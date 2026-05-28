"""SQLAlchemy models for incident persistence."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Incident(Base):
    """
    Record of an incident investigation.

    Stores the alert context, collected data, analysis results,
    and metadata about the investigation.
    """

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Alert context
    alert_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    cluster: Mapped[str] = mapped_column(String(255), nullable=False)
    namespace: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    pod: Mapped[str | None] = mapped_column(String(255), nullable=True)
    alert_timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    alert_description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw data (JSON)
    raw_alert_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    metrics_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    logs_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    traces_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    github_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # Analysis results
    analysis_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    probable_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    contributing_factors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    evidence: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    suggested_actions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[str | None] = mapped_column(String(50), nullable=True)
    needs_escalation: Mapped[bool] = mapped_column(default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Execution metadata
    investigation_started_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )
    investigation_completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    investigation_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    errors: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Slack metadata
    slack_channel: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_thread_ts: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_message_ts: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Source tracking
    source: Mapped[str] = mapped_column(
        String(50), default="webhook", nullable=False
    )  # webhook, slack, manual

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    # Relationships
    feedback: Mapped[list["IncidentFeedback"]] = relationship(
        "IncidentFeedback", back_populates="incident", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return (
            f"<Incident(id={self.id}, alert={self.alert_name}, "
            f"service={self.service_name}, severity={self.severity})>"
        )


class IncidentFeedback(Base):
    """
    Human feedback on incident analysis.

    Used for tracking accuracy and improving prompts.
    """

    __tablename__ = "incident_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("incidents.id"), nullable=False, index=True
    )

    # Feedback data
    feedback_type: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # correct, incorrect, partial, unknown
    correct_root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # User info
    slack_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    slack_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    incident: Mapped["Incident"] = relationship("Incident", back_populates="feedback")

    def __repr__(self) -> str:
        return f"<IncidentFeedback(id={self.id}, incident_id={self.incident_id}, type={self.feedback_type})>"


class LearnedSolution(Base):
    """
    Validated solutions learned from past incidents.

    Stores successful resolutions that can be used as context
    for future similar alerts.
    """

    __tablename__ = "learned_solutions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Alert identification (for matching similar alerts)
    alert_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    service_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    namespace: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Problem identification
    error_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    symptoms: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Solution data
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    solution_steps: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    prevention_tips: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    # Effectiveness tracking
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)

    # Source tracking
    source_incident_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("incidents.id"), nullable=True
    )
    validated_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Relationships
    source_incident: Mapped["Incident | None"] = relationship(
        "Incident", foreign_keys=[source_incident_id]
    )

    def __repr__(self) -> str:
        return (
            f"<LearnedSolution(id={self.id}, alert={self.alert_name}, service={self.service_name})>"
        )

    @property
    def success_rate(self) -> float:
        """Calculate success rate of this solution."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 0.0
        return self.success_count / total
