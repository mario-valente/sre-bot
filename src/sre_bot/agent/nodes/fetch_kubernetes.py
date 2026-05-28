"""Node for fetching Kubernetes data (API + Kube State Metrics)."""

import asyncio
from typing import Any

import structlog

from sre_bot.agent.state import (
    AgentState,
    ContainerInfo,
    DeploymentInfo,
    KubernetesData,
    KubernetesEvent,
    KubeStateMetricsData,
    PodCondition,
    PodInfo,
    StateUpdate,
)
from sre_bot.clients.kubernetes import KubernetesClient
from sre_bot.clients.prometheus import PrometheusClient
from sre_bot.clients.protocols import KubernetesQueryError, MetricsQueryError
from sre_bot.config import get_settings
from sre_bot.queries.kube_state_metrics import (
    get_deployment_health_queries,
    get_pod_health_queries,
)

logger = structlog.get_logger()


async def fetch_kubernetes(state: AgentState) -> StateUpdate:
    """
    Fetch Kubernetes data for the affected service.

    Collects data from two sources:
    1. Kubernetes API - pod details, logs, events, deployment info
    2. Kube State Metrics via Prometheus - pod status, restarts, resource usage

    Args:
        state: Current agent state with alert context.

    Returns:
        Updated state with Kubernetes data.
    """
    settings = get_settings()
    log = logger.bind(
        node="fetch_kubernetes",
        service=state.alert.service_name,
        namespace=state.alert.namespace,
    )

    if not settings.kubernetes_enabled:
        log.info("kubernetes integration disabled")
        return {"kubernetes": None}

    log.info("fetching Kubernetes data")

    alert = state.alert
    query_errors: list[str] = []
    issues_detected: list[str] = []

    # Initialize data containers
    pods: list[PodInfo] = []
    pod_logs: dict[str, str] = {}
    events: list[KubernetesEvent] = []
    deployment: DeploymentInfo | None = None
    kube_state_metrics: KubeStateMetricsData | None = None

    # === Fetch from Kubernetes API ===
    try:
        k8s_client = KubernetesClient()

        # Fetch pods, events, deployment in parallel
        pods_task = _fetch_pods(k8s_client, alert.service_name, alert.namespace, log)
        events_task = _fetch_events(k8s_client, alert.service_name, alert.namespace, log)
        deployment_task = _fetch_deployment(k8s_client, alert.service_name, alert.namespace, log)

        pods_result, events_result, deployment_result = await asyncio.gather(
            pods_task,
            events_task,
            deployment_task,
            return_exceptions=True,
        )

        # Process pods
        if isinstance(pods_result, BaseException):
            query_errors.append(f"Pods: {str(pods_result)}")
        else:
            pods = pods_result

        # Process events
        if isinstance(events_result, BaseException):
            query_errors.append(f"Events: {str(events_result)}")
        else:
            events = events_result

        # Process deployment
        if isinstance(deployment_result, BaseException):
            query_errors.append(f"Deployment: {str(deployment_result)}")
        else:
            deployment = deployment_result

        # Fetch logs for each pod (limit to first 3 pods to avoid overload)
        if pods:
            log_tasks = []
            for pod in pods[:3]:
                log_tasks.append(
                    _fetch_pod_logs(
                        k8s_client, pod.name, alert.namespace, settings.kubernetes_log_lines, log
                    )
                )

            log_results = await asyncio.gather(*log_tasks, return_exceptions=True)

            for pod, result in zip(pods[:3], log_results, strict=False):
                if isinstance(result, BaseException):
                    query_errors.append(f"Logs for {pod.name}: {str(result)}")
                elif result:
                    pod_logs[pod.name] = result

        # Fetch events specifically for problematic pods (Pending, Failed, CrashLoopBackOff, etc.)
        # This captures critical events like FailedScheduling, FailedMount, FailedAttachVolume
        if pods:
            try:
                problematic_pod_events = await _fetch_events_for_problematic_pods(
                    k8s_client, pods, alert.namespace, log
                )
                # Merge with existing events, avoiding duplicates
                existing_event_keys = {
                    f"{e.reason}:{e.message}:{e.involved_object.get('name', '')}" for e in events
                }
                for event in problematic_pod_events:
                    event_key = (
                        f"{event.reason}:{event.message}:{event.involved_object.get('name', '')}"
                    )
                    if event_key not in existing_event_keys:
                        events.append(event)
                        existing_event_keys.add(event_key)
            except Exception as e:
                log.warning("failed to fetch events for problematic pods", error=str(e))
                query_errors.append(f"Problematic pod events: {str(e)}")

    except Exception as e:
        log.error("failed to initialize Kubernetes client", error=str(e))
        query_errors.append(f"Kubernetes client: {str(e)}")

    # === Fetch from Kube State Metrics via Prometheus ===
    try:
        kube_state_metrics = await _fetch_kube_state_metrics(
            alert.service_name, alert.namespace, log
        )
    except Exception as e:
        log.error("failed to fetch kube state metrics", error=str(e))
        query_errors.append(f"Kube State Metrics: {str(e)}")

    # === Detect Issues ===
    issues_detected = _detect_kubernetes_issues(pods, events, deployment, kube_state_metrics)

    # Filter warning events
    warning_events = [e for e in events if e.type == "Warning"]

    kubernetes_data = KubernetesData(
        pods=pods,
        pod_logs=pod_logs,
        events=events,
        warning_events=warning_events,
        deployment=deployment,
        kube_state_metrics=kube_state_metrics,
        issues_detected=issues_detected,
        query_errors=query_errors,
    )

    log.info(
        "kubernetes data fetched",
        pods=len(pods),
        events=len(events),
        warning_events=len(warning_events),
        has_deployment=deployment is not None,
        issues=len(issues_detected),
        errors=len(query_errors),
    )

    return {"kubernetes": kubernetes_data}


async def _fetch_pods(
    client: KubernetesClient,
    service_name: str,
    namespace: str,
    log,
) -> list[PodInfo]:
    """Fetch pods for the service."""
    try:
        raw_pods = await client.get_pods_for_service(service_name, namespace)
        pods = []
        for raw_pod in raw_pods:
            containers = [
                ContainerInfo(
                    name=c["name"],
                    image=c["image"],
                    state=c["state"],
                    state_detail=c.get("state_detail", {}),
                    ready=c.get("ready", False),
                    restart_count=c.get("restart_count", 0),
                    resources=c.get("resources", {}),
                    command=c.get("command", []),
                    args=c.get("args", []),
                    env_vars=c.get("env_vars", {}),
                    image_pull_policy=c.get("image_pull_policy", ""),
                    liveness_probe=c.get("liveness_probe", {}),
                    readiness_probe=c.get("readiness_probe", {}),
                    startup_probe=c.get("startup_probe", {}),
                    security_context=c.get("security_context", {}),
                    volume_mounts=c.get("volume_mounts", []),
                )
                for c in raw_pod.get("containers", [])
            ]
            conditions = [
                PodCondition(
                    type=c["type"],
                    status=c["status"],
                    reason=c.get("reason"),
                    message=c.get("message"),
                    last_transition=c.get("last_transition"),
                )
                for c in raw_pod.get("conditions", [])
            ]
            pods.append(
                PodInfo(
                    name=raw_pod["name"],
                    namespace=raw_pod["namespace"],
                    phase=raw_pod["phase"],
                    node=raw_pod.get("node"),
                    ip=raw_pod.get("ip"),
                    created_at=raw_pod.get("created_at"),
                    containers=containers,
                    conditions=conditions,
                    restart_count=raw_pod.get("restart_count", 0),
                    labels=raw_pod.get("labels", {}),
                )
            )
        return pods
    except KubernetesQueryError:
        raise
    except Exception as e:
        log.warning("failed to fetch pods", error=str(e))
        raise KubernetesQueryError(f"Failed to fetch pods: {e}") from e


async def _fetch_events(
    client: KubernetesClient,
    service_name: str,
    namespace: str,
    log,
) -> list[KubernetesEvent]:
    """Fetch Kubernetes events for the namespace."""
    try:
        raw_events = await client.get_events(namespace, limit=50)
        # Filter events related to our service
        events = []
        for raw_event in raw_events:
            involved = raw_event.get("involved_object", {})
            obj_name = involved.get("name", "")
            # Include if object name starts with service name
            if obj_name.startswith(service_name):
                events.append(
                    KubernetesEvent(
                        type=raw_event["type"],
                        reason=raw_event["reason"],
                        message=raw_event["message"],
                        count=raw_event.get("count", 1),
                        first_timestamp=raw_event.get("first_timestamp"),
                        last_timestamp=raw_event.get("last_timestamp"),
                        involved_object=involved,
                        source=raw_event.get("source"),
                    )
                )
        return events
    except KubernetesQueryError:
        raise
    except Exception as e:
        log.warning("failed to fetch events", error=str(e))
        raise KubernetesQueryError(f"Failed to fetch events: {e}") from e


def _is_pod_problematic(pod: PodInfo) -> bool:
    """Check if a pod is in a problematic state that warrants event investigation."""
    # Check pod phase
    if pod.phase in ("Pending", "Failed", "Unknown"):
        return True

    # Check container states
    for container in pod.containers:
        if container.state == "waiting":
            reason = container.state_detail.get("reason", "")
            if reason in (
                "CrashLoopBackOff",
                "ImagePullBackOff",
                "ErrImagePull",
                "CreateContainerConfigError",
                "InvalidImageName",
                "ContainerCreating",
            ):
                return True

        if container.state == "terminated":
            reason = container.state_detail.get("reason", "")
            if reason in ("OOMKilled", "Error", "ContainerCannotRun"):
                return True

        # High restart count indicates instability
        if container.restart_count > 3:
            return True

    # Check pod conditions for issues
    for condition in pod.conditions:
        if condition.type == "Ready" and condition.status == "False":
            return True
        if condition.type == "PodScheduled" and condition.status == "False":
            return True
        if condition.type == "ContainersReady" and condition.status == "False":
            return True

    return False


async def _fetch_events_for_resource(
    client: KubernetesClient,
    resource_name: str,
    namespace: str,
    log,
) -> list[KubernetesEvent]:
    """Fetch Kubernetes events for a specific resource by name."""
    try:
        raw_events = await client.get_events(
            namespace,
            involved_object_name=resource_name,
            limit=20,
        )
        events = []
        for raw_event in raw_events:
            involved = raw_event.get("involved_object", {})
            events.append(
                KubernetesEvent(
                    type=raw_event["type"],
                    reason=raw_event["reason"],
                    message=raw_event["message"],
                    count=raw_event.get("count", 1),
                    first_timestamp=raw_event.get("first_timestamp"),
                    last_timestamp=raw_event.get("last_timestamp"),
                    involved_object=involved,
                    source=raw_event.get("source"),
                )
            )
        return events
    except KubernetesQueryError:
        raise
    except Exception as e:
        log.warning("failed to fetch events for resource", resource=resource_name, error=str(e))
        raise KubernetesQueryError(f"Failed to fetch events for {resource_name}: {e}") from e


async def _fetch_events_for_problematic_pods(
    client: KubernetesClient,
    pods: list[PodInfo],
    namespace: str,
    log,
) -> list[KubernetesEvent]:
    """
    Fetch events specifically for pods that are in problematic states.

    This is crucial for diagnosing issues like:
    - Pending pods: FailedScheduling, FailedAttachVolume, FailedMount
    - Failed pods: Killing, BackOff, Unhealthy
    - CrashLoopBackOff: Previous container logs and restart reasons
    """
    problematic_pods = [pod for pod in pods if _is_pod_problematic(pod)]

    if not problematic_pods:
        log.debug("no problematic pods found, skipping targeted event fetch")
        return []

    log.info(
        "fetching events for problematic pods",
        count=len(problematic_pods),
        pods=[p.name for p in problematic_pods],
    )

    # Fetch events for each problematic pod in parallel
    tasks = []
    for pod in problematic_pods[:5]:  # Limit to 5 pods to avoid overload
        tasks.append(_fetch_events_for_resource(client, pod.name, namespace, log))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_events: list[KubernetesEvent] = []
    seen_events: set[str] = set()  # Deduplicate by message + reason + object

    for pod, result in zip(problematic_pods[:5], results, strict=False):
        if isinstance(result, BaseException):
            log.warning("failed to fetch events for pod", pod=pod.name, error=str(result))
            continue

        events_list: list[KubernetesEvent] = result
        for event in events_list:
            # Create unique key for deduplication
            event_key = f"{event.reason}:{event.message}:{event.involved_object.get('name', '')}"
            if event_key not in seen_events:
                seen_events.add(event_key)
                all_events.append(event)

    return all_events


async def _fetch_deployment(
    client: KubernetesClient,
    service_name: str,
    namespace: str,
    log,
) -> DeploymentInfo | None:
    """Fetch deployment information."""
    try:
        raw_deployment = await client.get_deployment(service_name, namespace)
        if not raw_deployment:
            return None
        return DeploymentInfo(
            name=raw_deployment["name"],
            namespace=raw_deployment["namespace"],
            replicas=raw_deployment.get("replicas", {}),
            strategy=raw_deployment.get("strategy"),
            conditions=raw_deployment.get("conditions", []),
            created_at=raw_deployment.get("created_at"),
            labels=raw_deployment.get("labels", {}),
            annotations=raw_deployment.get("annotations", {}),
            pod_template_labels=raw_deployment.get("pod_template_labels", {}),
            pod_template_annotations=raw_deployment.get("pod_template_annotations", {}),
            selector=raw_deployment.get("selector", {}),
            min_ready_seconds=raw_deployment.get("min_ready_seconds", 0),
            revision_history_limit=raw_deployment.get("revision_history_limit"),
            volumes=raw_deployment.get("volumes", []),
        )
    except KubernetesQueryError:
        raise
    except Exception as e:
        log.warning("failed to fetch deployment", error=str(e))
        raise KubernetesQueryError(f"Failed to fetch deployment: {e}") from e


async def _fetch_pod_logs(
    client: KubernetesClient,
    pod_name: str,
    namespace: str,
    tail_lines: int,
    log,
) -> str:
    """Fetch logs for a single pod."""
    try:
        logs = await client.get_pod_logs(pod_name, namespace, tail_lines=tail_lines)
        return logs
    except KubernetesQueryError:
        raise
    except Exception as e:
        log.warning("failed to fetch logs", pod=pod_name, error=str(e))
        raise KubernetesQueryError(f"Failed to fetch logs: {e}") from e


async def _fetch_kube_state_metrics(
    service_name: str,
    namespace: str,
    log,
) -> KubeStateMetricsData:
    """Fetch Kube State Metrics via Prometheus."""
    client = PrometheusClient()

    # Build queries
    pod_queries = get_pod_health_queries(service_name, namespace)
    deployment_queries = get_deployment_health_queries(service_name, namespace)

    all_queries = {**pod_queries, **deployment_queries}

    # Execute queries in parallel
    results: dict[str, list[dict[str, Any]]] = {}
    tasks = []
    query_names = []

    for name, query in all_queries.items():
        query_names.append(name)
        tasks.append(_safe_prometheus_query(client, query, log))

    query_results = await asyncio.gather(*tasks, return_exceptions=True)

    for name, result in zip(query_names, query_results, strict=False):
        if isinstance(result, BaseException):
            log.warning("kube state query failed", query=name, error=str(result))
            results[name] = []
        else:
            results[name] = result

    # Parse results into KubeStateMetricsData
    return _parse_kube_state_results(results)


async def _safe_prometheus_query(
    client: PrometheusClient,
    query: str,
    log,  # noqa: ARG001
) -> list[dict[str, Any]]:
    """Execute Prometheus query with error handling."""
    try:
        return await client.query(query)
    except MetricsQueryError:
        raise
    except Exception as e:
        raise MetricsQueryError(f"Query failed: {e}") from e


def _parse_kube_state_results(results: dict[str, list]) -> KubeStateMetricsData:
    """Parse raw Prometheus results into KubeStateMetricsData."""
    data = KubeStateMetricsData()

    # Pod phases
    for item in results.get("pod_phase", []):
        labels = item.get("labels", {})
        pod_name = labels.get("pod", "")
        phase = labels.get("phase", "")
        if pod_name and phase:
            data.pod_phases[pod_name] = phase

    # Container waiting reasons
    for item in results.get("container_waiting", []):
        labels = item.get("labels", {})
        data.container_waiting_reasons.append(
            {
                "pod": labels.get("pod", ""),
                "container": labels.get("container", ""),
                "reason": labels.get("reason", ""),
            }
        )

    # Container terminated reasons
    for item in results.get("container_terminated", []):
        labels = item.get("labels", {})
        data.container_terminated_reasons.append(
            {
                "pod": labels.get("pod", ""),
                "container": labels.get("container", ""),
                "reason": labels.get("reason", ""),
            }
        )

    # Container restarts
    for item in results.get("container_restarts", []):
        labels = item.get("labels", {})
        pod_name = labels.get("pod", "")
        values = item.get("values", [])
        if pod_name and values:
            # Get latest value
            latest_value = values[-1].get("value", 0) if values else 0
            data.container_restarts[pod_name] = int(latest_value)

    # Deployment replicas
    desired = 0
    available = 0
    unavailable = 0

    for item in results.get("replicas_desired", []):
        values = item.get("values", [])
        if values:
            desired = int(values[-1].get("value", 0))

    for item in results.get("replicas_available", []):
        values = item.get("values", [])
        if values:
            available = int(values[-1].get("value", 0))

    for item in results.get("replicas_unavailable", []):
        values = item.get("values", [])
        if values:
            unavailable = int(values[-1].get("value", 0))

    data.deployment_replicas = {
        "desired": desired,
        "available": available,
        "unavailable": unavailable,
    }

    return data


def _detect_kubernetes_issues(
    pods: list[PodInfo],
    events: list[KubernetesEvent],
    deployment: DeploymentInfo | None,
    kube_state_metrics: KubeStateMetricsData | None,
) -> list[str]:
    """Detect issues from Kubernetes data."""
    issues = []

    # Check pod phases
    for pod in pods:
        if pod.phase == "Failed":
            issues.append(f"Pod {pod.name} is in Failed state")
        elif pod.phase == "Pending":
            issues.append(f"Pod {pod.name} is stuck in Pending state")

        # Check container states and probes
        for container in pod.containers:
            if container.state == "waiting":
                reason = container.state_detail.get("reason", "unknown")
                if reason in ("CrashLoopBackOff", "ImagePullBackOff", "ErrImagePull"):
                    issues.append(f"Container {container.name} in pod {pod.name}: {reason}")

            if container.restart_count > 3:
                issues.append(
                    f"Container {container.name} in pod {pod.name} has "
                    f"{container.restart_count} restarts"
                )

            # Check for problematic probe configurations (e.g., exec probes that always fail)
            for probe_name in ["readiness_probe", "liveness_probe", "startup_probe"]:
                probe = getattr(container, probe_name, {})
                if probe and probe.get("type") == "exec":
                    cmd = probe.get("exec", {}).get("command", [])
                    if cmd and (cmd == ["false"] or "false" in " ".join(cmd)):
                        issues.append(
                            f"Container {container.name} in {pod.name} has {probe_name} "
                            f"with failing command: {' '.join(cmd)} - probe will always fail!"
                        )

            # Check for missing environment variables or suspicious configurations
            if (
                not container.env_vars
                and container.command
                and "java" in str(container.command).lower()
            ):
                issues.append(
                    f"Java application {container.name} in {pod.name} has no environment "
                    f"variables configured"
                )

    # Check warning events - expanded to cover more critical event types
    # These events are particularly useful for diagnosing scheduling and volume issues
    critical_event_reasons = {
        # Scheduling issues
        "FailedScheduling": "Pod cannot be scheduled",
        "NodeNotReady": "Node is not ready",
        "InsufficientMemory": "Insufficient memory on nodes",
        "InsufficientCPU": "Insufficient CPU on nodes",
        "Unschedulable": "Pod is unschedulable",
        # Volume/PVC issues
        "FailedAttachVolume": "Volume attach failed",
        "FailedMount": "Volume mount failed",
        "VolumeBindingFailed": "PVC binding failed",
        "ProvisioningFailed": "Volume provisioning failed",
        # Container issues
        "BackOff": "Container back-off",
        "Killing": "Container being killed",
        "Unhealthy": "Container health check failed",
        "FailedPreStopHook": "PreStop hook failed",
        "FailedPostStartHook": "PostStart hook failed",
        # Image issues
        "Failed": "Container operation failed",
        "ErrImagePull": "Image pull failed",
        "ImagePullBackOff": "Image pull back-off",
        "InvalidImageName": "Invalid image name",
        # Network issues
        "NetworkNotReady": "Network not ready",
        "FailedCreatePodSandBox": "Pod sandbox creation failed",
    }

    for event in events:
        if event.reason in critical_event_reasons and event.type == "Warning":
            issue_prefix = critical_event_reasons[event.reason]
            obj_name = event.involved_object.get("name", "unknown")
            obj_kind = event.involved_object.get("kind", "resource")
            # Truncate message but keep useful info
            message = event.message[:150] if event.message else "No details"
            issues.append(f"{issue_prefix} ({obj_kind}/{obj_name}): {message}")

    # Check deployment
    if deployment:
        replicas = deployment.replicas
        if replicas.get("unavailable", 0) > 0:
            issues.append(f"Deployment has {replicas['unavailable']} unavailable replicas")
        if replicas.get("ready", 0) < replicas.get("desired", 0):
            issues.append(
                f"Deployment has only {replicas.get('ready', 0)}/{replicas.get('desired', 0)} "
                "ready replicas"
            )

    # Check kube state metrics
    if kube_state_metrics:
        # CrashLoopBackOff from waiting reasons
        for waiting in kube_state_metrics.container_waiting_reasons:
            reason = waiting.get("reason", "")
            if reason == "CrashLoopBackOff":
                pod = waiting.get("pod", "unknown")
                issues.append(f"CrashLoopBackOff detected in pod {pod}")

        # OOMKilled from terminated reasons
        for terminated in kube_state_metrics.container_terminated_reasons:
            reason = terminated.get("reason", "")
            if reason == "OOMKilled":
                pod = terminated.get("pod", "unknown")
                issues.append(f"OOMKilled detected in pod {pod}")

        # High restart counts
        for pod_name, restarts in kube_state_metrics.container_restarts.items():
            if restarts > 5:
                issues.append(f"High restart count ({restarts}) for pod {pod_name}")

    return issues
