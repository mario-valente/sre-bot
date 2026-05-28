"""Node for fetching traces from Tempo."""

import asyncio
from collections import Counter
from datetime import timedelta

import structlog

from sre_bot.agent.state import AgentState, SpanInfo, StateUpdate, TracesData
from sre_bot.clients.protocols import TracesQueryError
from sre_bot.clients.tempo import TempoClient
from sre_bot.config import get_settings
from sre_bot.queries.tempo import TraceQueryType, build_tempo_query

logger = structlog.get_logger()


async def fetch_traces(state: AgentState) -> StateUpdate:
    """
    Fetch traces from Tempo for the affected service.

    Queries error traces and slow traces to identify
    bottlenecks and failure points.

    Args:
        state: Current agent state with alert context.

    Returns:
        Updated state with traces data.
    """
    log = logger.bind(
        node="fetch_traces",
        service=state.alert.service_name,
    )
    log.info("fetching traces from Tempo")

    settings = get_settings()
    client = TempoClient()
    alert = state.alert

    # Define time window
    end_time = alert.timestamp
    start_time = end_time - timedelta(minutes=settings.lookback_minutes)

    # Build queries
    try:
        queries = {
            "errors": (TraceQueryType.ERROR_TRACES, None),
            "slow": (TraceQueryType.SLOW_TRACES, "1s"),
            "failed_http": (TraceQueryType.FAILED_HTTP, None),
        }
    except Exception as e:
        log.error("failed to prepare queries", error=str(e))
        return {
            "traces": TracesData(query_errors=[f"Query prep failed: {str(e)}"]),
            "errors": [f"Tempo query prep failed: {str(e)}"],
        }

    # Execute searches in parallel
    results = await asyncio.gather(
        *[
            _safe_search(
                client,
                name,
                alert.service_name,
                start_time,
                end_time,
                query_type,
                threshold,
                log,
            )
            for name, (query_type, threshold) in queries.items()
        ],
        return_exceptions=True,
    )

    # Process results
    failed_traces: list[SpanInfo] = []
    slow_traces: list[SpanInfo] = []
    query_errors = []

    for (name, _), result in zip(queries.items(), results, strict=False):
        if isinstance(result, BaseException):
            query_errors.append(f"{name}: {str(result)}")
            continue

        # At this point, result is the expected type (not an exception)
        spans = _parse_trace_results(result)

        if name == "errors" or name == "failed_http":
            failed_traces.extend(spans)
        elif name == "slow":
            slow_traces.extend(spans)

    # Deduplicate
    failed_traces = _deduplicate_spans(failed_traces)[:50]
    slow_traces = _deduplicate_spans(slow_traces)[:50]

    # Identify bottleneck services
    bottleneck_services = _identify_bottlenecks(failed_traces + slow_traces)

    traces_data = TracesData(
        failed_traces=failed_traces,
        slow_traces=slow_traces,
        bottleneck_services=bottleneck_services,
        query_errors=query_errors,
    )

    log.info(
        "traces fetched",
        failed_count=len(failed_traces),
        slow_count=len(slow_traces),
        bottlenecks=bottleneck_services,
        errors=len(query_errors),
    )

    return {"traces": traces_data}


async def _safe_search(
    client: TempoClient,
    name: str,
    service_name: str,
    start_time,
    end_time,
    query_type: TraceQueryType,
    threshold: str | None,
    log,
) -> list[dict]:
    """Execute trace search with error handling."""
    try:
        # Build query
        query = build_tempo_query(query_type, service_name, threshold=threshold)
        log.debug("executing trace search", query_name=name, query=query)

        # Determine status filter
        status = (
            "error"
            if query_type
            in (
                TraceQueryType.ERROR_TRACES,
                TraceQueryType.FAILED_HTTP,
            )
            else None
        )

        # Determine min_duration
        min_duration = threshold if query_type == TraceQueryType.SLOW_TRACES else None

        return await client.search(
            service_name=service_name,
            start=start_time,
            end=end_time,
            min_duration=min_duration,
            status=status,
            limit=100,
        )
    except TracesQueryError as e:
        log.warning("search failed", query_name=name, error=str(e))
        raise
    except Exception as e:
        log.exception("unexpected error in search", query_name=name)
        raise TracesQueryError(f"Unexpected error: {str(e)}") from e


def _parse_trace_results(raw_data: list[dict]) -> list[SpanInfo]:
    """Convert raw Tempo data to SpanInfo objects."""
    spans = []
    for item in raw_data:
        spans.append(
            SpanInfo(
                trace_id=item.get("trace_id", ""),
                span_id="",  # Not available in search results
                service_name=item.get("root_service_name", ""),
                operation_name=item.get("root_trace_name", ""),
                duration_ms=item.get("duration_ms", 0),
                status="error" if "error" in str(item).lower() else "ok",
                error_message=None,
                timestamp=item.get("start_time"),
            )
        )
    return spans


def _deduplicate_spans(spans: list[SpanInfo]) -> list[SpanInfo]:
    """
    Remove duplicate spans based on trace ID.

    Keeps the span with the longest duration for each trace.
    """
    trace_map: dict[str, SpanInfo] = {}

    for span in spans:
        existing = trace_map.get(span.trace_id)
        if not existing or span.duration_ms > existing.duration_ms:
            trace_map[span.trace_id] = span

    # Sort by duration descending
    return sorted(trace_map.values(), key=lambda x: x.duration_ms, reverse=True)


def _identify_bottlenecks(spans: list[SpanInfo]) -> list[str]:
    """
    Identify services that appear frequently in error/slow traces.

    These are likely bottleneck candidates.
    """
    if not spans:
        return []

    service_counter: Counter = Counter()

    for span in spans:
        if span.service_name:
            service_counter[span.service_name] += 1

    # Return services that appear in more than 20% of traces
    threshold = max(len(spans) * 0.2, 2)
    bottlenecks = [
        service for service, count in service_counter.most_common(5) if count >= threshold
    ]

    return bottlenecks
