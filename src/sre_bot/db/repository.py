"""Repository for database operations."""

from collections.abc import Sequence
from datetime import datetime, timedelta

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from sre_bot.agent.state import AgentState
from sre_bot.config import get_settings
from sre_bot.db.models import Base, Incident, IncidentFeedback, LearnedSolution

logger = structlog.get_logger()

# Global engine and session factory
_engine = None
_session_factory = None


async def init_db() -> None:
    """
    Initialize the database connection and create tables.

    Should be called once at application startup.
    """
    global _engine, _session_factory

    settings = get_settings()
    log = logger.bind(component="database")

    log.info("initializing database", url=settings.database_url.split("@")[-1])

    _engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    # Create tables
    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    log.info("database initialized")


async def close_db() -> None:
    """Close the database connection."""
    global _engine

    if _engine:
        await _engine.dispose()
        logger.info("database connection closed")


def get_session() -> AsyncSession:
    """
    Get a database session.

    Returns:
        AsyncSession for database operations.

    Raises:
        RuntimeError: If database not initialized.
    """
    if _session_factory is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")

    return _session_factory()


class IncidentRepository:
    """Repository for incident CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._log = logger.bind(repository="incident")

    async def create_from_state(
        self,
        state: AgentState,
        source: str = "webhook",
    ) -> Incident:
        """
        Create an incident record from agent state.

        Args:
            state: Final agent state after investigation.
            source: Source of the incident (webhook, slack, manual).

        Returns:
            Created Incident record.
        """
        alert = state.alert
        analysis = state.analysis

        # Calculate duration
        duration = None
        if state.completed_at and state.started_at:
            duration = (state.completed_at - state.started_at).total_seconds()

        incident = Incident(
            # Alert context
            alert_name=alert.alert_name,
            severity=alert.severity,
            service_name=alert.service_name,
            cluster=alert.cluster,
            namespace=alert.namespace,
            pod=alert.pod,
            alert_timestamp=alert.timestamp,
            alert_description=alert.description,
            raw_alert_payload=alert.raw_payload,
            # Collected data
            metrics_data=state.metrics.model_dump() if state.metrics else None,
            logs_data=state.logs.model_dump() if state.logs else None,
            traces_data=state.traces.model_dump() if state.traces else None,
            github_data=state.github.model_dump() if state.github else None,
            # Analysis
            analysis_summary=analysis.summary if analysis else None,
            probable_root_cause=analysis.probable_root_cause if analysis else None,
            contributing_factors=analysis.contributing_factors if analysis else None,
            evidence=analysis.evidence if analysis else None,
            suggested_actions=analysis.suggested_actions if analysis else None,
            confidence=analysis.confidence if analysis else None,
            needs_escalation=analysis.needs_human_escalation if analysis else False,
            escalation_reason=analysis.escalation_reason if analysis else None,
            # Execution metadata
            investigation_started_at=state.started_at,
            investigation_completed_at=state.completed_at,
            investigation_duration_seconds=duration,
            errors=state.errors if state.errors else None,
            # Slack
            slack_channel=state.slack_channel,
            slack_thread_ts=state.slack_thread_ts,
            slack_message_ts=state.slack_message_ts,
            # Source
            source=source,
        )

        self.session.add(incident)
        await self.session.commit()
        await self.session.refresh(incident)

        self._log.info(
            "incident created",
            incident_id=incident.id,
            service=incident.service_name,
            alert=incident.alert_name,
        )

        return incident

    async def get_by_id(self, incident_id: int) -> Incident | None:
        """Get incident by ID."""
        result = await self.session.execute(select(Incident).where(Incident.id == incident_id))
        return result.scalar_one_or_none()

    async def get_recent(
        self,
        limit: int = 50,
        service_name: str | None = None,
        namespace: str | None = None,
        severity: str | None = None,
    ) -> Sequence[Incident]:
        """
        Get recent incidents with optional filters.

        Args:
            limit: Maximum number of incidents to return.
            service_name: Filter by service name.
            namespace: Filter by namespace.
            severity: Filter by severity.

        Returns:
            List of incidents, most recent first.
        """
        query = select(Incident).order_by(Incident.created_at.desc()).limit(limit)

        if service_name:
            query = query.where(Incident.service_name == service_name)
        if namespace:
            query = query.where(Incident.namespace == namespace)
        if severity:
            query = query.where(Incident.severity == severity)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_similar(
        self,
        service_name: str,
        alert_name: str,
        days: int = 30,
        limit: int = 10,
    ) -> Sequence[Incident]:
        """
        Find similar past incidents.

        Useful for providing context about recurring issues.

        Args:
            service_name: Service to search for.
            alert_name: Alert name to match.
            days: Look back window in days.
            limit: Maximum results.

        Returns:
            List of similar incidents.
        """
        since = datetime.utcnow() - timedelta(days=days)

        query = (
            select(Incident)
            .where(
                Incident.service_name == service_name,
                Incident.alert_name == alert_name,
                Incident.created_at >= since,
            )
            .order_by(Incident.created_at.desc())
            .limit(limit)
        )

        result = await self.session.execute(query)
        return result.scalars().all()

    async def add_feedback(
        self,
        incident_id: int,
        feedback_type: str,
        correct_root_cause: str | None = None,
        additional_notes: str | None = None,
        slack_user_id: str | None = None,
        slack_username: str | None = None,
    ) -> IncidentFeedback:
        """
        Add feedback to an incident.

        Args:
            incident_id: ID of the incident.
            feedback_type: Type of feedback (correct, incorrect, partial, unknown).
            correct_root_cause: The actual root cause if analysis was wrong.
            additional_notes: Any additional notes.
            slack_user_id: Slack user ID who provided feedback.
            slack_username: Slack username.

        Returns:
            Created IncidentFeedback record.
        """
        feedback = IncidentFeedback(
            incident_id=incident_id,
            feedback_type=feedback_type,
            correct_root_cause=correct_root_cause,
            additional_notes=additional_notes,
            slack_user_id=slack_user_id,
            slack_username=slack_username,
        )

        self.session.add(feedback)
        await self.session.commit()
        await self.session.refresh(feedback)

        self._log.info(
            "feedback added",
            incident_id=incident_id,
            feedback_type=feedback_type,
        )

        return feedback

    async def get_correlated_alerts(
        self,
        current_alert_timestamp: datetime,
        service_name: str,
        namespace: str,
        time_window_minutes: int = 120,
        exclude_incident_id: int | None = None,
    ) -> dict[str, Sequence[Incident]]:
        """
        Find potentially related alerts that occurred before the current alert.

        This method searches for alerts that may have caused or contributed
        to the current incident by looking at:
        - Recent alerts from the same service
        - Recent alerts in the same namespace (potential dependencies)
        - Infrastructure alerts that could affect multiple services

        Args:
            current_alert_timestamp: Timestamp of the current alert.
            service_name: Name of the affected service.
            namespace: Kubernetes namespace.
            time_window_minutes: How far back to search (default: 2 hours).
            exclude_incident_id: Incident ID to exclude (current incident).

        Returns:
            Dictionary with categorized related alerts:
            - same_service: Alerts for the same service
            - same_namespace: Alerts in the same namespace (different services)
            - infrastructure: Alerts that may indicate infrastructure issues
        """
        window_start = current_alert_timestamp - timedelta(minutes=time_window_minutes)

        # Infrastructure-related keywords that often indicate root causes
        infra_keywords = [
            "database",
            "db",
            "postgres",
            "mysql",
            "redis",
            "kafka",
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
        ]

        # Query for same service alerts
        same_service_query = (
            select(Incident)
            .where(
                Incident.service_name == service_name,
                Incident.alert_timestamp >= window_start,
                Incident.alert_timestamp < current_alert_timestamp,
            )
            .order_by(Incident.alert_timestamp.desc())
            .limit(10)
        )

        if exclude_incident_id:
            same_service_query = same_service_query.where(Incident.id != exclude_incident_id)

        same_service_result = await self.session.execute(same_service_query)
        same_service_alerts = same_service_result.scalars().all()

        # Query for same namespace alerts (different services)
        same_namespace_query = (
            select(Incident)
            .where(
                Incident.namespace == namespace,
                Incident.service_name != service_name,
                Incident.alert_timestamp >= window_start,
                Incident.alert_timestamp < current_alert_timestamp,
            )
            .order_by(Incident.alert_timestamp.desc())
            .limit(15)
        )

        if exclude_incident_id:
            same_namespace_query = same_namespace_query.where(Incident.id != exclude_incident_id)

        same_namespace_result = await self.session.execute(same_namespace_query)
        same_namespace_alerts = same_namespace_result.scalars().all()

        # Query for all recent alerts to filter for infrastructure
        all_recent_query = (
            select(Incident)
            .where(
                Incident.alert_timestamp >= window_start,
                Incident.alert_timestamp < current_alert_timestamp,
                Incident.service_name != service_name,
            )
            .order_by(Incident.alert_timestamp.desc())
            .limit(50)
        )

        if exclude_incident_id:
            all_recent_query = all_recent_query.where(Incident.id != exclude_incident_id)

        all_recent_result = await self.session.execute(all_recent_query)
        all_recent_alerts = all_recent_result.scalars().all()

        # Filter for infrastructure-related alerts
        infra_alerts = []
        for incident in all_recent_alerts:
            alert_lower = incident.alert_name.lower()
            service_lower = incident.service_name.lower()
            description_lower = (incident.alert_description or "").lower()

            for keyword in infra_keywords:
                if (
                    keyword in alert_lower
                    or keyword in service_lower
                    or keyword in description_lower
                ):
                    infra_alerts.append(incident)
                    break

        self._log.info(
            "correlated alerts found",
            same_service=len(same_service_alerts),
            same_namespace=len(same_namespace_alerts),
            infrastructure=len(infra_alerts),
            time_window_minutes=time_window_minutes,
        )

        return {
            "same_service": same_service_alerts,
            "same_namespace": same_namespace_alerts,
            "infrastructure": infra_alerts,
        }

    async def get_stats(
        self,
        days: int = 30,
    ) -> dict:
        """
        Get incident statistics.

        Args:
            days: Look back window in days.

        Returns:
            Dictionary with statistics.
        """
        since = datetime.utcnow() - timedelta(days=days)

        # Get all incidents in window
        query = select(Incident).where(Incident.created_at >= since)
        result = await self.session.execute(query)
        incidents = result.scalars().all()

        # Calculate stats
        total = len(incidents)
        by_severity = {}
        by_service = {}
        escalated = 0
        with_analysis = 0
        avg_duration = 0.0

        durations = []

        for incident in incidents:
            # By severity
            by_severity[incident.severity] = by_severity.get(incident.severity, 0) + 1

            # By service
            by_service[incident.service_name] = by_service.get(incident.service_name, 0) + 1

            # Escalated
            if incident.needs_escalation:
                escalated += 1

            # With analysis
            if incident.analysis_summary:
                with_analysis += 1

            # Duration
            if incident.investigation_duration_seconds:
                durations.append(incident.investigation_duration_seconds)

        if durations:
            avg_duration = sum(durations) / len(durations)

        return {
            "total_incidents": total,
            "by_severity": by_severity,
            "by_service": by_service,
            "escalated_count": escalated,
            "with_analysis_count": with_analysis,
            "average_duration_seconds": avg_duration,
            "period_days": days,
        }


class LearnedSolutionRepository:
    """Repository for learned solutions CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._log = logger.bind(repository="learned_solution")

    async def create(
        self,
        alert_name: str,
        service_name: str,
        root_cause: str,
        solution_steps: list[str],
        namespace: str | None = None,
        error_pattern: str | None = None,
        symptoms: list[str] | None = None,
        prevention_tips: list[str] | None = None,
        source_incident_id: int | None = None,
        validated_by: str | None = None,
    ) -> LearnedSolution:
        """
        Create a new learned solution.

        Args:
            alert_name: Name of the alert this solution applies to.
            service_name: Service this solution applies to.
            root_cause: The root cause that was identified.
            solution_steps: Steps to resolve the issue.
            namespace: Optional namespace filter.
            error_pattern: Regex or text pattern for error matching.
            symptoms: List of symptoms to identify this issue.
            prevention_tips: How to prevent this in the future.
            source_incident_id: Original incident this was learned from.
            validated_by: User who validated this solution.

        Returns:
            Created LearnedSolution record.
        """
        solution = LearnedSolution(
            alert_name=alert_name,
            service_name=service_name,
            namespace=namespace,
            error_pattern=error_pattern,
            symptoms=symptoms,
            root_cause=root_cause,
            solution_steps=solution_steps,
            prevention_tips=prevention_tips,
            source_incident_id=source_incident_id,
            validated_by=validated_by,
        )

        self.session.add(solution)
        await self.session.commit()
        await self.session.refresh(solution)

        self._log.info(
            "learned solution created",
            solution_id=solution.id,
            alert_name=alert_name,
            service_name=service_name,
        )

        return solution

    async def create_from_incident(
        self,
        incident: Incident,
        validated_by: str | None = None,
        additional_tips: list[str] | None = None,
    ) -> LearnedSolution:
        """
        Create a learned solution from a validated incident.

        Args:
            incident: Incident with successful analysis.
            validated_by: User who validated this solution.
            additional_tips: Extra prevention tips to add.

        Returns:
            Created LearnedSolution record.
        """
        # Extract symptoms from the incident data
        symptoms = []
        if incident.contributing_factors:
            symptoms.extend(incident.contributing_factors)

        # Build solution steps from suggested actions
        solution_steps = incident.suggested_actions or ["Review the incident analysis"]

        return await self.create(
            alert_name=incident.alert_name,
            service_name=incident.service_name,
            namespace=incident.namespace,
            root_cause=incident.probable_root_cause or "Unknown",
            solution_steps=solution_steps,
            symptoms=symptoms if symptoms else None,
            prevention_tips=additional_tips,
            source_incident_id=incident.id,
            validated_by=validated_by,
        )

    async def find_similar(
        self,
        alert_name: str,
        service_name: str,
        namespace: str | None = None,
        limit: int = 5,
    ) -> Sequence[LearnedSolution]:
        """
        Find similar learned solutions for an alert.

        Matching priority:
        1. Exact match on alert_name + service_name + namespace
        2. Exact match on alert_name + service_name
        3. Same service_name with similar alert patterns
        4. Same alert_name across services (generic solutions)

        Args:
            alert_name: Current alert name.
            service_name: Current service name.
            namespace: Current namespace.
            limit: Maximum results.

        Returns:
            List of similar solutions, ordered by relevance.
        """
        solutions = []

        # Priority 1: Exact match with namespace
        if namespace:
            exact_query = (
                select(LearnedSolution)
                .where(
                    LearnedSolution.alert_name == alert_name,
                    LearnedSolution.service_name == service_name,
                    LearnedSolution.namespace == namespace,
                )
                .order_by(LearnedSolution.success_count.desc())
                .limit(limit)
            )
            result = await self.session.execute(exact_query)
            solutions.extend(result.scalars().all())

        # Priority 2: Same alert + service (any namespace)
        if len(solutions) < limit:
            remaining = limit - len(solutions)
            existing_ids = [s.id for s in solutions]

            service_query = (
                select(LearnedSolution)
                .where(
                    LearnedSolution.alert_name == alert_name,
                    LearnedSolution.service_name == service_name,
                    LearnedSolution.id.notin_(existing_ids) if existing_ids else True,
                )
                .order_by(LearnedSolution.success_count.desc())
                .limit(remaining)
            )
            result = await self.session.execute(service_query)
            solutions.extend(result.scalars().all())

        # Priority 3: Same service, different alerts (service-specific patterns)
        if len(solutions) < limit:
            remaining = limit - len(solutions)
            existing_ids = [s.id for s in solutions]

            same_service_query = (
                select(LearnedSolution)
                .where(
                    LearnedSolution.service_name == service_name,
                    LearnedSolution.id.notin_(existing_ids) if existing_ids else True,
                )
                .order_by(LearnedSolution.success_count.desc())
                .limit(remaining)
            )
            result = await self.session.execute(same_service_query)
            solutions.extend(result.scalars().all())

        # Priority 4: Same alert name across services (generic solutions)
        if len(solutions) < limit:
            remaining = limit - len(solutions)
            existing_ids = [s.id for s in solutions]

            generic_query = (
                select(LearnedSolution)
                .where(
                    LearnedSolution.alert_name == alert_name,
                    LearnedSolution.id.notin_(existing_ids) if existing_ids else True,
                )
                .order_by(LearnedSolution.success_count.desc())
                .limit(remaining)
            )
            result = await self.session.execute(generic_query)
            solutions.extend(result.scalars().all())

        self._log.info(
            "found similar solutions",
            alert_name=alert_name,
            service_name=service_name,
            count=len(solutions),
        )

        return solutions

    async def record_usage(
        self,
        solution_id: int,
        was_successful: bool,
    ) -> None:
        """
        Record that a solution was used and whether it was successful.

        Args:
            solution_id: ID of the solution used.
            was_successful: Whether the solution resolved the issue.
        """
        solution = await self.session.get(LearnedSolution, solution_id)
        if solution:
            solution.times_used += 1
            solution.last_used_at = datetime.utcnow()
            if was_successful:
                solution.success_count += 1
            else:
                solution.failure_count += 1

            await self.session.commit()

            self._log.info(
                "solution usage recorded",
                solution_id=solution_id,
                was_successful=was_successful,
                total_uses=solution.times_used,
            )

    async def get_top_solutions(
        self,
        service_name: str | None = None,
        limit: int = 10,
    ) -> Sequence[LearnedSolution]:
        """
        Get top performing solutions.

        Args:
            service_name: Optional filter by service.
            limit: Maximum results.

        Returns:
            Solutions ordered by success count.
        """
        query = (
            select(LearnedSolution)
            .where(LearnedSolution.success_count > 0)
            .order_by(LearnedSolution.success_count.desc())
            .limit(limit)
        )

        if service_name:
            query = query.where(LearnedSolution.service_name == service_name)

        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_by_id(self, solution_id: int) -> LearnedSolution | None:
        """Get solution by ID."""
        return await self.session.get(LearnedSolution, solution_id)
