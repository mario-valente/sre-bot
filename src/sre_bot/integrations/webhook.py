"""Webhook receiver for Alertmanager alerts using FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

import structlog
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from sre_bot.agent.graph import run_investigation
from sre_bot.agent.nodes.extract_context import parse_alertmanager_payload
from sre_bot.agent.state import AgentState
from sre_bot.config import get_settings

logger = structlog.get_logger()


class AlertmanagerWebhook(BaseModel):
    """Alertmanager webhook payload structure."""

    version: str = "4"
    groupKey: str = ""
    truncatedAlerts: int = 0
    status: str = "firing"
    receiver: str = ""
    groupLabels: dict[str, str] = {}
    commonLabels: dict[str, str] = {}
    commonAnnotations: dict[str, str] = {}
    externalURL: str = ""
    alerts: list[dict[str, Any]] = []


class WebhookResponse(BaseModel):
    """Response for webhook requests."""

    status: str
    message: str
    investigation_id: str | None = None


class HealthResponse(BaseModel):
    """Response for health check."""

    status: str
    version: str
    timestamp: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:  # noqa: ARG001
    """Lifespan context manager for startup/shutdown."""
    log = logger.bind(component="webhook_server")
    log.info("webhook server starting")
    yield
    log.info("webhook server shutting down")


def create_webhook_app() -> FastAPI:
    """
    Create and configure the FastAPI webhook receiver.

    Returns:
        Configured FastAPI app.
    """
    app = FastAPI(
        title="SRE Copilot Webhook",
        description="Webhook receiver for Alertmanager alerts",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Register routes
    _register_routes(app)

    return app


def _register_routes(app: FastAPI) -> None:
    """Register all webhook routes."""

    @app.get("/health", response_model=HealthResponse)
    async def health_check() -> HealthResponse:
        """Health check endpoint."""
        return HealthResponse(
            status="healthy",
            version="0.1.0",
            timestamp=datetime.utcnow().isoformat(),
        )

    @app.get("/ready")
    async def readiness_check() -> dict[str, str]:
        """Readiness check endpoint."""
        # Could add checks for dependencies (Prometheus, Loki, etc.)
        return {"status": "ready"}

    @app.post("/webhook/alertmanager", response_model=WebhookResponse)
    async def receive_alertmanager_webhook(
        webhook: AlertmanagerWebhook,
        background_tasks: BackgroundTasks,
        request: Request,  # noqa: ARG001
    ) -> WebhookResponse:
        """
        Receive and process Alertmanager webhooks.

        This endpoint receives alerts from Alertmanager and triggers
        investigation for critical alerts.
        """
        log = logger.bind(
            handler="alertmanager_webhook",
            status=webhook.status,
            alerts_count=len(webhook.alerts),
            group_key=webhook.groupKey,
        )

        log.info("received alertmanager webhook")

        # Only process firing alerts
        if webhook.status != "firing":
            log.debug("ignoring non-firing alert")
            return WebhookResponse(
                status="ignored",
                message=f"Alert status '{webhook.status}' ignored",
            )

        # Filter for actionable alerts (aligned with Alertmanager route)
        allowed_severities = {"critical", "warning"}
        critical_alerts: list[dict[str, Any]] = []
        evaluated_alerts: list[dict[str, Any]] = []
        for alert in webhook.alerts:
            labels = {
                **webhook.groupLabels,
                **webhook.commonLabels,
                **alert.get("labels", {}),
            }
            severity = str(labels.get("severity", "")).lower()
            alert_status = str(alert.get("status") or webhook.status).lower()
            matches = severity in allowed_severities and alert_status == "firing"

            evaluated_alerts.append(
                {
                    "alertname": labels.get("alertname"),
                    "service": labels.get("service") or labels.get("service_name"),
                    "severity": severity,
                    "status": alert_status,
                    "matches_filter": matches,
                }
            )

            if matches:
                critical_alerts.append(alert)

        log.info(
            "alert filtering completed",
            critical_count=len(critical_alerts),
            evaluated_count=len(evaluated_alerts),
            evaluated_alerts=evaluated_alerts,
        )

        if not critical_alerts:
            observed = [
                {
                    "severity": str(
                        (
                            {
                                **webhook.groupLabels,
                                **webhook.commonLabels,
                                **a.get("labels", {}),
                            }
                        ).get("severity", "")
                    ).lower(),
                    "status": str(a.get("status") or webhook.status).lower(),
                }
                for a in webhook.alerts
            ]
            log.info(
                "no actionable firing alerts",
                allowed_severities=sorted(allowed_severities),
                observed_alerts=observed,
            )
            return WebhookResponse(
                status="ignored",
                message="No actionable firing alerts to process",
            )

        # Generate investigation ID
        investigation_id = f"inv-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        # Process each critical alert
        for index, alert in enumerate(critical_alerts):
            labels = {
                **webhook.groupLabels,
                **webhook.commonLabels,
                **alert.get("labels", {}),
            }

            log.info(
                "scheduling alert background task",
                investigation_id=investigation_id,
                alert_index=index,
                alertname=labels.get("alertname"),
                service=labels.get("service") or labels.get("service_name"),
            )

            background_tasks.add_task(
                _process_alert,
                alert,
                webhook.model_dump(),
                investigation_id,
            )

        log.info(
            "investigations triggered",
            count=len(critical_alerts),
            investigation_id=investigation_id,
        )

        return WebhookResponse(
            status="accepted",
            message=f"Processing {len(critical_alerts)} actionable alert(s)",
            investigation_id=investigation_id,
        )

    @app.post("/webhook/custom")
    async def receive_custom_webhook(
        request: Request,
        background_tasks: BackgroundTasks,
    ) -> WebhookResponse:
        """
        Receive custom webhook payloads.

        Supports custom alert formats with required fields:
        - service_name
        - severity
        - namespace (optional, defaults to "production")
        """
        log = logger.bind(handler="custom_webhook")

        try:
            payload = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload") from None

        # Validate required fields
        if "service_name" not in payload:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: service_name",
            )

        if "severity" not in payload:
            raise HTTPException(
                status_code=400,
                detail="Missing required field: severity",
            )

        log.info(
            "received custom webhook",
            service=payload.get("service_name"),
            severity=payload.get("severity"),
        )

        investigation_id = f"inv-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

        background_tasks.add_task(
            _process_custom_alert,
            payload,
            investigation_id,
        )

        return WebhookResponse(
            status="accepted",
            message="Processing alert",
            investigation_id=investigation_id,
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(
        request: Request,  # noqa: ARG001
        exc: Exception,  # noqa: ARG001
    ) -> JSONResponse:
        """Handle uncaught exceptions."""
        logger.exception("unhandled exception in webhook handler")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal server error"},
        )


async def _process_alert(
    alert: dict[str, Any],
    full_payload: dict[str, Any],
    investigation_id: str,
) -> None:
    """
    Process a single alert in the background.

    Args:
        alert: Single alert from Alertmanager.
        full_payload: Complete webhook payload.
        investigation_id: Unique ID for this investigation.
    """
    log = logger.bind(
        handler="alert_processor",
        investigation_id=investigation_id,
        alert_name=alert.get("labels", {}).get("alertname"),
    )

    try:
        log.info(
            "background processing started",
            alert_status=alert.get("status"),
            alert_labels=alert.get("labels", {}),
        )

        # Parse alert into context
        payload_for_parser = {
            "alerts": [alert],
            "commonLabels": full_payload.get("commonLabels", {}),
            "groupLabels": full_payload.get("groupLabels", {}),
            "commonAnnotations": full_payload.get("commonAnnotations", {}),
        }
        alert_context = parse_alertmanager_payload(payload_for_parser)

        log.info(
            "alert context parsed",
            service=alert_context.service_name,
            namespace=alert_context.namespace,
            cluster=alert_context.cluster,
            severity=alert_context.severity,
        )

        # Create initial state
        settings = get_settings()
        initial_state = AgentState(
            alert=alert_context,
            slack_channel=settings.slack_alert_channel if settings.slack_bot_token else None,
        )

        log.info(
            "initial state created",
            slack_enabled=bool(settings.slack_bot_token),
            slack_channel=initial_state.slack_channel,
        )

        # Run investigation
        final_state = await run_investigation(initial_state)

        log.info(
            "investigation completed",
            has_analysis=final_state.analysis is not None,
            errors=len(final_state.errors) if final_state.errors else 0,
        )

        if final_state.errors:
            log.warning("investigation completed with errors", errors=final_state.errors)

        if final_state.analysis is None:
            log.warning("investigation completed without analysis")

    except Exception:
        log.exception("investigation failed")


async def _process_custom_alert(
    payload: dict[str, Any],
    investigation_id: str,
) -> None:
    """
    Process a custom alert in the background.

    Args:
        payload: Custom alert payload.
        investigation_id: Unique ID for this investigation.
    """
    log = logger.bind(
        handler="custom_alert_processor",
        investigation_id=investigation_id,
        service=payload.get("service_name"),
    )

    try:
        from sre_bot.agent.state import AlertContext

        # Build alert context from custom payload
        severity_raw = payload.get("severity", "warning").lower()
        severity = (
            "critical"
            if "crit" in severity_raw
            else ("warning" if "warn" in severity_raw else "info")
        )

        alert_context = AlertContext(
            alert_name=payload.get("alert_name", "CustomAlert"),
            severity=severity,
            service_name=payload["service_name"],
            cluster=payload.get("cluster", "unknown"),
            namespace=payload.get("namespace", "production"),
            pod=payload.get("pod"),
            timestamp=datetime.utcnow(),
            description=payload.get("description", ""),
            raw_payload=payload,
        )

        log.info(
            "starting custom investigation",
            service=alert_context.service_name,
            namespace=alert_context.namespace,
        )

        # Create initial state
        settings = get_settings()
        initial_state = AgentState(
            alert=alert_context,
            slack_channel=settings.slack_alert_channel if settings.slack_bot_token else None,
        )

        # Run investigation
        final_state = await run_investigation(initial_state)

        log.info(
            "custom investigation completed",
            has_analysis=final_state.analysis is not None,
            errors=len(final_state.errors) if final_state.errors else 0,
        )

    except Exception:
        log.exception("custom investigation failed")


# Module-level app instance
_webhook_app: FastAPI | None = None


def get_webhook_app() -> FastAPI:
    """
    Get the webhook app instance (singleton).

    Returns:
        Configured FastAPI app.
    """
    global _webhook_app

    if _webhook_app is None:
        _webhook_app = create_webhook_app()

    return _webhook_app


async def start_webhook_server() -> None:
    """
    Start the webhook server.

    This runs indefinitely and handles incoming webhooks.
    """
    settings = get_settings()

    if not settings.enable_webhook:
        logger.info("webhook server disabled")
        return

    log = logger.bind(
        component="webhook_server",
        host=settings.webhook_host,
        port=settings.webhook_port,
    )
    log.info("starting webhook server")

    app = get_webhook_app()

    config = uvicorn.Config(
        app=app,
        host=settings.webhook_host,
        port=settings.webhook_port,
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()
