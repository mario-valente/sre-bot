"""LangGraph state definitions for the SRE Copilot agent."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field


def merge_lists(left: list[str], right: list[str]) -> list[str]:
    """Reducer that merges two lists (used for LangGraph state updates)."""
    return left + right


class AlertContext(BaseModel):
    """
    Extracted context from the original alert.

    Contains all relevant labels and metadata from the Alertmanager webhook
    or Slack message that triggered the investigation.
    """

    alert_name: str = Field(
        description="Name of the alert (e.g., 'HighErrorRate', 'PodCrashLooping')"
    )
    severity: Literal["critical", "warning", "info"] = Field(description="Alert severity level")
    service_name: str = Field(description="Name of the affected service")
    cluster: str = Field(description="Kubernetes cluster name")
    namespace: str = Field(description="Kubernetes namespace")
    pod: str | None = Field(default=None, description="Specific pod name if available")
    status_code: int | None = Field(default=None, description="HTTP status code if relevant")
    timestamp: datetime = Field(description="When the alert fired")
    raw_payload: dict[str, Any] = Field(
        default_factory=dict, description="Original alert payload for debugging"
    )
    description: str = Field(default="", description="Alert description/summary")
    runbook_url: str | None = Field(default=None, description="Link to runbook if available")


class MetricPoint(BaseModel):
    """Single metric data point."""

    timestamp: float = Field(description="Unix timestamp")
    value: float = Field(description="Metric value")


class MetricSeries(BaseModel):
    """Time series data with labels."""

    labels: dict[str, str] = Field(default_factory=dict, description="Metric labels")
    values: list[MetricPoint] = Field(default_factory=list, description="Time series values")


class MetricsData(BaseModel):
    """
    Results from Prometheus queries.

    Contains CPU, memory, error rate, and latency metrics
    for the affected service in the alert time window.
    """

    cpu_usage: list[MetricSeries] = Field(default_factory=list, description="CPU usage time series")
    memory_usage: list[MetricSeries] = Field(
        default_factory=list, description="Memory usage time series"
    )
    error_rate_5xx: list[MetricSeries] = Field(
        default_factory=list, description="HTTP 5xx error rate"
    )
    latency_p99: list[MetricSeries] = Field(
        default_factory=list, description="P99 latency time series"
    )
    request_rate: list[MetricSeries] = Field(
        default_factory=list, description="Request rate time series"
    )
    anomalies_detected: list[str] = Field(
        default_factory=list,
        description="Human-readable anomaly descriptions",
    )
    query_errors: list[str] = Field(
        default_factory=list, description="Errors encountered during metric queries"
    )


class LogEntry(BaseModel):
    """Single log entry from Loki."""

    timestamp: datetime = Field(description="Log timestamp")
    level: str = Field(description="Log level (error, fatal, warn, etc.)")
    message: str = Field(description="Log message content")
    labels: dict[str, str] = Field(default_factory=dict, description="Log labels")


class LogsData(BaseModel):
    """
    Results from Loki queries.

    Contains error and fatal logs for the affected service
    during the alert time window.
    """

    error_logs: list[LogEntry] = Field(default_factory=list, description="Logs with level=error")
    fatal_logs: list[LogEntry] = Field(default_factory=list, description="Logs with level=fatal")
    log_patterns: list[str] = Field(
        default_factory=list,
        description="Frequently occurring error patterns",
    )
    total_error_count: int = Field(default=0, description="Total error log count")
    query_errors: list[str] = Field(
        default_factory=list, description="Errors encountered during log queries"
    )


class SpanInfo(BaseModel):
    """Information about a trace span."""

    trace_id: str = Field(description="Trace ID")
    span_id: str = Field(description="Span ID")
    service_name: str = Field(description="Service that generated this span")
    operation_name: str = Field(description="Operation/endpoint name")
    duration_ms: float = Field(description="Span duration in milliseconds")
    status: str = Field(description="Span status (ok, error)")
    error_message: str | None = Field(default=None, description="Error message if any")
    timestamp: datetime = Field(description="Span start time")


class TracesData(BaseModel):
    """
    Results from Tempo queries.

    Contains traces with errors or high latency for the
    affected service during the alert time window.
    """

    failed_traces: list[SpanInfo] = Field(
        default_factory=list, description="Traces with error status"
    )
    slow_traces: list[SpanInfo] = Field(
        default_factory=list, description="Traces exceeding latency threshold"
    )
    bottleneck_services: list[str] = Field(
        default_factory=list,
        description="Services identified as bottlenecks in traces",
    )
    query_errors: list[str] = Field(
        default_factory=list, description="Errors encountered during trace queries"
    )


class CommitInfo(BaseModel):
    """Information about a Git commit."""

    sha: str = Field(description="Commit SHA")
    message: str = Field(description="Commit message")
    author: str = Field(description="Commit author")
    timestamp: datetime = Field(description="Commit timestamp")
    url: str = Field(description="URL to view commit")


class PullRequestInfo(BaseModel):
    """Information about a pull request."""

    number: int = Field(description="PR number")
    title: str = Field(description="PR title")
    author: str = Field(description="PR author")
    merged_at: datetime | None = Field(default=None, description="Merge timestamp")
    url: str = Field(description="URL to view PR")
    files_changed: int = Field(default=0, description="Number of files changed")


class ReleaseInfo(BaseModel):
    """Information about a release."""

    tag: str = Field(description="Release tag")
    name: str = Field(description="Release name")
    published_at: datetime = Field(description="Release timestamp")
    url: str = Field(description="URL to view release")


class GitHubData(BaseModel):
    """
    Recent changes from GitHub repository.

    Used to correlate incidents with recent deployments,
    code changes, or releases.
    """

    recent_commits: list[CommitInfo] = Field(
        default_factory=list, description="Recent commits to main branch"
    )
    recent_prs: list[PullRequestInfo] = Field(
        default_factory=list, description="Recently merged PRs"
    )
    last_release: ReleaseInfo | None = Field(default=None, description="Most recent release")
    has_recent_deploy: bool = Field(
        default=False,
        description="Whether a deploy occurred within the recent deploy window",
    )
    repository: str = Field(default="", description="Repository name")
    query_errors: list[str] = Field(
        default_factory=list, description="Errors encountered during GitHub queries"
    )


class ContainerInfo(BaseModel):
    """Information about a container in a pod."""

    name: str = Field(description="Container name")
    image: str = Field(description="Container image")
    state: str = Field(description="Container state (running, waiting, terminated)")
    state_detail: dict[str, Any] = Field(default_factory=dict, description="State details")
    ready: bool = Field(default=False, description="Whether container is ready")
    restart_count: int = Field(default=0, description="Number of restarts")
    resources: dict[str, Any] = Field(default_factory=dict, description="Resource limits/requests")
    command: list[str] = Field(default_factory=list, description="Container entrypoint command")
    args: list[str] = Field(default_factory=list, description="Container arguments")
    env_vars: dict[str, str] = Field(default_factory=dict, description="Environment variables")
    image_pull_policy: str = Field(default="", description="Image pull policy")
    liveness_probe: dict[str, Any] = Field(
        default_factory=dict, description="Liveness probe configuration"
    )
    readiness_probe: dict[str, Any] = Field(
        default_factory=dict, description="Readiness probe configuration"
    )
    startup_probe: dict[str, Any] = Field(
        default_factory=dict, description="Startup probe configuration"
    )
    security_context: dict[str, Any] = Field(default_factory=dict, description="Security context")
    volume_mounts: list[dict[str, Any]] = Field(default_factory=list, description="Volume mounts")


class PodCondition(BaseModel):
    """Kubernetes pod condition."""

    type: str = Field(description="Condition type (Ready, ContainersReady, etc.)")
    status: str = Field(description="Condition status (True, False, Unknown)")
    reason: str | None = Field(default=None, description="Reason for condition")
    message: str | None = Field(default=None, description="Human-readable message")
    last_transition: str | None = Field(default=None, description="Last transition time")


class PodInfo(BaseModel):
    """Detailed information about a Kubernetes pod."""

    name: str = Field(description="Pod name")
    namespace: str = Field(description="Pod namespace")
    phase: str = Field(description="Pod phase (Running, Pending, Failed, etc.)")
    node: str | None = Field(default=None, description="Node the pod is running on")
    ip: str | None = Field(default=None, description="Pod IP address")
    created_at: str | None = Field(default=None, description="Pod creation timestamp")
    containers: list[ContainerInfo] = Field(
        default_factory=list, description="Container information"
    )
    conditions: list[PodCondition] = Field(default_factory=list, description="Pod conditions")
    restart_count: int = Field(default=0, description="Total restart count across containers")
    labels: dict[str, str] = Field(default_factory=dict, description="Pod labels")


class KubernetesEvent(BaseModel):
    """Kubernetes event information."""

    type: str = Field(description="Event type (Normal, Warning)")
    reason: str = Field(description="Event reason (e.g., Killing, Created, Started)")
    message: str = Field(description="Event message")
    count: int = Field(default=1, description="Number of times event occurred")
    first_timestamp: str | None = Field(default=None, description="First occurrence")
    last_timestamp: str | None = Field(default=None, description="Last occurrence")
    involved_object: dict[str, Any] = Field(default_factory=dict, description="Object involved")
    source: str | None = Field(default=None, description="Event source component")


class DeploymentInfo(BaseModel):
    """Kubernetes deployment information."""

    name: str = Field(description="Deployment name")
    namespace: str = Field(description="Deployment namespace")
    replicas: dict[str, int] = Field(
        default_factory=dict,
        description="Replica counts (desired, ready, available, unavailable)",
    )
    strategy: str | None = Field(default=None, description="Deployment strategy")
    conditions: list[dict[str, Any]] = Field(
        default_factory=list, description="Deployment conditions"
    )
    created_at: str | None = Field(default=None, description="Creation timestamp")
    labels: dict[str, str] = Field(default_factory=dict, description="Labels")
    annotations: dict[str, str] = Field(default_factory=dict, description="Deployment annotations")
    pod_template_labels: dict[str, str] = Field(
        default_factory=dict, description="Pod template labels"
    )
    pod_template_annotations: dict[str, str] = Field(
        default_factory=dict, description="Pod template annotations"
    )
    selector: dict[str, str] = Field(default_factory=dict, description="Label selector")
    min_ready_seconds: int = Field(default=0, description="Min ready seconds")
    revision_history_limit: int | None = Field(default=None, description="Revision history limit")
    volumes: list[dict[str, Any]] = Field(default_factory=list, description="Pod template volumes")


class KubeStateMetricsData(BaseModel):
    """Data from Kube State Metrics via Prometheus."""

    pod_phases: dict[str, str] = Field(
        default_factory=dict,
        description="Pod name to phase mapping",
    )
    container_waiting_reasons: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Containers in waiting state with reasons",
    )
    container_terminated_reasons: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Containers in terminated state with reasons",
    )
    container_restarts: dict[str, int] = Field(
        default_factory=dict,
        description="Container restart counts",
    )
    deployment_replicas: dict[str, Any] = Field(
        default_factory=dict,
        description="Deployment replica status",
    )
    resource_limits: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Container resource limits",
    )
    resource_requests: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Container resource requests",
    )


class KubernetesData(BaseModel):
    """
    Kubernetes cluster data for incident investigation.

    Combines data from both the Kubernetes API and Kube State Metrics.
    """

    # Pod information from K8s API
    pods: list[PodInfo] = Field(default_factory=list, description="Pods for the service")
    pod_logs: dict[str, str] = Field(
        default_factory=dict,
        description="Pod name to log content mapping",
    )

    # Events from K8s API
    events: list[KubernetesEvent] = Field(
        default_factory=list,
        description="Recent Kubernetes events",
    )
    warning_events: list[KubernetesEvent] = Field(
        default_factory=list,
        description="Warning events only (filtered)",
    )

    # Deployment info from K8s API
    deployment: DeploymentInfo | None = Field(default=None, description="Deployment information")

    # Metrics from Kube State Metrics via Prometheus
    kube_state_metrics: KubeStateMetricsData | None = Field(
        default=None, description="Data from kube-state-metrics"
    )

    # Detected issues
    issues_detected: list[str] = Field(
        default_factory=list,
        description="Human-readable issues detected from K8s data",
    )

    # Query errors
    query_errors: list[str] = Field(
        default_factory=list, description="Errors encountered during Kubernetes queries"
    )


class CorrelatedAlert(BaseModel):
    """Summary of a potentially related past alert."""

    alert_name: str = Field(description="Name of the past alert")
    service_name: str = Field(description="Service that triggered the alert")
    severity: str = Field(description="Alert severity")
    timestamp: datetime = Field(description="When the alert was triggered")
    probable_root_cause: str | None = Field(default=None, description="Root cause if analyzed")
    summary: str | None = Field(default=None, description="Brief summary of the incident")
    confidence: str | None = Field(default=None, description="Analysis confidence level")


class CorrelatedAlertsData(BaseModel):
    """
    Data about potentially related alerts from recent history.

    Used to identify patterns, recurring issues, or cascading failures
    where one alert might be caused by another (e.g., DB down -> API errors).
    """

    same_service_alerts: list[CorrelatedAlert] = Field(
        default_factory=list,
        description="Recent alerts for the same service",
    )
    same_namespace_alerts: list[CorrelatedAlert] = Field(
        default_factory=list,
        description="Recent alerts in the same namespace (potential dependency issues)",
    )
    dependency_alerts: list[CorrelatedAlert] = Field(
        default_factory=list,
        description="Alerts from known dependencies (databases, queues, etc.)",
    )
    potential_root_cause_alerts: list[CorrelatedAlert] = Field(
        default_factory=list,
        description="Alerts that may have caused this incident (e.g., infra issues)",
    )
    time_window_minutes: int = Field(
        default=120,
        description="Time window used to search for correlated alerts",
    )
    query_errors: list[str] = Field(
        default_factory=list,
        description="Errors encountered during correlation queries",
    )


class HistoricalSolution(BaseModel):
    """A learned solution from past incidents."""

    id: int = Field(description="Solution ID for tracking")
    alert_name: str = Field(description="Alert name this solution applies to")
    service_name: str = Field(description="Service this solution applies to")
    root_cause: str = Field(description="The identified root cause")
    solution_steps: list[str] = Field(description="Steps to resolve the issue")
    success_rate: float = Field(default=0.0, description="Success rate of this solution")
    times_used: int = Field(default=0, description="Number of times this solution was applied")
    symptoms: list[str] = Field(
        default_factory=list, description="Symptoms that identify this issue"
    )


class HistoricalSolutionsData(BaseModel):
    """
    Historical solutions from past incidents.

    Contains validated solutions that can help resolve similar alerts.
    """

    exact_matches: list[HistoricalSolution] = Field(
        default_factory=list,
        description="Solutions for exact same alert and service",
    )
    similar_solutions: list[HistoricalSolution] = Field(
        default_factory=list,
        description="Solutions for similar alerts or services",
    )
    total_found: int = Field(default=0, description="Total solutions found")
    query_errors: list[str] = Field(
        default_factory=list,
        description="Errors encountered during solution queries",
    )


class IncidentAnalysis(BaseModel):
    """
    Final analysis synthesized by the LLM.

    Consolidates all collected data into a root cause hypothesis
    with supporting evidence and recommended actions.
    """

    summary: str = Field(
        description="Brief TL;DR of the incident (1-2 sentences)",
    )
    probable_root_cause: str = Field(
        description="Primary hypothesis for the root cause",
    )
    contributing_factors: list[str] = Field(
        default_factory=list,
        description="Secondary factors that may have contributed",
    )
    evidence: list[str] = Field(
        default_factory=list,
        description="Data points that support the hypothesis",
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description="Recommended next steps for mitigation",
    )
    confidence: Literal["high", "medium", "low"] = Field(
        description="Confidence level in the analysis",
    )
    needs_human_escalation: bool = Field(
        default=False,
        description="Whether this incident requires immediate human attention",
    )
    escalation_reason: str | None = Field(
        default=None,
        description="Reason for escalation if needed",
    )
    used_historical_solution_id: int | None = Field(
        default=None,
        description="ID of historical solution that was applied (for feedback tracking)",
    )


class AgentState(BaseModel):
    """
    Main state that flows through the LangGraph.

    This state is passed between nodes and accumulates data
    as the investigation progresses.
    """

    # === Input ===
    alert: AlertContext = Field(description="Extracted alert context")

    # === Collected Data (populated by nodes) ===
    metrics: MetricsData | None = Field(default=None, description="Prometheus metrics data")
    logs: LogsData | None = Field(default=None, description="Loki logs data")
    traces: TracesData | None = Field(default=None, description="Tempo traces data")
    github: GitHubData | None = Field(default=None, description="GitHub changes data")
    kubernetes: KubernetesData | None = Field(
        default=None, description="Kubernetes cluster data (pods, events, logs)"
    )
    correlated_alerts: CorrelatedAlertsData | None = Field(
        default=None, description="Related alerts from recent history for correlation analysis"
    )
    historical_solutions: HistoricalSolutionsData | None = Field(
        default=None, description="Learned solutions from similar past incidents"
    )

    # === Output ===
    analysis: IncidentAnalysis | None = Field(
        default=None, description="Final synthesized analysis"
    )

    # === Slack Metadata ===
    slack_thread_ts: str | None = Field(
        default=None, description="Slack thread timestamp for replies"
    )
    slack_channel: str | None = Field(default=None, description="Slack channel ID for posting")
    slack_message_ts: str | None = Field(
        default=None, description="Timestamp of the bot's response message"
    )

    # === Execution Metadata ===
    errors: Annotated[list[str], merge_lists] = Field(
        default_factory=list,
        description="Errors accumulated during execution",
    )
    started_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the investigation started",
    )
    completed_at: datetime | None = Field(
        default=None, description="When the investigation completed"
    )


# Type alias for node return values (partial state updates)
StateUpdate = dict[str, Any]
