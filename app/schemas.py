from datetime import datetime
from typing import Optional, List, Any, Dict, Union
from enum import Enum

from pydantic import BaseModel, Field, ConfigDict, field_validator

from .models import (
    InstrumentStatus,
    ReservationStatus,
    AnomalyType,
    UserRole,
    AuditAction,
)


class ConflictType(str, Enum):
    INSTRUMENT_NOT_FOUND = "instrument_not_found"
    INSTRUMENT_STATUS_NOT_ALLOWED = "instrument_status_not_allowed"
    DURATION_EXCEEDS_LIMIT = "duration_exceeds_limit"
    TIME_OVERLAP_WITH_RESERVATION = "time_overlap_with_reservation"
    TIME_OVERLAP_WITH_DOWNTIME = "time_overlap_with_downtime"
    ACTIVE_USAGE_OCCUPANCY = "active_usage_occupancy"
    INVALID_TIME_RANGE = "invalid_time_range"
    PAST_TIME_NOT_ALLOWED = "past_time_not_allowed"


class UserBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: str = Field(..., min_length=1, max_length=200)
    group_name: str = Field(..., min_length=1, max_length=200)
    role: UserRole = UserRole.USER


class UserCreate(UserBase):
    pass


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    group_name: Optional[str] = Field(None, min_length=1, max_length=200)
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class User(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class InstrumentBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    code: str = Field(..., min_length=1, max_length=50)
    location: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    status: InstrumentStatus = InstrumentStatus.AVAILABLE
    max_reservation_hours: float = Field(8.0, gt=0)
    grace_period_minutes: int = Field(15, ge=0)
    no_show_threshold_minutes: int = Field(30, ge=0)
    requires_approval: bool = False


class InstrumentCreate(InstrumentBase):
    pass


class InstrumentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    location: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    status: Optional[InstrumentStatus] = None
    max_reservation_hours: Optional[float] = Field(None, gt=0)
    grace_period_minutes: Optional[int] = Field(None, ge=0)
    no_show_threshold_minutes: Optional[int] = Field(None, ge=0)
    requires_approval: Optional[bool] = None


class Instrument(InstrumentBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime


class DowntimeRecordBase(BaseModel):
    instrument_id: int
    start_time: datetime
    end_time: datetime
    reason: str = Field(..., min_length=1)


class DowntimeRecordCreate(DowntimeRecordBase):
    pass


class DowntimeRecord(DowntimeRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reported_by: Optional[int] = None
    is_resolved: bool
    resolved_at: Optional[datetime] = None
    created_at: datetime


class ReservationBase(BaseModel):
    instrument_id: int
    title: str = Field(..., min_length=1, max_length=300)
    purpose: Optional[str] = None
    start_time: datetime
    end_time: datetime

    @field_validator("end_time")
    @classmethod
    def check_time_order(cls, v: datetime, info) -> datetime:
        start_time = info.data.get("start_time")
        if start_time and v <= start_time:
            raise ValueError("end_time must be after start_time")
        return v


class ReservationCreate(ReservationBase):
    user_id: int


class ReservationUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=300)
    purpose: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None


class Reservation(ReservationBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    status: ReservationStatus
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    cancelled_by: Optional[int] = None
    cancelled_at: Optional[datetime] = None
    cancel_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ReservationDetail(Reservation):
    user: Optional[User] = None
    instrument: Optional[Instrument] = None


class UsageRecordBase(BaseModel):
    instrument_id: int
    user_id: int
    check_in_time: datetime


class UsageRecordCreate(UsageRecordBase):
    reservation_id: Optional[int] = None
    notes: Optional[str] = None


class UsageRecordCheckOut(BaseModel):
    check_out_time: datetime
    notes: Optional[str] = None


class UsageRecord(UsageRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reservation_id: Optional[int] = None
    check_out_time: Optional[datetime] = None
    actual_duration_minutes: Optional[int] = None
    notes: Optional[str] = None
    created_at: datetime


class AnomalyRecordBase(BaseModel):
    anomaly_type: AnomalyType
    instrument_id: int
    description: str = Field(..., min_length=1)


class AnomalyRecordCreate(AnomalyRecordBase):
    reservation_id: Optional[int] = None
    user_id: Optional[int] = None
    severity: int = Field(1, ge=1, le=5)
    extra_data: Optional[str] = None


class AnomalyRecordResolve(BaseModel):
    resolution_note: str = Field(..., min_length=1)
    resolved_by: int


class AnomalyRecord(AnomalyRecordBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reservation_id: Optional[int] = None
    user_id: Optional[int] = None
    detected_at: datetime
    severity: int
    is_resolved: bool
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
    resolved_by: Optional[int] = None
    extra_data: Optional[str] = None


class AuditLogBase(BaseModel):
    entity_type: str
    entity_id: int
    action: AuditAction


class AuditLog(AuditLogBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    operator_id: Optional[int] = None
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    change_reason: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: datetime


class ReservationConflictItem(BaseModel):
    conflict_type: ConflictType
    severity: int = Field(1, ge=1, le=5)
    message: str
    blocked: bool = True
    reference_id: Optional[int] = None
    reference_type: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class ReservationConflictInfo(BaseModel):
    has_conflict: bool
    has_blocking_conflict: bool = False
    conflicts: List[ReservationConflictItem] = []
    conflicting_reservations: List[Reservation] = []
    conflicting_downtimes: List[DowntimeRecord] = []
    active_usage: Optional[UsageRecord] = None
    summary: Optional[str] = None


class InstrumentUsageStats(BaseModel):
    instrument_id: int
    instrument_name: str
    total_reservations: int
    completed_reservations: int
    cancelled_reservations: int
    no_show_count: int
    total_usage_minutes: int
    overtime_count: int
    anomaly_count: int
    utilization_rate: float


class GroupUsageStats(BaseModel):
    group_name: str
    total_reservations: int
    total_users: int
    total_usage_minutes: int
    no_show_count: int
    overtime_count: int
    anomaly_count: int


class TimeRangeStats(BaseModel):
    start_time: datetime
    end_time: datetime
    total_reservations: int
    total_usage_minutes: int
    anomaly_count: int
    top_instruments: List[Dict[str, Any]] = []
    top_groups: List[Dict[str, Any]] = []


class ReservationTrace(BaseModel):
    reservation: ReservationDetail
    usage_records: List[UsageRecord] = []
    anomalies: List[AnomalyRecord] = []
    audit_logs: List[AuditLog] = []
