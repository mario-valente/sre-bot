"""Node for fetching correlated alerts from Alertmanager."""

from datetime import datetime

import structlog

from sre_bot.agent.state import (
    AgentState,
    CorrelatedAlert,
    CorrelatedAlertsData,
    StateUpdate,
)
from sre_bot.clients.alertmanager import AlertmanagerClient, AlertmanagerError
from sre_bot.config import get_settings

logger = structlog.get_logger()


async def fetch_correlated_alerts(state: AgentState) -> StateUpdate:
    """
    Fetch potentially related alerts from Alertmanager.

    This node searches for alerts that may have caused or contributed
    to the current incident by looking at:
    - Recent alerts from the same service (pattern detection)
    - Recent alerts in the same namespace (dependency issues)
    - Infrastructure alerts (DB, network, etc.) that could cascade

    Example correlations:
    - Pod CrashLoopBackOff might be caused by Database connection failure
    - High latency might be caused by Redis/Cache being unavailable
    - Multiple service failures might indicate network or cluster issues

    Args:
        state: Current agent state with alert context.

    Returns:
        Updated state with correlated alerts data.
    """
    log = logger.bind(
        node="fetch_correlated_alerts",
        service=state.alert.service_name,
        namespace=state.alert.namespace,
    )
    log.info("fetching correlated alerts from Alertmanager")

    settings = get_settings()
    alert = state.alert
    time_window = settings.correlation_window_minutes

    try:
        client = AlertmanagerClient()

        # Fetch recent alerts from Alertmanager
        recent_alerts = await client.get_recent_alerts(
            since_minutes=time_window,
            exclude_alert_name=alert.alert_name,
            exclude_service=alert.service_name,
        )

        # Categorize alerts
        same_service_alerts: list[CorrelatedAlert] = []
        same_namespace_alerts: list[CorrelatedAlert] = []
        infra_alerts: list[CorrelatedAlert] = []

        for am_alert in recent_alerts:
            corr_alert = _alertmanager_to_correlated_alert(am_alert)

            # Same service (but different alert)
            if am_alert["service_name"] == alert.service_name:
                same_service_alerts.append(corr_alert)

            # Same namespace (potential dependency)
            elif am_alert["namespace"] == alert.namespace:
                same_namespace_alerts.append(corr_alert)

            # Infrastructure alert
            if _is_infrastructure_alert(am_alert) and corr_alert not in infra_alerts:
                infra_alerts.append(corr_alert)

        # Identify potential root causes
        potential_root_causes = _identify_potential_root_causes(
            infra_alerts=infra_alerts,
            same_namespace_alerts=same_namespace_alerts,
            current_alert_time=alert.timestamp,
        )

        correlated_data = CorrelatedAlertsData(
            same_service_alerts=same_service_alerts[:10],
            same_namespace_alerts=same_namespace_alerts[:15],
            dependency_alerts=infra_alerts[:10],
            potential_root_cause_alerts=potential_root_causes,
            time_window_minutes=time_window,
        )

        log.info(
            "correlated alerts fetched",
            same_service=len(same_service_alerts),
            same_namespace=len(same_namespace_alerts),
            infrastructure=len(infra_alerts),
            potential_root_causes=len(potential_root_causes),
        )

        return {"correlated_alerts": correlated_data}

    except AlertmanagerError as e:
        log.warning("alertmanager error, continuing without correlation", error=str(e))
        return {
            "correlated_alerts": CorrelatedAlertsData(
                time_window_minutes=time_window,
                query_errors=[f"Alertmanager error: {str(e)}"],
            ),
        }
    except Exception as e:
        log.exception("failed to fetch correlated alerts")
        return {
            "correlated_alerts": CorrelatedAlertsData(
                time_window_minutes=time_window,
                query_errors=[f"Failed to fetch correlated alerts: {str(e)}"],
            ),
            "errors": [f"Correlated alerts fetch failed: {str(e)}"],
        }


def _alertmanager_to_correlated_alert(am_alert: dict) -> CorrelatedAlert:
    """Convert an Alertmanager alert to a CorrelatedAlert."""
    annotations = am_alert.get("annotations", {})

    return CorrelatedAlert(
        alert_name=am_alert["alert_name"],
        service_name=am_alert["service_name"],
        severity=am_alert["severity"],
        timestamp=am_alert["starts_at"],
        probable_root_cause=None,  # Alertmanager doesn't have analysis
        summary=annotations.get("summary", annotations.get("description")),
        confidence=None,
    )


def _is_infrastructure_alert(am_alert: dict) -> bool:
    """Check if an alert is infrastructure-related."""
    # Infrastructure keywords that often indicate root causes
    infra_keywords = [
        "database",
        "db",
        "postgres",
        "mysql",
        "mongo",
        "redis",
        "cache",
        "memcached",
        "kafka",
        "rabbitmq",
        "queue",
        "message",
        "network",
        "dns",
        "connection",
        "timeout",
        "oom",
        "memory",
        "cpu",
        "disk",
        "node",
        "cluster",
        "istio",
        "envoy",
        "nginx",
        "etcd",
        "zookeeper",
        "consul",
        "vault",
    ]

    alert_name = am_alert["alert_name"].lower()
    service_name = am_alert["service_name"].lower()
    annotations = am_alert.get("annotations", {})
    description = (annotations.get("description", "") + annotations.get("summary", "")).lower()

    for keyword in infra_keywords:
        if keyword in alert_name or keyword in service_name or keyword in description:
            return True

    return False


def _identify_potential_root_causes(
    infra_alerts: list[CorrelatedAlert],
    same_namespace_alerts: list[CorrelatedAlert],
    current_alert_time: datetime,
) -> list[CorrelatedAlert]:
    """
    Identify alerts that are likely root causes for the current incident.

    Prioritizes:
    - Infrastructure alerts that started BEFORE the current alert
    - Critical severity alerts
    - Alerts from critical services (databases, caches, etc.)
    """
    potential_causes: list[CorrelatedAlert] = []

    # Critical infrastructure services
    critical_services = [
        "database",
        "db",
        "postgres",
        "mysql",
        "mongo",
        "redis",
        "cache",
        "memcached",
        "kafka",
        "rabbitmq",
        "queue",
        "network",
        "dns",
        "etcd",
    ]

    # Check infrastructure alerts
    for alert in infra_alerts:
        # Must have started BEFORE current alert
        if alert.timestamp >= current_alert_time:
            continue

        # Check if critical infrastructure
        is_critical_service = any(
            kw in alert.service_name.lower() or kw in alert.alert_name.lower()
            for kw in critical_services
        )

        # Critical severity or critical service
        if (alert.severity == "critical" or is_critical_service) and alert not in potential_causes:
            potential_causes.append(alert)

    # Check namespace alerts for critical issues
    for alert in same_namespace_alerts:
        if alert.timestamp >= current_alert_time:
            continue

        if alert.severity == "critical" and alert not in potential_causes:
            potential_causes.append(alert)

    # Sort by timestamp (oldest first - more likely to be root cause)
    # and then by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    potential_causes.sort(
        key=lambda x: (x.timestamp, severity_order.get(x.severity, 3)),
    )

    # Return top 5 most likely root causes
    return potential_causes[:5]
