"""Alertmanager HTTP client implementation."""

from datetime import datetime
from typing import Any

import httpx
import structlog

from sre_bot.config import get_settings

logger = structlog.get_logger()


class AlertmanagerError(Exception):
    """Exception raised when Alertmanager API calls fail."""

    pass


class AlertmanagerClient:
    """
    HTTP client for Alertmanager API.

    Used to fetch active and recent alerts for correlation analysis.

    API Documentation:
        https://prometheus.io/docs/alerting/latest/alertmanager/
        https://github.com/prometheus/alertmanager/blob/main/api/v2/openapi.yaml
    """

    def __init__(
        self,
        base_url: str | None = None,
        timeout: float | None = None,
        headers: dict[str, str] | None = None,
    ):
        """
        Initialize Alertmanager client.

        Args:
            base_url: Alertmanager server URL. Defaults to settings.
            timeout: Request timeout in seconds. Defaults to settings.
            headers: Additional HTTP headers.
        """
        settings = get_settings()
        self.base_url = (base_url or settings.alertmanager_url).rstrip("/")
        self.timeout = timeout or settings.query_timeout_seconds
        self.headers = headers or {}
        self._log = logger.bind(client="alertmanager", base_url=self.base_url)

    async def get_alerts(
        self,
        active: bool = True,
        silenced: bool = False,
        inhibited: bool = False,
        unprocessed: bool = False,
        filter_labels: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get alerts from Alertmanager.

        Endpoint: GET /api/v2/alerts

        Args:
            active: Include active alerts.
            silenced: Include silenced alerts.
            inhibited: Include inhibited alerts.
            unprocessed: Include unprocessed alerts.
            filter_labels: Filter alerts by labels (e.g., {"severity": "critical"}).

        Returns:
            List of alert objects from Alertmanager.

        Raises:
            AlertmanagerError: If the request fails.
        """
        self._log.debug("fetching alerts", active=active, silenced=silenced)

        params: dict[str, str | list[str]] = {
            "active": str(active).lower(),
            "silenced": str(silenced).lower(),
            "inhibited": str(inhibited).lower(),
            "unprocessed": str(unprocessed).lower(),
        }

        # Add label filters (Alertmanager uses filter[] query param)
        if filter_labels:
            filters = [f'{k}="{v}"' for k, v in filter_labels.items()]
            params["filter"] = filters

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v2/alerts",
                    params=params,
                    headers=self.headers,
                )
                response.raise_for_status()
                alerts = response.json()

                self._log.debug("alerts fetched", count=len(alerts))
                return alerts

        except httpx.HTTPStatusError as e:
            self._log.error("HTTP error", status=e.response.status_code)
            raise AlertmanagerError(f"Alertmanager HTTP error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            self._log.error("request error", error=str(e))
            raise AlertmanagerError(f"Alertmanager request error: {e}") from e

    async def get_alert_groups(self) -> list[dict[str, Any]]:
        """
        Get alert groups from Alertmanager.

        Endpoint: GET /api/v2/alerts/groups

        Returns:
            List of alert group objects.

        Raises:
            AlertmanagerError: If the request fails.
        """
        self._log.debug("fetching alert groups")

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/api/v2/alerts/groups",
                    headers=self.headers,
                )
                response.raise_for_status()
                groups = response.json()

                self._log.debug("alert groups fetched", count=len(groups))
                return groups

        except httpx.HTTPStatusError as e:
            self._log.error("HTTP error", status=e.response.status_code)
            raise AlertmanagerError(f"Alertmanager HTTP error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            self._log.error("request error", error=str(e))
            raise AlertmanagerError(f"Alertmanager request error: {e}") from e

    async def get_recent_alerts(
        self,
        since_minutes: int = 120,
        exclude_alert_name: str | None = None,
        exclude_service: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get recent alerts suitable for correlation analysis.

        Fetches both active and resolved alerts, filtering by time window.

        Args:
            since_minutes: Time window in minutes to look back.
            exclude_alert_name: Alert name to exclude (current alert).
            exclude_service: Service name to exclude.

        Returns:
            List of recent alerts, sorted by startsAt (most recent first).
        """
        self._log.info(
            "fetching recent alerts for correlation",
            since_minutes=since_minutes,
            exclude_alert=exclude_alert_name,
        )

        # Get active alerts
        active_alerts = await self.get_alerts(
            active=True,
            silenced=True,  # Include silenced (may still be relevant)
            inhibited=True,  # Include inhibited
        )

        # Calculate time window
        now = datetime.utcnow()
        cutoff = now.timestamp() - (since_minutes * 60)

        # Filter and process alerts
        recent_alerts = []
        for alert in active_alerts:
            # Parse startsAt timestamp
            starts_at_str = alert.get("startsAt", "")
            try:
                # Alertmanager uses RFC3339 format
                starts_at = datetime.fromisoformat(starts_at_str.replace("Z", "+00:00"))
                alert_timestamp = starts_at.timestamp()
            except (ValueError, AttributeError):
                continue

            # Filter by time window
            if alert_timestamp < cutoff:
                continue

            # Get labels
            labels = alert.get("labels", {})
            alert_name = labels.get("alertname", "")
            service = labels.get("service", labels.get("job", ""))

            # Exclude current alert
            if (
                exclude_alert_name
                and alert_name == exclude_alert_name
                and exclude_service
                and service == exclude_service
            ):
                continue

            # Normalize alert data
            recent_alerts.append(
                {
                    "alert_name": alert_name,
                    "service_name": service,
                    "severity": labels.get("severity", "unknown"),
                    "namespace": labels.get("namespace", ""),
                    "cluster": labels.get("cluster", ""),
                    "status": alert.get("status", {}).get("state", "active"),
                    "starts_at": starts_at,
                    "ends_at": alert.get("endsAt"),
                    "labels": labels,
                    "annotations": alert.get("annotations", {}),
                    "fingerprint": alert.get("fingerprint", ""),
                }
            )

        # Sort by start time (most recent first)
        recent_alerts.sort(key=lambda x: x["starts_at"], reverse=True)

        self._log.info(
            "recent alerts found",
            total=len(recent_alerts),
            since_minutes=since_minutes,
        )

        return recent_alerts
