"""Node for fetching logs from Loki."""

import asyncio
from collections import Counter
from datetime import datetime, timedelta

import structlog

from sre_bot.agent.state import AgentState, LogEntry, LogsData, StateUpdate
from sre_bot.clients.loki import LokiClient
from sre_bot.clients.protocols import LogsQueryError
from sre_bot.config import get_settings
from sre_bot.queries.loki import LogQueryType, build_loki_query

logger = structlog.get_logger()


async def fetch_logs(state: AgentState) -> StateUpdate:
    """
    Fetch logs from Loki for the affected service.

    Queries error and fatal logs, looking for patterns
    that might indicate the root cause.

    Args:
        state: Current agent state with alert context.

    Returns:
        Updated state with logs data.
    """
    log = logger.bind(
        node="fetch_logs",
        service=state.alert.service_name,
        namespace=state.alert.namespace,
    )
    log.info("fetching logs from Loki")

    settings = get_settings()
    client = LokiClient()
    alert = state.alert

    # Define time window
    end_time = alert.timestamp
    start_time = end_time - timedelta(minutes=settings.lookback_minutes)

    # Build queries
    try:
        queries = {
            "errors": build_loki_query(
                LogQueryType.ALL_ERRORS, alert.service_name, alert.namespace
            ),
            "exceptions": build_loki_query(
                LogQueryType.EXCEPTION_LOGS, alert.service_name, alert.namespace
            ),
            "timeouts": build_loki_query(
                LogQueryType.TIMEOUT_LOGS, alert.service_name, alert.namespace
            ),
        }
    except Exception as e:
        log.error("failed to build queries", error=str(e))
        return {
            "logs": LogsData(query_errors=[f"Query build failed: {str(e)}"]),
            "errors": [f"Loki query build failed: {str(e)}"],
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
    all_entries: list[LogEntry] = []
    query_errors = []

    for (name, _), result in zip(queries.items(), results, strict=False):
        if isinstance(result, BaseException):
            query_errors.append(f"{name}: {str(result)}")
            continue

        # At this point, result is the expected type (not an exception)
        entries = _parse_log_entries(result)
        all_entries.extend(entries)

    # Separate by level
    error_logs = [e for e in all_entries if e.level == "error"]
    fatal_logs = [e for e in all_entries if e.level == "fatal"]

    # Deduplicate and sort
    error_logs = _deduplicate_logs(error_logs)[:100]  # Limit to 100
    fatal_logs = _deduplicate_logs(fatal_logs)[:50]  # Limit to 50

    # Detect patterns
    log_patterns = _extract_patterns(all_entries)

    logs_data = LogsData(
        error_logs=error_logs,
        fatal_logs=fatal_logs,
        log_patterns=log_patterns,
        total_error_count=len(error_logs) + len(fatal_logs),
        query_errors=query_errors,
    )

    log.info(
        "logs fetched",
        error_count=len(error_logs),
        fatal_count=len(fatal_logs),
        patterns=len(log_patterns),
        errors=len(query_errors),
    )

    return {"logs": logs_data}


async def _safe_query(
    client: LokiClient,
    name: str,
    query: str,
    start_time: datetime,
    end_time: datetime,
    log,
) -> list[dict]:
    """Execute query with error handling."""
    try:
        return await client.query(query, start_time, end_time, limit=500)
    except LogsQueryError as e:
        log.warning("query failed", query_name=name, error=str(e))
        raise
    except Exception as e:
        log.exception("unexpected error in query", query_name=name)
        raise LogsQueryError(f"Unexpected error: {str(e)}") from e


def _parse_log_entries(raw_data: list[dict]) -> list[LogEntry]:
    """Convert raw Loki data to LogEntry objects."""
    entries = []
    for item in raw_data:
        entries.append(
            LogEntry(
                timestamp=item.get("timestamp", datetime.utcnow()),
                level=item.get("level", "unknown"),
                message=item.get("message", ""),
                labels=item.get("labels", {}),
            )
        )
    return entries


def _deduplicate_logs(entries: list[LogEntry]) -> list[LogEntry]:
    """
    Remove duplicate log entries based on message similarity.

    Keeps the first occurrence of each unique message pattern.
    """
    seen_messages = set()
    unique_entries = []

    for entry in entries:
        # Normalize message for comparison (first 100 chars)
        normalized = _normalize_message(entry.message)
        if normalized not in seen_messages:
            seen_messages.add(normalized)
            unique_entries.append(entry)

    # Sort by timestamp descending
    unique_entries.sort(key=lambda x: x.timestamp, reverse=True)
    return unique_entries


def _normalize_message(message: str) -> str:
    """
    Normalize log message for deduplication.

    Removes variable parts like timestamps, IDs, numbers.
    """
    import re

    # Replace UUIDs
    normalized = re.sub(
        r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
        "<UUID>",
        message,
        flags=re.IGNORECASE,
    )
    # Replace long hex strings
    normalized = re.sub(r"[0-9a-f]{16,}", "<HEX>", normalized, flags=re.IGNORECASE)
    # Replace numbers
    normalized = re.sub(r"\d+", "<N>", normalized)
    # Replace IP addresses
    normalized = re.sub(r"\d+\.\d+\.\d+\.\d+", "<IP>", normalized)
    # Truncate
    return normalized[:100]


def _extract_patterns(entries: list[LogEntry]) -> list[str]:
    """
    Extract common patterns from log entries.

    Identifies frequently occurring error types or messages.
    """
    if not entries:
        return []

    # Count normalized message patterns
    pattern_counter: Counter = Counter()

    for entry in entries:
        # Extract key phrases
        phrases = _extract_key_phrases(entry.message)
        for phrase in phrases:
            pattern_counter[phrase] += 1

    # Return top patterns
    patterns = []
    for pattern, count in pattern_counter.most_common(5):
        if count >= 2:  # At least 2 occurrences
            patterns.append(f"{pattern} (x{count})")

    return patterns


def _extract_key_phrases(message: str) -> list[str]:
    """Extract key error phrases from a log message."""
    import re

    phrases = []

    # Common error patterns
    patterns = [
        r"(?i)(error|exception|failed|failure|timeout|refused|denied|invalid|missing|null|undefined)[\s:]+\w+",
        r"(?i)(cannot|could not|unable to)\s+\w+",
        r"(?i)(status[=:]\s*\d+)",
        r"(?i)(code[=:]\s*\w+)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, message)
        phrases.extend(matches)

    return phrases[:3]  # Limit to 3 phrases per message
