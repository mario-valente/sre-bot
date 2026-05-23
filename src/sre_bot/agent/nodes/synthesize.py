"""Node for synthesizing analysis using LLM."""

from datetime import datetime

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from sre_bot.agent.state import AgentState, IncidentAnalysis, StateUpdate
from sre_bot.llm import get_llm

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are an expert SRE (Site Reliability Engineer) analyzing an incident.
Your task is to synthesize data from multiple sources and provide a root cause analysis.

Be concise, technical, and actionable. Focus on:
1. What happened (summary)
2. Why it happened (root cause hypothesis)
3. What evidence supports this
4. What to do next (mitigation steps)

Guidelines:
- Be specific with service names, error messages, and metrics
- Prioritize the most likely root cause based on evidence
- Suggest immediate actions, not long-term improvements
- If data is insufficient, say so and suggest what data to gather
- Set confidence based on evidence strength (high/medium/low)
- Flag for escalation if: data loss risk, security concern, or widespread impact

### Alert Correlation Analysis Instructions:
When analyzing correlated alerts, consider:
1. **Cascading Failures**: An infrastructure alert (database, cache, network) happening BEFORE
   the current alert may be the root cause. Example: "DatabaseConnectionTimeout" → "HighErrorRate"
2. **Same Service Patterns**: Multiple alerts from the same service suggest a recurring or worsening issue
3. **Same Namespace Issues**: Other services in the same namespace failing may indicate:
   - Shared dependency issues (database, config, secrets)
   - Network/connectivity problems
   - Resource contention
4. **Timeline Analysis**: Alerts are ordered by timestamp - earlier infrastructure alerts
   are more likely to be root causes of later application alerts
5. **Severity Escalation**: If a warning became critical, or multiple services are affected,
   this indicates a spreading issue that needs immediate attention

### Kubernetes-Specific Analysis Instructions:
When analyzing Kubernetes data, pay close attention to:

1. **Readiness/Liveness Probes:**
   - Are probes failing? (readiness_probe or liveness_probe with type exec/http/tcp)
   - Are failure thresholds set too aggressively?
   - Are initial delays sufficient for startup?
   - Check for probe commands returning false, http 404/500, or connection timeouts
   - If a probe command starts with "false" or always fails, this will cause CrashLoopBackOff

2. **Container Configuration:**
   - Are the command and args correct for the application?
   - Are critical environment variables missing or misconfigured?
   - Do resource limits make sense for the workload?
   - Is the security context appropriate? (privileged, runAsNonRoot, uid/gid)

3. **Pod State Indicators:**
   - CrashLoopBackOff = Container repeatedly failing to start
   - Pending = Pod can't be scheduled (usually resource or node issues)
   - ImagePullBackOff = Image pull failure
   - Look for pod conditions that are not True status

4. **Common Misconfigurations:**
   - Incorrect probe configuration (especially failing/always-false exec probes)
   - Missing or wrong environment variables
   - Incorrect container command or arguments
   - Resource requests too high for available nodes
   - Image pull policy issues
   - Security context preventing container startup

Output format: JSON matching the IncidentAnalysis schema."""


def _build_analysis_prompt(state: AgentState) -> str:
    """Build the analysis prompt with all collected data."""
    alert = state.alert
    sections = []

    # Alert context
    sections.append(f"""## Alert Context
- **Alert Name:** {alert.alert_name}
- **Severity:** {alert.severity}
- **Service:** {alert.service_name}
- **Namespace:** {alert.namespace}
- **Cluster:** {alert.cluster}
- **Timestamp:** {alert.timestamp.isoformat()}
- **Description:** {alert.description or "N/A"}
""")

    # Metrics
    if state.metrics:
        metrics = state.metrics
        metrics_section = "## Metrics (Prometheus)\n"

        if metrics.anomalies_detected:
            metrics_section += "**Anomalies Detected:**\n"
            for anomaly in metrics.anomalies_detected:
                metrics_section += f"- {anomaly}\n"

        if metrics.error_rate_5xx:
            metrics_section += "\n**Error Rate (5xx):** Data available\n"
        if metrics.latency_p99:
            metrics_section += "**P99 Latency:** Data available\n"
        if metrics.cpu_usage:
            metrics_section += "**CPU Usage:** Data available\n"
        if metrics.memory_usage:
            metrics_section += "**Memory Usage:** Data available\n"

        if metrics.query_errors:
            metrics_section += "\n**Query Errors:**\n"
            for err in metrics.query_errors:
                metrics_section += f"- {err}\n"

        sections.append(metrics_section)
    else:
        sections.append("## Metrics\nNo metrics data available.\n")

    # Logs
    if state.logs:
        logs = state.logs
        logs_section = f"## Logs (Loki)\n**Total Error/Fatal Logs:** {logs.total_error_count}\n"

        if logs.log_patterns:
            logs_section += "\n**Common Patterns:**\n"
            for pattern in logs.log_patterns[:5]:
                logs_section += f"- {pattern}\n"

        if logs.fatal_logs:
            logs_section += f"\n**Sample Fatal Logs ({len(logs.fatal_logs)}):**\n"
            for log_entry in logs.fatal_logs[:3]:
                logs_section += (
                    f"- [{log_entry.timestamp.strftime('%H:%M:%S')}] {log_entry.message[:200]}\n"
                )

        if logs.error_logs:
            logs_section += f"\n**Sample Error Logs ({len(logs.error_logs)}):**\n"
            for log_entry in logs.error_logs[:5]:
                logs_section += (
                    f"- [{log_entry.timestamp.strftime('%H:%M:%S')}] {log_entry.message[:200]}\n"
                )

        sections.append(logs_section)
    else:
        sections.append("## Logs\nNo log data available.\n")

    # Traces
    if state.traces:
        traces = state.traces
        traces_section = "## Traces (Tempo)\n"

        if traces.bottleneck_services:
            traces_section += "**Bottleneck Services:**\n"
            for svc in traces.bottleneck_services:
                traces_section += f"- {svc}\n"

        if traces.failed_traces:
            traces_section += f"\n**Failed Traces ({len(traces.failed_traces)}):**\n"
            for trace in traces.failed_traces[:3]:
                traces_section += (
                    f"- {trace.operation_name}: {trace.duration_ms:.0f}ms ({trace.service_name})\n"
                )

        if traces.slow_traces:
            traces_section += f"\n**Slow Traces ({len(traces.slow_traces)}):**\n"
            for trace in traces.slow_traces[:3]:
                traces_section += (
                    f"- {trace.operation_name}: {trace.duration_ms:.0f}ms ({trace.service_name})\n"
                )

        sections.append(traces_section)
    else:
        sections.append("## Traces\nNo trace data available.\n")

    # Kubernetes
    if state.kubernetes:
        k8s = state.kubernetes
        k8s_section = "## Kubernetes Analysis\n"

        # Issues detected upfront
        if k8s.issues_detected:
            k8s_section += "**🚨 Issues Detected:**\n"
            for issue in k8s.issues_detected:
                k8s_section += f"- {issue}\n"

        # Pod details
        if k8s.pods:
            k8s_section += f"\n**Pods ({len(k8s.pods)}):**\n"
            for pod in k8s.pods[:5]:
                k8s_section += f"\n  **Pod: {pod.name}**\n"
                k8s_section += f"    - Phase: {pod.phase}\n"
                k8s_section += f"    - Node: {pod.node or 'N/A'}\n"
                k8s_section += f"    - Restart Count: {pod.restart_count}\n"

                # Pod conditions
                for cond in pod.conditions:
                    if cond.status != "True":
                        k8s_section += (
                            f"    - Condition {cond.type}: {cond.status} ({cond.reason})\n"
                        )

                # Container details with new fields
                for container in pod.containers:
                    k8s_section += f"\n    **Container: {container.name}**\n"
                    k8s_section += f"      - Image: {container.image}\n"
                    k8s_section += f"      - State: {container.state}\n"
                    if container.state_detail:
                        for key, value in container.state_detail.items():
                            k8s_section += f"        - {key}: {value}\n"

                    # Command and args (key for misconfiguration detection)
                    if container.command:
                        k8s_section += f"      - Command: {' '.join(container.command)}\n"
                    if container.args:
                        k8s_section += f"      - Args: {' '.join(container.args)}\n"

                    # Environment variables
                    if container.env_vars:
                        k8s_section += (
                            f"      - Environment Variables: {len(container.env_vars)} set\n"
                        )
                        for key, value in list(container.env_vars.items())[:3]:
                            k8s_section += f"        - {key}={value if len(str(value)) < 50 else str(value)[:47] + '...'}\n"
                        if len(container.env_vars) > 3:
                            k8s_section += f"        - ... and {len(container.env_vars) - 3} more\n"

                    # Resource limits/requests
                    if container.resources:
                        limits = container.resources.get("limits", {})
                        requests = container.resources.get("requests", {})
                        if limits:
                            k8s_section += f"      - Resource Limits: CPU={limits.get('cpu')}, Memory={limits.get('memory')}\n"
                        if requests:
                            k8s_section += f"      - Resource Requests: CPU={requests.get('cpu')}, Memory={requests.get('memory')}\n"

                    # Security context
                    if container.security_context:
                        k8s_section += "      - Security Context: "
                        sc_items = []
                        if container.security_context.get("privileged"):
                            sc_items.append("PRIVILEGED")
                        if container.security_context.get("run_as_non_root") is False:
                            sc_items.append("RUNNING_AS_ROOT")
                        if container.security_context.get("read_only_root_filesystem"):
                            sc_items.append("READ_ONLY_FS")
                        if container.security_context.get("run_as_user"):
                            sc_items.append(f"UID={container.security_context['run_as_user']}")
                        k8s_section += ", ".join(sc_items) if sc_items else "default\n"
                        k8s_section += "\n"

                    # Probes (important for CrashLoopBackOff issues)
                    if container.readiness_probe:
                        probe = container.readiness_probe
                        k8s_section += f"      - Readiness Probe: type={probe.get('type')}, "
                        k8s_section += f"failureThreshold={probe.get('failure_threshold')}, "
                        k8s_section += f"periodSeconds={probe.get('period_seconds')}\n"
                        if probe.get("type") == "exec" and probe.get("exec", {}).get("command"):
                            k8s_section += (
                                f"        - Command: {' '.join(probe['exec']['command'])}\n"
                            )

                    if container.liveness_probe:
                        probe = container.liveness_probe
                        k8s_section += f"      - Liveness Probe: type={probe.get('type')}, "
                        k8s_section += f"initialDelaySeconds={probe.get('initial_delay_seconds')}\n"

                    if container.startup_probe:
                        probe = container.startup_probe
                        k8s_section += f"      - Startup Probe: type={probe.get('type')}\n"

                    # Volume mounts
                    if container.volume_mounts:
                        k8s_section += f"      - Volume Mounts: {len(container.volume_mounts)}\n"
                        for vm in container.volume_mounts[:3]:
                            k8s_section += f"        - {vm.get('name')}: {vm.get('mount_path')} {'(read-only)' if vm.get('read_only') else ''}\n"

        # Deployment info
        if k8s.deployment:
            dep = k8s.deployment
            k8s_section += f"\n**Deployment: {dep.name}**\n"
            k8s_section += f"  - Desired Replicas: {dep.replicas.get('desired', 0)}\n"
            k8s_section += f"  - Ready Replicas: {dep.replicas.get('ready', 0)}\n"
            k8s_section += f"  - Available Replicas: {dep.replicas.get('available', 0)}\n"
            k8s_section += f"  - Unavailable Replicas: {dep.replicas.get('unavailable', 0)}\n"
            k8s_section += f"  - Strategy: {dep.strategy}\n"
            k8s_section += f"  - Min Ready Seconds: {dep.min_ready_seconds}\n"

            if dep.volumes:
                k8s_section += f"  - Volumes Configured: {len(dep.volumes)}\n"
                for vol in dep.volumes[:3]:
                    vol_type = vol.get("type", "unknown")
                    k8s_section += f"    - {vol.get('name')}: type={vol_type}\n"

            if dep.annotations:
                k8s_section += "  - Key Annotations: "
                k8s_section += (
                    ", ".join([f"{k}={v[:30]}" for k, v in list(dep.annotations.items())[:2]])
                    + "\n"
                )

        # Events
        if k8s.warning_events:
            k8s_section += f"\n**Warning Events ({len(k8s.warning_events)}):**\n"
            for event in k8s.warning_events[:5]:
                k8s_section += f"  - [{event.reason}] {event.message[:100]}\n"

        # Pod logs
        if k8s.pod_logs:
            k8s_section += f"\n**Pod Logs Available: {len(k8s.pod_logs)} pod(s)**\n"
            for pod_name, logs in list(k8s.pod_logs.items())[:2]:
                log_lines = logs.split("\n")[:5]
                k8s_section += f"  **{pod_name}:**\n"
                for line in log_lines:
                    if line.strip():
                        k8s_section += f"    {line[:100]}\n"

        # Kube State Metrics
        if k8s.kube_state_metrics:
            ksm = k8s.kube_state_metrics
            if ksm.container_waiting_reasons:
                k8s_section += "\n**Containers Waiting:**\n"
                for waiting in ksm.container_waiting_reasons[:3]:
                    k8s_section += f"  - {waiting.get('pod')}/{waiting.get('container')}: {waiting.get('reason')}\n"

            if ksm.container_terminated_reasons:
                k8s_section += "\n**Containers Terminated:**\n"
                for term in ksm.container_terminated_reasons[:3]:
                    k8s_section += (
                        f"  - {term.get('pod')}/{term.get('container')}: {term.get('reason')}\n"
                    )

            if ksm.container_restarts:
                high_restarts = {k: v for k, v in ksm.container_restarts.items() if v > 3}
                if high_restarts:
                    k8s_section += "\n**High Container Restarts:**\n"
                    for pod, count in high_restarts.items():
                        k8s_section += f"  - {pod}: {count} restarts\n"

        sections.append(k8s_section)
    else:
        sections.append("## Kubernetes\nNo Kubernetes data available.\n")

    # GitHub
    if state.github:
        github = state.github
        github_section = f"## Recent Changes (GitHub)\n**Repository:** {github.repository}\n"
        github_section += (
            f"**Recent Deploy Detected:** {'Yes' if github.has_recent_deploy else 'No'}\n"
        )

        if github.recent_commits:
            github_section += f"\n**Recent Commits ({len(github.recent_commits)}):**\n"
            for commit in github.recent_commits[:3]:
                github_section += f"- [{commit.sha}] {commit.message[:60]} ({commit.author})\n"

        if github.recent_prs:
            github_section += f"\n**Recent PRs ({len(github.recent_prs)}):**\n"
            for pr in github.recent_prs[:3]:
                github_section += f"- #{pr.number}: {pr.title[:50]} ({pr.author})\n"

        if github.last_release:
            release = github.last_release
            github_section += f"\n**Latest Release:** {release.tag} ({release.published_at.strftime('%Y-%m-%d')})\n"

        sections.append(github_section)
    else:
        sections.append("## Recent Changes\nNo GitHub data available.\n")

    # Correlated Alerts
    if state.correlated_alerts:
        corr = state.correlated_alerts
        corr_section = f"## Correlated Alerts (Last {corr.time_window_minutes} minutes)\n"
        corr_section += (
            "**IMPORTANT:** Review these alerts to identify potential cascading failures.\n\n"
        )

        # Potential root causes (most important)
        if corr.potential_root_cause_alerts:
            corr_section += "### Potential Root Cause Alerts\n"
            corr_section += "These alerts may have CAUSED the current incident:\n"
            for alert in corr.potential_root_cause_alerts:
                time_diff = (state.alert.timestamp - alert.timestamp).total_seconds() / 60
                corr_section += f"\n**{alert.alert_name}** ({alert.service_name})\n"
                corr_section += f"  - Severity: {alert.severity}\n"
                corr_section += f"  - Occurred: {time_diff:.0f} minutes BEFORE current alert\n"
                if alert.probable_root_cause:
                    corr_section += f"  - Root Cause Analysis: {alert.probable_root_cause[:150]}\n"
                if alert.summary:
                    corr_section += f"  - Summary: {alert.summary[:100]}\n"

        # Same service alerts (pattern detection)
        if corr.same_service_alerts:
            corr_section += f"\n### Same Service History ({len(corr.same_service_alerts)} alerts)\n"
            corr_section += "Recent alerts for the same service (may indicate recurring issue):\n"
            for alert in corr.same_service_alerts[:3]:
                time_diff = (state.alert.timestamp - alert.timestamp).total_seconds() / 60
                corr_section += (
                    f"  - {alert.alert_name} ({alert.severity}) - {time_diff:.0f}min ago"
                )
                if alert.probable_root_cause:
                    corr_section += f" - Cause: {alert.probable_root_cause[:80]}"
                corr_section += "\n"

        # Same namespace alerts (dependency issues)
        if corr.same_namespace_alerts:
            corr_section += (
                f"\n### Same Namespace Alerts ({len(corr.same_namespace_alerts)} alerts)\n"
            )
            corr_section += "Other services in the same namespace that may be related:\n"
            for alert in corr.same_namespace_alerts[:5]:
                time_diff = (state.alert.timestamp - alert.timestamp).total_seconds() / 60
                corr_section += f"  - {alert.service_name}: {alert.alert_name} ({alert.severity}) - {time_diff:.0f}min ago\n"

        # Dependency/infrastructure alerts
        if corr.dependency_alerts:
            corr_section += (
                f"\n### Infrastructure/Dependency Alerts ({len(corr.dependency_alerts)} alerts)\n"
            )
            corr_section += "Database, cache, network, and other infrastructure alerts:\n"
            for alert in corr.dependency_alerts[:5]:
                time_diff = (state.alert.timestamp - alert.timestamp).total_seconds() / 60
                corr_section += f"  - {alert.service_name}: {alert.alert_name} ({alert.severity}) - {time_diff:.0f}min ago\n"

        if corr.query_errors:
            corr_section += "\n**Query Errors:**\n"
            for err in corr.query_errors:
                corr_section += f"  - {err}\n"

        sections.append(corr_section)
    else:
        sections.append("## Correlated Alerts\nNo historical alert data available.\n")

    # Execution errors
    if state.errors:
        sections.append("## Data Collection Errors\n" + "\n".join(f"- {e}" for e in state.errors))

    return "\n".join(sections)


async def synthesize(state: AgentState) -> StateUpdate:
    """
    Synthesize all collected data into a root cause analysis using LLM.

    Args:
        state: Current agent state with all collected data.

    Returns:
        Updated state with incident analysis.
    """
    log = logger.bind(
        node="synthesize",
        service=state.alert.service_name,
    )
    log.info("synthesizing incident analysis")

    try:
        llm = get_llm()

        # Build prompt
        analysis_prompt = _build_analysis_prompt(state)

        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(
                content=f"""Analyze this incident and provide a root cause analysis.

{analysis_prompt}

IMPORTANT ANALYSIS FOCUS:
- **CORRELATED ALERTS**: First check the "Correlated Alerts" section for potential root causes.
  If there are infrastructure alerts (database, network, cache) that occurred BEFORE this alert,
  they are likely the root cause. Mention them explicitly in your analysis.
- If Kubernetes data shows CrashLoopBackOff or Pending pods, analyze the container configuration deeply
- Check readiness/liveness probes for any that are obviously failing (e.g., exec probes with command "false")
- Look for misconfigurations in command, args, environment variables
- If probes are configured, analyze their failure thresholds and initial delays
- Consider if pod logs indicate the actual error
- Cross-reference Kubernetes pod conditions with container state details
- If multiple services in the same namespace are affected, consider shared dependencies

Respond with a JSON object containing:
- summary: Brief 1-2 sentence summary
- probable_root_cause: Primary hypothesis (be specific about the root cause)
- contributing_factors: List of secondary factors
- evidence: List of data points supporting the hypothesis
- suggested_actions: List of immediate next steps
- confidence: "high", "medium", or "low"
- needs_human_escalation: true/false
- escalation_reason: Reason if escalation needed (optional)
"""
            ),
        ]

        # Invoke LLM
        response = await llm.ainvoke(messages)
        response_text = response.content

        # Parse response
        analysis = _parse_llm_response(response_text, log)

        log.info(
            "analysis completed",
            confidence=analysis.confidence,
            needs_escalation=analysis.needs_human_escalation,
        )

        return {
            "analysis": analysis,
            "completed_at": datetime.utcnow(),
        }

    except Exception as e:
        log.exception("failed to synthesize analysis")

        # Return a fallback analysis
        fallback = IncidentAnalysis(
            summary=f"Analysis failed for {state.alert.service_name} incident",
            probable_root_cause="Unable to determine - analysis failed",
            contributing_factors=[],
            evidence=[],
            suggested_actions=[
                "Manually review metrics in Grafana",
                "Check application logs in Loki",
                "Review recent deployments",
            ],
            confidence="low",
            needs_human_escalation=True,
            escalation_reason=f"Automated analysis failed: {str(e)}",
        )

        return {
            "analysis": fallback,
            "errors": [f"LLM synthesis failed: {str(e)}"],
            "completed_at": datetime.utcnow(),
        }


def _parse_llm_response(response_text: str, log) -> IncidentAnalysis:
    """Parse LLM response into IncidentAnalysis object."""
    import json
    import re

    # Try to extract JSON from response
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return IncidentAnalysis(
                summary=data.get("summary", "No summary provided"),
                probable_root_cause=data.get("probable_root_cause", "Unknown"),
                contributing_factors=data.get("contributing_factors", []),
                evidence=data.get("evidence", []),
                suggested_actions=data.get("suggested_actions", []),
                confidence=data.get("confidence", "low"),
                needs_human_escalation=data.get("needs_human_escalation", False),
                escalation_reason=data.get("escalation_reason"),
            )
        except json.JSONDecodeError as e:
            log.warning("failed to parse JSON response", error=str(e))

    # Fallback: create analysis from plain text
    log.warning("using fallback text parsing")
    return IncidentAnalysis(
        summary=response_text[:200] if response_text else "No analysis generated",
        probable_root_cause="See summary for details",
        contributing_factors=[],
        evidence=[],
        suggested_actions=["Review the analysis manually"],
        confidence="low",
        needs_human_escalation=True,
        escalation_reason="Could not parse structured analysis",
    )
