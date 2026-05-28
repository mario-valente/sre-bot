"""Node for fetching metrics from Prometheus."""

import asyncio
from datetime import timedelta

import structlog

from sre_bot.agent.state import (
    AgentState,
    MetricPoint,
    MetricsData,
    MetricSeries,
    StateUpdate,
)
from sre_bot.clients.prometheus import PrometheusClient
from sre_bot.clients.protocols import MetricsQueryError
from sre_bot.config import get_settings
from sre_bot.queries.prometheus import MetricType, build_prometheus_query

logger = structlog.get_logger()


async def fetch_metrics(state: AgentState) -> StateUpdate:
    """
    Fetch metrics from Prometheus for the affected service.

    Queries CPU, memory, error rate, latency, and request rate
    for the time window around the alert.

    Args:
        state: Current agent state with alert context.

    Returns:
        Updated state with metrics data.
    """
    log = logger.bind(
        node="fetch_metrics",
        service=state.alert.service_name,
        namespace=state.alert.namespace,
    )
    log.info("fetching metrics from Prometheus")

    settings = get_settings()
    client = PrometheusClient()
    alert = state.alert

    # Define time window
    end_time = alert.timestamp
    start_time = end_time - timedelta(minutes=settings.lookback_minutes)

    # Build queries using safe templates
    try:
        queries = {
            "cpu": build_prometheus_query(
                MetricType.CPU_USAGE, alert.service_name, alert.namespace
            ),
            "memory": build_prometheus_query(
                MetricType.MEMORY_USAGE, alert.service_name, alert.namespace
            ),
            "error_rate": build_prometheus_query(
                MetricType.ERROR_RATE, alert.service_name, alert.namespace
            ),
            "latency_p99": build_prometheus_query(
                MetricType.LATENCY_P99, alert.service_name, alert.namespace
            ),
            "request_rate": build_prometheus_query(
                MetricType.REQUEST_RATE, alert.service_name, alert.namespace
            ),
        }
    except Exception as e:
        log.error("failed to build queries", error=str(e))
        return {
            "metrics": MetricsData(query_errors=[f"Query build failed: {str(e)}"]),
            "errors": [f"Prometheus query build failed: {str(e)}"],
        }

    # Execute queries in parallel
    results = await asyncio.gather(
        *[
            _safe_query(client, name, query, start_time, end_time, log)
            for name, query in queries.items()
        ],
        return_exceptions=True,
    )

    # Process results
    metrics_data = MetricsData()
    query_errors = []

    for (name, _), result in zip(queries.items(), results, strict=False):
        if isinstance(result, BaseException):
            query_errors.append(f"{name}: {str(result)}")
            continue

        # At this point, result is the expected type (not an exception)
        series_list = _parse_series(result)

        if name == "cpu":
            metrics_data.cpu_usage = series_list
        elif name == "memory":
            metrics_data.memory_usage = series_list
        elif name == "error_rate":
            metrics_data.error_rate_5xx = series_list
        elif name == "latency_p99":
            metrics_data.latency_p99 = series_list
        elif name == "request_rate":
            metrics_data.request_rate = series_list

    # Detect anomalies
    metrics_data.anomalies_detected = _detect_anomalies(metrics_data)
    metrics_data.query_errors = query_errors

    log.info(
        "metrics fetched",
        cpu_series=len(metrics_data.cpu_usage),
        memory_series=len(metrics_data.memory_usage),
        anomalies=len(metrics_data.anomalies_detected),
        errors=len(query_errors),
    )

    return {"metrics": metrics_data}


async def _safe_query(
    client: PrometheusClient,
    name: str,
    query: str,
    start_time,
    end_time,
    log,
) -> list[dict]:
    """Execute query with error handling."""
    try:
        return await client.query_range(query, start_time, end_time)
    except MetricsQueryError as e:
        log.warning("query failed", query_name=name, error=str(e))
        raise
    except Exception as e:
        log.exception("unexpected error in query", query_name=name)
        raise MetricsQueryError(f"Unexpected error: {str(e)}") from e


def _parse_series(raw_data: list[dict]) -> list[MetricSeries]:
    """Convert raw Prometheus data to MetricSeries objects."""
    series_list = []
    for item in raw_data:
        values = [
            MetricPoint(timestamp=v["timestamp"], value=v["value"]) for v in item.get("values", [])
        ]
        series_list.append(
            MetricSeries(
                labels=item.get("labels", {}),
                values=values,
            )
        )
    return series_list


def _detect_anomalies(metrics: MetricsData) -> list[str]:
    """
    Detect anomalies in the collected metrics.

    Simple heuristics for MVP - can be enhanced with ML later.
    """
    anomalies = []

    # Check error rate spike
    if metrics.error_rate_5xx:
        for series in metrics.error_rate_5xx:
            if series.values:
                max_error_rate = max(v.value for v in series.values)
                if max_error_rate > 0.05:  # > 5% error rate
                    anomalies.append(f"High error rate detected: {max_error_rate:.1%}")
                    break

    # Check latency spike
    if metrics.latency_p99:
        for series in metrics.latency_p99:
            if series.values:
                max_latency = max(v.value for v in series.values)
                if max_latency > 1.0:  # > 1 second
                    anomalies.append(f"High P99 latency detected: {max_latency:.2f}s")
                    break

    # Check CPU spike
    if metrics.cpu_usage:
        for series in metrics.cpu_usage:
            if series.values:
                max_cpu = max(v.value for v in series.values)
                if max_cpu > 0.9:  # > 90% CPU
                    anomalies.append(f"High CPU usage detected: {max_cpu:.1%}")
                    break

    # Check memory spike
    if metrics.memory_usage:
        for series in metrics.memory_usage:
            if series.values:
                values = [v.value for v in series.values]
                if len(values) > 1:
                    # Check for rapid memory growth
                    growth = (values[-1] - values[0]) / max(values[0], 1)
                    if growth > 0.5:  # > 50% growth
                        anomalies.append(f"Rapid memory growth detected: {growth:.1%}")
                        break

    return anomalies
