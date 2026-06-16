import enum
from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    DateTime,
    ForeignKey,
    Enum,
    Boolean,
    Float,
    Index,
)
from sqlalchemy.orm import relationship

from .database import Base


class InstrumentStatus(str, enum.Enum):
    AVAILABLE = "available"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"
    FAULT = "fault"


class ReservationStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    IN_USE = "in_use"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    NO_SHOW = "no_show"


class AnomalyType(str, enum.Enum):
    OVERTIME_OCCUPANCY = "overtime_occupancy"
    NO_SHOW = "no_show"
    EARLY_USE = "early_use"
    TEMPORARY_DOWNTIME = "temporary_downtime"
    EQUIPMENT_FAULT = "equipment_fault"
    SCHEDULE_CONFLICT = "schedule_conflict"
    UNAUTHORIZED_USE = "unauthorized_use"


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    GROUP_LEADER = "group_leader"
    USER = "user"


class AuditAction(str, enum.Enum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"
    STATUS_CHANGE = "status_change"
    CHECK_IN = "check_in"
    CHECK_OUT = "check_out"
    CANCEL = "cancel"
    APPROVE = "approve"
    REJECT = "reject"
    ANOMALY_DETECTED = "anomaly_detected"
    ANOMALY_RESOLVED = "anomaly_resolved"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(200), unique=True, nullable=False, index=True)
    group_name = Column(String(200), nullable=False, index=True)
    role = Column(Enum(UserRole), default=UserRole.USER, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    reservations = relationship("Reservation", back_populates="user", foreign_keys="Reservation.user_id")
    usage_records = relationship("UsageRecord", back_populates="user")


class Instrument(Base):
    __tablename__ = "instruments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False, index=True)
    code = Column(String(50), unique=True, nullable=False, index=True)
    location = Column(String(200))
    description = Column(Text)
    status = Column(Enum(InstrumentStatus), default=InstrumentStatus.AVAILABLE, nullable=False)
    max_reservation_hours = Column(Float, default=8.0)
    grace_period_minutes = Column(Integer, default=15)
    no_show_threshold_minutes = Column(Integer, default=30)
    requires_approval = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    reservations = relationship("Reservation", back_populates="instrument")
    usage_records = relationship("UsageRecord", back_populates="instrument")
    anomalies = relationship("AnomalyRecord", back_populates="instrument")
    downtime_records = relationship("DowntimeRecord", back_populates="instrument")


class DowntimeRecord(Base):
    __tablename__ = "downtime_records"

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False)
    reason = Column(Text, nullable=False)
    reported_by = Column(Integer, ForeignKey("users.id"))
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    instrument = relationship("Instrument", back_populates="downtime_records")


class Reservation(Base):
    __tablename__ = "reservations"
    __table_args__ = (
        Index("idx_instrument_time", "instrument_id", "start_time", "end_time"),
        Index("idx_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(300), nullable=False)
    purpose = Column(Text)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False, index=True)
    status = Column(Enum(ReservationStatus), default=ReservationStatus.PENDING, nullable=False, index=True)
    approved_by = Column(Integer, ForeignKey("users.id"))
    approved_at = Column(DateTime)
    cancelled_by = Column(Integer, ForeignKey("users.id"))
    cancelled_at = Column(DateTime)
    cancel_reason = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    instrument = relationship("Instrument", back_populates="reservations")
    user = relationship("User", back_populates="reservations", foreign_keys=[user_id])
    approver = relationship("User", foreign_keys=[approved_by])
    canceller = relationship("User", foreign_keys=[cancelled_by])
    usage_records = relationship("UsageRecord", back_populates="reservation")
    anomalies = relationship("AnomalyRecord", back_populates="reservation")


class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(Integer, primary_key=True, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    check_in_time = Column(DateTime, nullable=False)
    check_out_time = Column(DateTime)
    actual_duration_minutes = Column(Integer)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    reservation = relationship("Reservation", back_populates="usage_records")
    instrument = relationship("Instrument", back_populates="usage_records")
    user = relationship("User", back_populates="usage_records")


class AnomalyRecord(Base):
    __tablename__ = "anomaly_records"
    __table_args__ = (
        Index("idx_anomaly_type_time", "anomaly_type", "detected_at"),
        Index("idx_anomaly_instrument", "instrument_id", "detected_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    anomaly_type = Column(Enum(AnomalyType), nullable=False, index=True)
    instrument_id = Column(Integer, ForeignKey("instruments.id"), nullable=False, index=True)
    reservation_id = Column(Integer, ForeignKey("reservations.id"), index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    detected_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    description = Column(Text, nullable=False)
    severity = Column(Integer, default=1)
    is_resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)
    resolution_note = Column(Text)
    resolved_by = Column(Integer, ForeignKey("users.id"))
    extra_data = Column(Text)

    instrument = relationship("Instrument", back_populates="anomalies")
    reservation = relationship("Reservation", back_populates="anomalies")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_entity", "entity_type", "entity_id"),
        Index("idx_audit_action_time", "action", "created_at"),
        Index("idx_audit_operator", "operator_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String(50), nullable=False, index=True)
    entity_id = Column(Integer, nullable=False, index=True)
    action = Column(Enum(AuditAction), nullable=False, index=True)
    operator_id = Column(Integer, ForeignKey("users.id"), index=True)
    old_value = Column(Text)
    new_value = Column(Text)
    change_reason = Column(Text)
    ip_address = Column(String(50))
    user_agent = Column(String(500))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
