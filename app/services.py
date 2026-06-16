from datetime import datetime, timedelta
from typing import List, Optional, Tuple, Dict, Any
from collections import defaultdict

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, func

from . import models, schemas
from .config import settings
from .audit import AuditLogger
from .models import (
    ReservationStatus,
    InstrumentStatus,
    AnomalyType,
    AuditAction,
)


ACTIVE_STATUSES = [
    ReservationStatus.PENDING,
    ReservationStatus.CONFIRMED,
    ReservationStatus.IN_USE,
]

FINAL_STATUSES = [
    ReservationStatus.COMPLETED,
    ReservationStatus.CANCELLED,
    ReservationStatus.EXPIRED,
    ReservationStatus.NO_SHOW,
]


class ReservationService:
    def __init__(self, db: Session, operator_id: Optional[int] = None):
        self.db = db
        self.operator_id = operator_id
        self.audit = AuditLogger(db)

    def _time_overlaps(
        self, start1: datetime, end1: datetime, start2: datetime, end2: datetime
    ) -> bool:
        return start1 < end2 and start2 < end1

    def check_conflicts(
        self,
        instrument_id: int,
        start_time: datetime,
        end_time: datetime,
        exclude_reservation_id: Optional[int] = None,
    ) -> schemas.ReservationConflictInfo:
        instrument = self.db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
        if not instrument:
            return schemas.ReservationConflictInfo(
                has_conflict=True, conflict_reason="Instrument not found"
            )

        if instrument.status in [InstrumentStatus.OUT_OF_SERVICE, InstrumentStatus.FAULT]:
            return schemas.ReservationConflictInfo(
                has_conflict=True,
                conflict_reason=f"Instrument is {instrument.status.value}, not available for reservation",
            )

        duration_hours = (end_time - start_time).total_seconds() / 3600
        max_hours = instrument.max_reservation_hours or settings.DEFAULT_MAX_RESERVATION_HOURS
        if duration_hours > max_hours:
            return schemas.ReservationConflictInfo(
                has_conflict=True,
                conflict_reason=f"Reservation duration ({duration_hours:.1f}h) exceeds maximum allowed ({max_hours}h)",
            )

        query = self.db.query(models.Reservation).filter(
            models.Reservation.instrument_id == instrument_id,
            models.Reservation.status.in_(ACTIVE_STATUSES),
        )
        if exclude_reservation_id:
            query = query.filter(models.Reservation.id != exclude_reservation_id)

        existing_reservations = query.all()
        conflicts = []
        for r in existing_reservations:
            if self._time_overlaps(start_time, end_time, r.start_time, r.end_time):
                conflicts.append(r)

        if conflicts:
            return schemas.ReservationConflictInfo(
                has_conflict=True,
                conflicting_reservations=[schemas.Reservation.model_validate(c) for c in conflicts],
                conflict_reason=f"Time conflicts with {len(conflicts)} existing reservation(s)",
            )

        downtimes = self.db.query(models.DowntimeRecord).filter(
            models.DowntimeRecord.instrument_id == instrument_id,
            models.DowntimeRecord.is_resolved == False,
        ).all()
        for dt in downtimes:
            if self._time_overlaps(start_time, end_time, dt.start_time, dt.end_time):
                return schemas.ReservationConflictInfo(
                    has_conflict=True,
                    conflict_reason=f"Instrument has scheduled downtime from {dt.start_time} to {dt.end_time}: {dt.reason}",
                )

        return schemas.ReservationConflictInfo(has_conflict=False)

    def create_reservation(
        self, data: schemas.ReservationCreate
    ) -> Tuple[models.Reservation, Optional[schemas.ReservationConflictInfo]]:
        conflict = self.check_conflicts(data.instrument_id, data.start_time, data.end_time)
        if conflict.has_conflict:
            return None, conflict

        instrument = self.db.query(models.Instrument).filter(models.Instrument.id == data.instrument_id).first()
        initial_status = (
            ReservationStatus.PENDING if instrument.requires_approval else ReservationStatus.CONFIRMED
        )

        reservation = models.Reservation(
            instrument_id=data.instrument_id,
            user_id=data.user_id,
            title=data.title,
            purpose=data.purpose,
            start_time=data.start_time,
            end_time=data.end_time,
            status=initial_status,
        )
        self.db.add(reservation)
        self.db.flush()
        self.db.refresh(reservation)

        self.audit.log_create(
            "reservation",
            reservation.id,
            schemas.Reservation.model_validate(reservation).model_dump(),
            operator_id=self.operator_id or data.user_id,
        )

        return reservation, None

    def update_reservation(
        self, reservation_id: int, data: schemas.ReservationUpdate
    ) -> Tuple[Optional[models.Reservation], Optional[str]]:
        reservation = self.db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
        if not reservation:
            return None, "Reservation not found"

        if reservation.status in FINAL_STATUSES:
            return None, f"Cannot update reservation in {reservation.status.value} status"

        old_data = schemas.Reservation.model_validate(reservation).model_dump()

        new_start = data.start_time if data.start_time is not None else reservation.start_time
        new_end = data.end_time if data.end_time is not None else reservation.end_time

        if data.start_time is not None or data.end_time is not None:
            conflict = self.check_conflicts(
                reservation.instrument_id, new_start, new_end, exclude_reservation_id=reservation_id
            )
            if conflict.has_conflict:
                return None, conflict.conflict_reason

        if data.title is not None:
            reservation.title = data.title
        if data.purpose is not None:
            reservation.purpose = data.purpose
        if data.start_time is not None:
            reservation.start_time = data.start_time
        if data.end_time is not None:
            reservation.end_time = data.end_time

        self.db.flush()
        self.db.refresh(reservation)

        self.audit.log_update(
            "reservation",
            reservation.id,
            old_data,
            schemas.Reservation.model_validate(reservation).model_dump(),
            operator_id=self.operator_id or reservation.user_id,
        )

        return reservation, None

    def approve_reservation(self, reservation_id: int, approver_id: int) -> Optional[models.Reservation]:
        reservation = self.db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
        if not reservation:
            return None
        if reservation.status != ReservationStatus.PENDING:
            return None

        old_status = reservation.status
        reservation.status = ReservationStatus.CONFIRMED
        reservation.approved_by = approver_id
        reservation.approved_at = datetime.utcnow()

        self.db.flush()
        self.db.refresh(reservation)

        self.audit.log_status_change(
            "reservation", reservation.id, old_status, reservation.status, operator_id=approver_id
        )
        self.audit.log(
            "reservation",
            reservation.id,
            AuditAction.APPROVE,
            operator_id=approver_id,
            new_value={"approved_at": reservation.approved_at.isoformat()},
        )

        return reservation

    def reject_reservation(self, reservation_id: int, rejecter_id: int, reason: str) -> Optional[models.Reservation]:
        reservation = self.db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
        if not reservation:
            return None
        if reservation.status != ReservationStatus.PENDING:
            return None

        old_status = reservation.status
        reservation.status = ReservationStatus.CANCELLED
        reservation.cancelled_by = rejecter_id
        reservation.cancelled_at = datetime.utcnow()
        reservation.cancel_reason = reason

        self.db.flush()
        self.db.refresh(reservation)

        self.audit.log_status_change(
            "reservation", reservation.id, old_status, reservation.status,
            operator_id=rejecter_id, change_reason=reason,
        )

        return reservation

    def cancel_reservation(
        self, reservation_id: int, canceller_id: int, reason: Optional[str] = None
    ) -> Optional[models.Reservation]:
        reservation = self.db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
        if not reservation:
            return None
        if reservation.status in FINAL_STATUSES:
            return None

        old_status = reservation.status
        reservation.status = ReservationStatus.CANCELLED
        reservation.cancelled_by = canceller_id
        reservation.cancelled_at = datetime.utcnow()
        reservation.cancel_reason = reason

        self.db.flush()
        self.db.refresh(reservation)

        self.audit.log_status_change(
            "reservation", reservation.id, old_status, reservation.status,
            operator_id=canceller_id, change_reason=reason,
        )
        self.audit.log(
            "reservation", reservation.id, AuditAction.CANCEL,
            operator_id=canceller_id, new_value={"cancel_reason": reason},
        )

        return reservation

    def auto_expire_stale_reservations(self) -> int:
        now = datetime.utcnow()
        expired_count = 0

        pending_to_expire = self.db.query(models.Reservation).filter(
            models.Reservation.status.in_([ReservationStatus.PENDING, ReservationStatus.CONFIRMED]),
            models.Reservation.end_time < now,
        ).all()

        for r in pending_to_expire:
            old_status = r.status
            r.status = ReservationStatus.EXPIRED
            self.audit.log_status_change("reservation", r.id, old_status, r.status)
            expired_count += 1

        self.db.flush()
        return expired_count


class UsageService:
    def __init__(self, db: Session, operator_id: Optional[int] = None):
        self.db = db
        self.operator_id = operator_id
        self.audit = AuditLogger(db)
        self.anomaly_service = AnomalyService(db, operator_id)

    def check_in(
        self, data: schemas.UsageRecordCreate
    ) -> Tuple[Optional[models.UsageRecord], Optional[str]]:
        instrument = self.db.query(models.Instrument).filter(models.Instrument.id == data.instrument_id).first()
        if not instrument:
            return None, "Instrument not found"

        if instrument.status in [InstrumentStatus.OUT_OF_SERVICE, InstrumentStatus.FAULT]:
            return None, f"Instrument is {instrument.status.value}"

        active_use = self.db.query(models.UsageRecord).filter(
            models.UsageRecord.instrument_id == data.instrument_id,
            models.UsageRecord.check_out_time == None,
        ).first()
        if active_use:
            return None, "Instrument is currently in use (active check-in exists)"

        reservation = None
        if data.reservation_id:
            reservation = self.db.query(models.Reservation).filter(
                models.Reservation.id == data.reservation_id
            ).first()
            if not reservation:
                return None, "Reservation not found"
            if reservation.status not in [ReservationStatus.CONFIRMED, ReservationStatus.IN_USE]:
                return None, f"Reservation is not confirmed (status: {reservation.status.value})"
            if reservation.user_id != data.user_id:
                return None, "Reservation does not belong to this user"

            grace = timedelta(minutes=instrument.grace_period_minutes or settings.DEFAULT_GRACE_PERIOD_MINUTES)
            allowed_start = reservation.start_time - grace
            if data.check_in_time < allowed_start:
                self.anomaly_service.create_anomaly(
                    schemas.AnomalyRecordCreate(
                        anomaly_type=AnomalyType.EARLY_USE,
                        instrument_id=data.instrument_id,
                        reservation_id=data.reservation_id,
                        user_id=data.user_id,
                        description=f"Checked in {(allowed_start - data.check_in_time).total_seconds() / 60:.0f} minutes before allowed start time",
                        severity=2,
                    )
                )

            if reservation.status == ReservationStatus.CONFIRMED:
                old_status = reservation.status
                reservation.status = ReservationStatus.IN_USE
                self.audit.log_status_change(
                    "reservation", reservation.id, old_status, reservation.status,
                    operator_id=self.operator_id or data.user_id,
                )
        else:
            grace = timedelta(minutes=instrument.grace_period_minutes or settings.DEFAULT_GRACE_PERIOD_MINUTES)
            overlapping_reservation = self.db.query(models.Reservation).filter(
                models.Reservation.instrument_id == data.instrument_id,
                models.Reservation.status.in_([ReservationStatus.CONFIRMED, ReservationStatus.IN_USE]),
                models.Reservation.start_time <= data.check_in_time + grace,
                models.Reservation.end_time >= data.check_in_time - grace,
            ).first()
            if overlapping_reservation:
                return None, (
                    f"Cannot check in without reservation: instrument is reserved by user #{overlapping_reservation.user_id} "
                    f"from {overlapping_reservation.start_time} to {overlapping_reservation.end_time}"
                )

            self.anomaly_service.create_anomaly(
                schemas.AnomalyRecordCreate(
                    anomaly_type=AnomalyType.UNAUTHORIZED_USE,
                    instrument_id=data.instrument_id,
                    user_id=data.user_id,
                    description="Checked in without a valid reservation",
                    severity=3,
                )
            )

        usage = models.UsageRecord(
            reservation_id=data.reservation_id,
            instrument_id=data.instrument_id,
            user_id=data.user_id,
            check_in_time=data.check_in_time,
            notes=data.notes,
        )
        self.db.add(usage)
        self.db.flush()
        self.db.refresh(usage)

        self.audit.log(
            "usage_record",
            usage.id,
            AuditAction.CHECK_IN,
            operator_id=self.operator_id or data.user_id,
            new_value={"check_in_time": data.check_in_time.isoformat()},
        )

        return usage, None

    def check_out(
        self, usage_id: int, data: schemas.UsageRecordCheckOut
    ) -> Tuple[Optional[models.UsageRecord], Optional[str]]:
        usage = self.db.query(models.UsageRecord).filter(models.UsageRecord.id == usage_id).first()
        if not usage:
            return None, "Usage record not found"
        if usage.check_out_time is not None:
            return None, "Already checked out"

        if data.check_out_time <= usage.check_in_time:
            return None, "Check-out time must be after check-in time"

        old_data = {
            "check_in_time": usage.check_in_time.isoformat(),
            "check_out_time": None,
        }

        usage.check_out_time = data.check_out_time
        usage.actual_duration_minutes = int(
            (data.check_out_time - usage.check_in_time).total_seconds() / 60
        )
        if data.notes:
            usage.notes = (usage.notes or "") + "\n" + data.notes if usage.notes else data.notes

        self.db.flush()
        self.db.refresh(usage)

        self.audit.log(
            "usage_record",
            usage.id,
            AuditAction.CHECK_OUT,
            operator_id=self.operator_id or usage.user_id,
            old_value=old_data,
            new_value={
                "check_out_time": data.check_out_time.isoformat(),
                "actual_duration_minutes": usage.actual_duration_minutes,
            },
        )

        if usage.reservation_id:
            reservation = self.db.query(models.Reservation).filter(
                models.Reservation.id == usage.reservation_id
            ).first()
            if reservation and reservation.status == ReservationStatus.IN_USE:
                instrument = self.db.query(models.Instrument).filter(
                    models.Instrument.id == reservation.instrument_id
                ).first()
                grace = timedelta(
                    minutes=instrument.grace_period_minutes or settings.DEFAULT_GRACE_PERIOD_MINUTES
                ) if instrument else timedelta(minutes=settings.DEFAULT_GRACE_PERIOD_MINUTES)

                allowed_end = reservation.end_time + grace
                if data.check_out_time > allowed_end:
                    overtime_minutes = int((data.check_out_time - allowed_end).total_seconds() / 60)
                    self.anomaly_service.create_anomaly(
                        schemas.AnomalyRecordCreate(
                            anomaly_type=AnomalyType.OVERTIME_OCCUPANCY,
                            instrument_id=reservation.instrument_id,
                            reservation_id=reservation.id,
                            user_id=usage.user_id,
                            description=f"Checked out {overtime_minutes} minutes after scheduled end (with grace period)",
                            severity=3 if overtime_minutes > 60 else 2,
                            extra_data=f"overtime_minutes={overtime_minutes}",
                        )
                    )

                old_status = reservation.status
                reservation.status = ReservationStatus.COMPLETED
                self.audit.log_status_change(
                    "reservation", reservation.id, old_status, reservation.status,
                    operator_id=self.operator_id or usage.user_id,
                )

        return usage, None

    def detect_no_shows(self) -> int:
        now = datetime.utcnow()
        no_show_count = 0

        instruments = {i.id: i for i in self.db.query(models.Instrument).all()}

        confirmed_reservations = self.db.query(models.Reservation).filter(
            models.Reservation.status == ReservationStatus.CONFIRMED,
            models.Reservation.start_time < now,
        ).all()

        for r in confirmed_reservations:
            instrument = instruments.get(r.instrument_id)
            threshold = (
                instrument.no_show_threshold_minutes
                if instrument
                else settings.DEFAULT_NO_SHOW_THRESHOLD_MINUTES
            )
            deadline = r.start_time + timedelta(minutes=threshold)

            if now < deadline:
                continue

            active_checkin = self.db.query(models.UsageRecord).filter(
                models.UsageRecord.reservation_id == r.id,
                models.UsageRecord.check_out_time == None,
            ).first()
            if active_checkin:
                continue

            old_status = r.status
            r.status = ReservationStatus.NO_SHOW

            self.anomaly_service.create_anomaly(
                schemas.AnomalyRecordCreate(
                    anomaly_type=AnomalyType.NO_SHOW,
                    instrument_id=r.instrument_id,
                    reservation_id=r.id,
                    user_id=r.user_id,
                    description=f"No show: user did not check in within {threshold} minutes of reservation start",
                    severity=3,
                )
            )

            self.audit.log_status_change("reservation", r.id, old_status, r.status)
            no_show_count += 1

        self.db.flush()
        return no_show_count


class AnomalyService:
    def __init__(self, db: Session, operator_id: Optional[int] = None):
        self.db = db
        self.operator_id = operator_id
        self.audit = AuditLogger(db)

    def create_anomaly(self, data: schemas.AnomalyRecordCreate) -> models.AnomalyRecord:
        anomaly = models.AnomalyRecord(
            anomaly_type=data.anomaly_type,
            instrument_id=data.instrument_id,
            reservation_id=data.reservation_id,
            user_id=data.user_id,
            detected_at=datetime.utcnow(),
            description=data.description,
            severity=data.severity,
            extra_data=data.extra_data,
        )
        self.db.add(anomaly)
        self.db.flush()
        self.db.refresh(anomaly)

        self.audit.log(
            "anomaly",
            anomaly.id,
            AuditAction.ANOMALY_DETECTED,
            operator_id=self.operator_id,
            new_value={
                "type": data.anomaly_type.value,
                "description": data.description,
                "severity": data.severity,
            },
        )

        return anomaly

    def resolve_anomaly(
        self, anomaly_id: int, data: schemas.AnomalyRecordResolve
    ) -> Optional[models.AnomalyRecord]:
        anomaly = self.db.query(models.AnomalyRecord).filter(models.AnomalyRecord.id == anomaly_id).first()
        if not anomaly:
            return None
        if anomaly.is_resolved:
            return None

        anomaly.is_resolved = True
        anomaly.resolved_at = datetime.utcnow()
        anomaly.resolution_note = data.resolution_note
        anomaly.resolved_by = data.resolved_by

        self.db.flush()
        self.db.refresh(anomaly)

        self.audit.log(
            "anomaly",
            anomaly.id,
            AuditAction.ANOMALY_RESOLVED,
            operator_id=data.resolved_by,
            new_value={"resolution_note": data.resolution_note},
        )

        return anomaly


class StatsService:
    def __init__(self, db: Session):
        self.db = db

    def get_instrument_stats(
        self, instrument_id: int, start_time: datetime, end_time: datetime
    ) -> Optional[schemas.InstrumentUsageStats]:
        instrument = self.db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
        if not instrument:
            return None

        reservations = self.db.query(models.Reservation).filter(
            models.Reservation.instrument_id == instrument_id,
            models.Reservation.start_time >= start_time,
            models.Reservation.start_time <= end_time,
        ).all()

        total = len(reservations)
        completed = sum(1 for r in reservations if r.status == ReservationStatus.COMPLETED)
        cancelled = sum(1 for r in reservations if r.status == ReservationStatus.CANCELLED)
        no_shows = sum(1 for r in reservations if r.status == ReservationStatus.NO_SHOW)

        usage_records = self.db.query(models.UsageRecord).filter(
            models.UsageRecord.instrument_id == instrument_id,
            models.UsageRecord.check_in_time >= start_time,
            models.UsageRecord.check_in_time <= end_time,
            models.UsageRecord.check_out_time != None,
        ).all()
        total_usage = sum(r.actual_duration_minutes or 0 for r in usage_records)

        anomalies = self.db.query(models.AnomalyRecord).filter(
            models.AnomalyRecord.instrument_id == instrument_id,
            models.AnomalyRecord.detected_at >= start_time,
            models.AnomalyRecord.detected_at <= end_time,
        ).all()
        anomaly_count = len(anomalies)
        overtime_count = sum(1 for a in anomalies if a.anomaly_type == AnomalyType.OVERTIME_OCCUPANCY)

        total_minutes = (end_time - start_time).total_seconds() / 60
        utilization_rate = (total_usage / total_minutes * 100) if total_minutes > 0 else 0.0

        return schemas.InstrumentUsageStats(
            instrument_id=instrument_id,
            instrument_name=instrument.name,
            total_reservations=total,
            completed_reservations=completed,
            cancelled_reservations=cancelled,
            no_show_count=no_shows,
            total_usage_minutes=total_usage,
            overtime_count=overtime_count,
            anomaly_count=anomaly_count,
            utilization_rate=round(utilization_rate, 2),
        )

    def get_group_stats(
        self, group_name: str, start_time: datetime, end_time: datetime
    ) -> schemas.GroupUsageStats:
        users = self.db.query(models.User).filter(models.User.group_name == group_name).all()
        user_ids = [u.id for u in users]

        reservations = self.db.query(models.Reservation).filter(
            models.Reservation.user_id.in_(user_ids),
            models.Reservation.start_time >= start_time,
            models.Reservation.start_time <= end_time,
        ).all()

        total_reservations = len(reservations)
        no_show_count = sum(1 for r in reservations if r.status == ReservationStatus.NO_SHOW)

        usage_records = self.db.query(models.UsageRecord).filter(
            models.UsageRecord.user_id.in_(user_ids),
            models.UsageRecord.check_in_time >= start_time,
            models.UsageRecord.check_in_time <= end_time,
            models.UsageRecord.check_out_time != None,
        ).all()
        total_usage = sum(r.actual_duration_minutes or 0 for r in usage_records)

        anomalies = self.db.query(models.AnomalyRecord).filter(
            models.AnomalyRecord.user_id.in_(user_ids),
            models.AnomalyRecord.detected_at >= start_time,
            models.AnomalyRecord.detected_at <= end_time,
        ).all()
        anomaly_count = len(anomalies)
        overtime_count = sum(1 for a in anomalies if a.anomaly_type == AnomalyType.OVERTIME_OCCUPANCY)

        return schemas.GroupUsageStats(
            group_name=group_name,
            total_reservations=total_reservations,
            total_users=len(users),
            total_usage_minutes=total_usage,
            no_show_count=no_show_count,
            overtime_count=overtime_count,
            anomaly_count=anomaly_count,
        )

    def get_time_range_stats(
        self, start_time: datetime, end_time: datetime
    ) -> schemas.TimeRangeStats:
        reservations = self.db.query(models.Reservation).filter(
            models.Reservation.start_time >= start_time,
            models.Reservation.start_time <= end_time,
        ).all()

        usage_records = self.db.query(models.UsageRecord).filter(
            models.UsageRecord.check_in_time >= start_time,
            models.UsageRecord.check_in_time <= end_time,
            models.UsageRecord.check_out_time != None,
        ).all()
        total_usage = sum(r.actual_duration_minutes or 0 for r in usage_records)

        anomalies = self.db.query(models.AnomalyRecord).filter(
            models.AnomalyRecord.detected_at >= start_time,
            models.AnomalyRecord.detected_at <= end_time,
        ).all()

        instrument_counter: Dict[int, int] = defaultdict(int)
        for r in reservations:
            instrument_counter[r.instrument_id] += 1
        top_instruments = sorted(instrument_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        instruments_map = {i.id: i.name for i in self.db.query(models.Instrument).all()}
        top_instruments_list = [
            {"instrument_id": iid, "name": instruments_map.get(iid, f"#{iid}"), "count": count}
            for iid, count in top_instruments
        ]

        user_reservation_counter: Dict[int, int] = defaultdict(int)
        for r in reservations:
            user_reservation_counter[r.user_id] += 1
        users = {u.id: u for u in self.db.query(models.User).all()}
        group_counter: Dict[str, int] = defaultdict(int)
        for uid, count in user_reservation_counter.items():
            user = users.get(uid)
            if user:
                group_counter[user.group_name] += count
        top_groups = sorted(group_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        top_groups_list = [{"group_name": g, "count": c} for g, c in top_groups]

        return schemas.TimeRangeStats(
            start_time=start_time,
            end_time=end_time,
            total_reservations=len(reservations),
            total_usage_minutes=total_usage,
            anomaly_count=len(anomalies),
            top_instruments=top_instruments_list,
            top_groups=top_groups_list,
        )

    def get_reservation_trace(self, reservation_id: int) -> Optional[schemas.ReservationTrace]:
        reservation = self.db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
        if not reservation:
            return None

        usage_records = self.db.query(models.UsageRecord).filter(
            models.UsageRecord.reservation_id == reservation_id
        ).order_by(models.UsageRecord.check_in_time).all()

        anomalies = self.db.query(models.AnomalyRecord).filter(
            models.AnomalyRecord.reservation_id == reservation_id
        ).order_by(models.AnomalyRecord.detected_at).all()

        audit_logs = self.db.query(models.AuditLog).filter(
            or_(
                and_(models.AuditLog.entity_type == "reservation", models.AuditLog.entity_id == reservation_id),
                and_(models.AuditLog.entity_type == "usage_record", models.AuditLog.entity_id.in_([u.id for u in usage_records])),
                and_(models.AuditLog.entity_type == "anomaly", models.AuditLog.entity_id.in_([a.id for a in anomalies])),
            )
        ).order_by(models.AuditLog.created_at).all()

        reservation_detail = schemas.ReservationDetail.model_validate(reservation)
        reservation_detail.user = schemas.User.model_validate(
            self.db.query(models.User).filter(models.User.id == reservation.user_id).first()
        )
        reservation_detail.instrument = schemas.Instrument.model_validate(
            self.db.query(models.Instrument).filter(models.Instrument.id == reservation.instrument_id).first()
        )

        return schemas.ReservationTrace(
            reservation=reservation_detail,
            usage_records=[schemas.UsageRecord.model_validate(u) for u in usage_records],
            anomalies=[schemas.AnomalyRecord.model_validate(a) for a in anomalies],
            audit_logs=[schemas.AuditLog.model_validate(a) for a in audit_logs],
        )
