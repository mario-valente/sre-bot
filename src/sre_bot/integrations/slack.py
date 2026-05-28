"""Slack integration using slack_bolt."""

import contextlib
import re
from datetime import datetime
from typing import Any

import structlog
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

from sre_bot.agent.graph import run_investigation
from sre_bot.agent.state import AgentState, AlertContext
from sre_bot.config import get_settings
from sre_bot.db.repository import (
    IncidentRepository,
    LearnedSolutionRepository,
    get_session,
)

logger = structlog.get_logger()

# Global app instance
_slack_app: AsyncApp | None = None


def create_slack_app() -> AsyncApp:
    """
    Create and configure the Slack Bolt app.

    Returns:
        Configured AsyncApp instance.
    """
    settings = get_settings()

    if not settings.slack_bot_token or not settings.slack_signing_secret:
        raise ValueError("SLACK_BOT_TOKEN and SLACK_SIGNING_SECRET must be configured")

    app = AsyncApp(
        token=settings.slack_bot_token.get_secret_value(),
        signing_secret=settings.slack_signing_secret.get_secret_value(),
    )

    # Register event handlers
    _register_handlers(app)

    return app


def _register_handlers(app: AsyncApp) -> None:
    """Register all Slack event handlers."""

    @app.event("message")
    async def handle_message(event: dict[str, Any], say: Any, client: Any) -> None:
        """
        Handle incoming messages in alert channels.

        Looks for messages that match alert patterns and triggers investigation.
        """
        log = logger.bind(
            handler="message",
            channel=event.get("channel"),
            user=event.get("user"),
        )

        # Skip bot messages and thread replies
        if event.get("bot_id") or event.get("thread_ts"):
            return

        # Check if this is an alert channel
        settings = get_settings()
        channel_info = await client.conversations_info(channel=event["channel"])
        channel_name = channel_info.get("channel", {}).get("name", "")

        if settings.slack_alert_channel not in channel_name:
            return

        text = event.get("text", "")

        # Try to parse as Alertmanager message
        alert_context = _parse_slack_alert(text, event)
        if not alert_context:
            log.debug("message does not match alert pattern")
            return

        log.info(
            "alert detected in Slack",
            alert_name=alert_context.alert_name,
            service=alert_context.service_name,
        )

        # Acknowledge the alert
        await say(
            text=f":robot_face: Analyzing incident for *{alert_context.service_name}*...",
            thread_ts=event.get("ts"),
        )

        # Run investigation
        try:
            initial_state = AgentState(
                alert=alert_context,
                slack_channel=event.get("channel"),
                slack_thread_ts=event.get("ts"),
            )

            await run_investigation(initial_state)

        except Exception as e:
            log.exception("investigation failed")
            await say(
                text=f":x: Investigation failed: {str(e)}",
                thread_ts=event.get("ts"),
            )

    @app.event("app_mention")
    async def handle_mention(event: dict[str, Any], say: Any, client: Any) -> None:
        """
        Handle direct mentions of the bot.

        Supports commands like:
        - @bot analyze <service>
        - @bot help
        """
        log = logger.bind(
            handler="app_mention",
            channel=event.get("channel"),
            user=event.get("user"),
        )

        text = event.get("text", "").lower()

        if "help" in text:
            await say(
                text=_get_help_text(),
                thread_ts=event.get("thread_ts") or event.get("ts"),
            )
            return

        if "analyze" in text:
            # Extract service name from mention
            match = re.search(r"analyze\s+(\S+)", text)
            if match:
                service_name = match.group(1)
                await _trigger_manual_investigation(service_name, event, say, client, log)
                return

        # Default response
        await say(
            text="I can help with incident analysis. Try `@sre-copilot help` for commands.",
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )

    @app.action(re.compile(r"^feedback_.*"))
    async def handle_feedback_action(ack: Any, body: Any, client: Any) -> None:
        """
        Handle feedback button actions.

        Action IDs:
        - feedback_correct_<incident_id>
        - feedback_incorrect_<incident_id>
        - feedback_partial_<incident_id>
        """
        await ack()

        log = logger.bind(
            handler="feedback_action",
            user=body.get("user", {}).get("id"),
        )

        action = body.get("actions", [{}])[0]
        action_id = action.get("action_id", "")

        # Parse action ID
        parts = action_id.split("_")
        if len(parts) < 3:
            log.warning("invalid feedback action", action_id=action_id)
            return

        feedback_type = parts[1]  # correct, incorrect, partial
        incident_id = int(parts[2])

        log.info(
            "feedback received",
            feedback_type=feedback_type,
            incident_id=incident_id,
        )

        try:
            session = get_session()
            try:
                incident_repo = IncidentRepository(session)
                solution_repo = LearnedSolutionRepository(session)

                # Get incident
                incident = await incident_repo.get_by_id(incident_id)
                if not incident:
                    log.warning("incident not found", incident_id=incident_id)
                    return

                # Add feedback
                user = body.get("user", {})
                await incident_repo.add_feedback(
                    incident_id=incident_id,
                    feedback_type=feedback_type,
                    slack_user_id=user.get("id"),
                    slack_username=user.get("username"),
                )

                # If feedback is "correct", create a learned solution
                if feedback_type == "correct" and incident.probable_root_cause:
                    await solution_repo.create_from_incident(
                        incident=incident,
                        validated_by=user.get("username"),
                    )
                    log.info(
                        "learned solution created from incident",
                        incident_id=incident_id,
                    )

                # Update the message to show feedback was received
                channel = body.get("channel", {}).get("id")
                message_ts = body.get("message", {}).get("ts")

                if channel and message_ts:
                    await client.chat_update(
                        channel=channel,
                        ts=message_ts,
                        text=body.get("message", {}).get("text", ""),
                        blocks=_update_blocks_with_feedback(
                            body.get("message", {}).get("blocks", []),
                            feedback_type,
                            user.get("username", "someone"),
                        ),
                    )
            finally:
                await session.close()

        except Exception as e:
            log.exception("failed to process feedback")
            # Try to notify the user
            with contextlib.suppress(Exception):
                await client.chat_postEphemeral(
                    channel=body.get("channel", {}).get("id"),
                    user=body.get("user", {}).get("id"),
                    text=f":warning: Failed to save feedback: {str(e)}",
                )

    @app.command("/sre-analyze")
    async def handle_analyze_command(ack: Any, body: Any, say: Any) -> None:
        """
        Handle /sre-analyze slash command.

        Usage: /sre-analyze <service-name> [namespace]
        """
        await ack()

        log = logger.bind(
            handler="slash_command",
            command="/sre-analyze",
            user=body.get("user_id"),
        )

        text = body.get("text", "").strip()
        if not text:
            await say("Usage: `/sre-analyze <service-name> [namespace]`")
            return

        parts = text.split()
        service_name = parts[0]
        namespace = parts[1] if len(parts) > 1 else "production"

        log.info("manual analysis requested", service=service_name, namespace=namespace)

        # Create alert context for manual analysis
        alert_context = AlertContext(
            alert_name="ManualAnalysis",
            severity="info",
            service_name=service_name,
            cluster="unknown",
            namespace=namespace,
            timestamp=datetime.utcnow(),
            description="Manual analysis requested by user",
        )

        await say(f":mag: Starting analysis for *{service_name}* in `{namespace}`...")

        try:
            initial_state = AgentState(
                alert=alert_context,
                slack_channel=body.get("channel_id"),
            )

            await run_investigation(initial_state)

        except Exception as e:
            log.exception("manual analysis failed")
            await say(f":x: Analysis failed: {str(e)}")


async def _trigger_manual_investigation(
    service_name: str,
    event: dict[str, Any],
    say: Any,
    client: Any,  # noqa: ARG001
    log: Any,
) -> None:
    """Trigger a manual investigation for a service."""

    alert_context = AlertContext(
        alert_name="ManualInvestigation",
        severity="info",
        service_name=service_name,
        cluster="unknown",
        namespace="production",
        timestamp=datetime.utcnow(),
        description="Manual investigation triggered via Slack",
    )

    log.info("triggering manual investigation", service=service_name)

    await say(
        text=f":mag: Starting investigation for *{service_name}*...",
        thread_ts=event.get("thread_ts") or event.get("ts"),
    )

    try:
        initial_state = AgentState(
            alert=alert_context,
            slack_channel=event.get("channel"),
            slack_thread_ts=event.get("thread_ts") or event.get("ts"),
        )

        await run_investigation(initial_state)

    except Exception as e:
        log.exception("manual investigation failed")
        await say(
            text=f":x: Investigation failed: {str(e)}",
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )


def _parse_slack_alert(text: str, event: dict[str, Any]) -> AlertContext | None:
    """
    Parse a Slack message to extract alert context.

    Supports common Alertmanager message formats.
    """
    # Common patterns for Alertmanager messages
    patterns = {
        "alert_name": r"\[FIRING(?::\d+)?\]\s*(\w+)",
        "service": r"(?:service|app)[=:]\s*[\"']?(\S+)[\"']?",
        "namespace": r"namespace[=:]\s*[\"']?(\S+)[\"']?",
        "severity": r"severity[=:]\s*[\"']?(\w+)[\"']?",
        "cluster": r"cluster[=:]\s*[\"']?(\S+)[\"']?",
    }

    extracted = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            extracted[key] = match.group(1)

    # Must have at least alert name and service
    if not extracted.get("alert_name") or not extracted.get("service"):
        return None

    # Map severity
    severity_raw = extracted.get("severity", "warning").lower()
    severity = (
        "critical" if "crit" in severity_raw else ("warning" if "warn" in severity_raw else "info")
    )

    return AlertContext(
        alert_name=extracted.get("alert_name", "UnknownAlert"),
        severity=severity,
        service_name=extracted["service"],
        cluster=extracted.get("cluster", "unknown"),
        namespace=extracted.get("namespace", "production"),
        timestamp=datetime.utcnow(),
        raw_payload={"slack_event": event, "text": text},
    )


def _get_help_text() -> str:
    """Get help text for the bot."""
    return """*SRE Copilot* - Automated Incident Analysis

*Commands:*
• `@sre-copilot analyze <service-name>` - Analyze a service
• `@sre-copilot help` - Show this help message
• `/sre-analyze <service-name> [namespace]` - Run analysis via slash command

*Automatic Analysis:*
The bot automatically analyzes alerts posted in the alerts channel.

*What it does:*
1. Queries Prometheus for metrics (CPU, memory, error rate, latency)
2. Queries Loki for error logs
3. Queries Tempo for failed/slow traces
4. Checks GitHub for recent deployments
5. Uses AI to synthesize a root cause analysis

*Learning System:*
The bot learns from feedback! When you mark an analysis as "Correct",
it saves the solution and uses it for future similar incidents.

:robot_face: Powered by SRE Copilot"""


def _update_blocks_with_feedback(
    blocks: list[dict[str, Any]],
    feedback_type: str,
    username: str,
) -> list[dict[str, Any]]:
    """Update message blocks to show feedback was received."""
    updated_blocks = []

    feedback_emoji = {
        "correct": ":white_check_mark:",
        "incorrect": ":x:",
        "partial": ":warning:",
    }.get(feedback_type, ":question:")

    feedback_text = {
        "correct": "marked as correct",
        "incorrect": "marked as incorrect",
        "partial": "marked as partially correct",
    }.get(feedback_type, "gave feedback")

    for block in blocks:
        # Replace the actions block with feedback confirmation
        if block.get("type") == "actions":
            updated_blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"{feedback_emoji} *@{username}* {feedback_text}",
                        }
                    ],
                }
            )
            if feedback_type == "correct":
                updated_blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": ":brain: Solution saved for future incidents!",
                            }
                        ],
                    }
                )
        else:
            updated_blocks.append(block)

    return updated_blocks


def build_feedback_blocks(incident_id: int) -> list[dict[str, Any]]:
    """
    Build Slack blocks for feedback buttons.

    Args:
        incident_id: ID of the incident to provide feedback for.

    Returns:
        List of Slack blocks with feedback buttons.
    """
    return [
        {
            "type": "divider",
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Was this analysis helpful?* Your feedback helps improve future analyses.",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Correct", "emoji": True},
                    "style": "primary",
                    "action_id": f"feedback_correct_{incident_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Partially Correct", "emoji": True},
                    "action_id": f"feedback_partial_{incident_id}",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Incorrect", "emoji": True},
                    "style": "danger",
                    "action_id": f"feedback_incorrect_{incident_id}",
                },
            ],
        },
    ]


def get_slack_app() -> AsyncApp:
    """
    Get the Slack app instance (singleton).

    Returns:
        Configured AsyncApp instance.
    """
    global _slack_app

    if _slack_app is None:
        _slack_app = create_slack_app()

    return _slack_app


async def start_slack_listener() -> None:
    """
    Start the Slack Socket Mode listener.

    This runs indefinitely and handles incoming events.
    """
    settings = get_settings()

    if not settings.enable_slack_listener:
        logger.info("Slack listener disabled")
        return

    if not settings.slack_app_token:
        raise ValueError("SLACK_APP_TOKEN must be configured for Socket Mode")

    log = logger.bind(component="slack_listener")
    log.info("starting Slack Socket Mode listener")

    app = get_slack_app()
    handler = AsyncSocketModeHandler(
        app=app,
        app_token=settings.slack_app_token.get_secret_value(),
    )

    await handler.start_async()
