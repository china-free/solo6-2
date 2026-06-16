"""Comprehensive test suite for the lab reservation system."""
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import Base, engine, SessionLocal
from app import models, schemas
from app.services import ReservationService, UsageService, AnomalyService, StatsService
from app.models import (
    ReservationStatus,
    InstrumentStatus,
    AnomalyType,
    UserRole,
)


class TestBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Base.metadata.create_all(bind=engine)

    def setUp(self):
        self.db = SessionLocal()
        self._seed_data()

    def tearDown(self):
        self.db.rollback()
        self.db.close()

    def _seed_data(self):
        self.user1 = models.User(
            name="测试用户1", email="test1@lab.edu", group_name="测试组", role=UserRole.USER
        )
        self.user2 = models.User(
            name="测试用户2", email="test2@lab.edu", group_name="测试组", role=UserRole.USER
        )
        self.admin = models.User(
            name="管理员", email="admin@lab.edu", group_name="管理组", role=UserRole.ADMIN
        )
        self.db.add_all([self.user1, self.user2, self.admin])
        self.db.flush()

        self.instr = models.Instrument(
            name="测试仪器",
            code="TEST-001",
            status=InstrumentStatus.AVAILABLE,
            max_reservation_hours=4.0,
            grace_period_minutes=15,
            no_show_threshold_minutes=30,
            requires_approval=False,
        )
        self.instr_approval = models.Instrument(
            name="需要审批的仪器",
            code="TEST-002",
            status=InstrumentStatus.AVAILABLE,
            requires_approval=True,
        )
        self.db.add_all([self.instr, self.instr_approval])
        self.db.flush()


class TestReservationConflict(TestBase):
    def test_no_conflict_for_new_reservation(self):
        service = ReservationService(self.db)
        now = datetime.utcnow()
        result = service.check_conflicts(
            self.instr.id, now + timedelta(hours=1), now + timedelta(hours=2)
        )
        self.assertFalse(result.has_conflict)

    def test_conflict_detection(self):
        now = datetime.utcnow()
        service = ReservationService(self.db, operator_id=self.user1.id)

        res, err = service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="预约1",
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=3),
            )
        )
        self.assertIsNone(err)
        self.assertIsNotNone(res)

        result = service.check_conflicts(
            self.instr.id, now + timedelta(hours=2), now + timedelta(hours=4)
        )
        self.assertTrue(result.has_conflict)
        self.assertGreater(len(result.conflicting_reservations), 0)

    def test_exceeds_max_duration(self):
        service = ReservationService(self.db)
        now = datetime.utcnow()
        result = service.check_conflicts(
            self.instr.id, now, now + timedelta(hours=10)
        )
        self.assertTrue(result.has_conflict)
        self.assertIn("exceeds maximum", result.conflict_reason)

    def test_downtime_conflict(self):
        now = datetime.utcnow()
        downtime = models.DowntimeRecord(
            instrument_id=self.instr.id,
            start_time=now + timedelta(hours=5),
            end_time=now + timedelta(hours=8),
            reason="维护",
            is_resolved=False,
        )
        self.db.add(downtime)
        self.db.flush()

        service = ReservationService(self.db)
        result = service.check_conflicts(
            self.instr.id, now + timedelta(hours=6), now + timedelta(hours=7)
        )
        self.assertTrue(result.has_conflict)
        self.assertIn("downtime", result.conflict_reason)

    def test_unavailable_instrument(self):
        self.instr.status = InstrumentStatus.OUT_OF_SERVICE
        self.db.flush()

        service = ReservationService(self.db)
        now = datetime.utcnow()
        result = service.check_conflicts(
            self.instr.id, now + timedelta(hours=1), now + timedelta(hours=2)
        )
        self.assertTrue(result.has_conflict)


class TestReservationFlow(TestBase):
    def test_create_reservation_no_approval(self):
        now = datetime.utcnow()
        service = ReservationService(self.db, operator_id=self.user1.id)
        res, err = service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="测试预约",
                purpose="测试用途",
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
            )
        )
        self.assertIsNone(err)
        self.assertEqual(res.status, ReservationStatus.CONFIRMED)

    def test_create_reservation_requires_approval(self):
        now = datetime.utcnow()
        service = ReservationService(self.db, operator_id=self.user1.id)
        res, err = service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr_approval.id,
                user_id=self.user1.id,
                title="需审批预约",
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
            )
        )
        self.assertIsNone(err)
        self.assertEqual(res.status, ReservationStatus.PENDING)

    def test_approve_reservation(self):
        now = datetime.utcnow()
        service = ReservationService(self.db, operator_id=self.user1.id)
        res, _ = service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr_approval.id,
                user_id=self.user1.id,
                title="待审批",
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
            )
        )

        approved = service.approve_reservation(res.id, self.admin.id)
        self.assertIsNotNone(approved)
        self.assertEqual(approved.status, ReservationStatus.CONFIRMED)
        self.assertEqual(approved.approved_by, self.admin.id)

    def test_cancel_reservation(self):
        now = datetime.utcnow()
        service = ReservationService(self.db, operator_id=self.user1.id)
        res, _ = service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="将被取消",
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
            )
        )

        cancelled = service.cancel_reservation(res.id, self.user1.id, reason="计划变更")
        self.assertIsNotNone(cancelled)
        self.assertEqual(cancelled.status, ReservationStatus.CANCELLED)

    def test_auto_expire(self):
        now = datetime.utcnow()
        service = ReservationService(self.db, operator_id=self.user1.id)
        res, _ = service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="过期预约",
                start_time=now - timedelta(hours=5),
                end_time=now - timedelta(hours=3),
            )
        )

        count = service.auto_expire_stale_reservations()
        self.assertGreaterEqual(count, 1)
        self.db.refresh(res)
        self.assertEqual(res.status, ReservationStatus.EXPIRED)


class TestUsageFlow(TestBase):
    def test_check_in_check_out(self):
        now = datetime.utcnow()
        res_service = ReservationService(self.db, operator_id=self.user1.id)
        res, _ = res_service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="使用预约",
                start_time=now + timedelta(minutes=5),
                end_time=now + timedelta(hours=2),
            )
        )

        usage_service = UsageService(self.db, operator_id=self.user1.id)
        usage, err = usage_service.check_in(
            schemas.UsageRecordCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                reservation_id=res.id,
                check_in_time=now + timedelta(minutes=10),
            )
        )
        self.assertIsNone(err)
        self.assertIsNotNone(usage)
        self.db.refresh(res)
        self.assertEqual(res.status, ReservationStatus.IN_USE)

        usage_out, err = usage_service.check_out(
            usage.id,
            schemas.UsageRecordCheckOut(check_out_time=now + timedelta(hours=1, minutes=50)),
        )
        self.assertIsNone(err)
        self.assertIsNotNone(usage_out)
        self.assertEqual(usage_out.actual_duration_minutes, 100)
        self.db.refresh(res)
        self.assertEqual(res.status, ReservationStatus.COMPLETED)

    def test_overtime_detection(self):
        now = datetime.utcnow()
        res_service = ReservationService(self.db, operator_id=self.user1.id)
        res, _ = res_service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="超时测试",
                start_time=now,
                end_time=now + timedelta(hours=1),
            )
        )

        usage_service = UsageService(self.db, operator_id=self.user1.id)
        usage, _ = usage_service.check_in(
            schemas.UsageRecordCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                reservation_id=res.id,
                check_in_time=now,
            )
        )
        usage_service.check_out(
            usage.id,
            schemas.UsageRecordCheckOut(check_out_time=now + timedelta(hours=1, minutes=45)),
        )

        anomalies = (
            self.db.query(models.AnomalyRecord)
            .filter(models.AnomalyRecord.anomaly_type == AnomalyType.OVERTIME_OCCUPANCY)
            .all()
        )
        self.assertGreater(len(anomalies), 0)

    def test_no_show_detection(self):
        now = datetime.utcnow()
        res_service = ReservationService(self.db, operator_id=self.user1.id)
        res, _ = res_service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="爽约测试",
                start_time=now - timedelta(hours=2),
                end_time=now - timedelta(hours=1),
            )
        )
        res.status = ReservationStatus.CONFIRMED
        self.db.flush()

        usage_service = UsageService(self.db)
        count = usage_service.detect_no_shows()
        self.assertGreaterEqual(count, 1)
        self.db.refresh(res)
        self.assertEqual(res.status, ReservationStatus.NO_SHOW)

    def test_double_checkin_prevented(self):
        now = datetime.utcnow()
        usage_service = UsageService(self.db, operator_id=self.user1.id)
        usage_service.check_in(
            schemas.UsageRecordCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                check_in_time=now,
            )
        )

        _, err = usage_service.check_in(
            schemas.UsageRecordCreate(
                instrument_id=self.instr.id,
                user_id=self.user2.id,
                check_in_time=now + timedelta(minutes=30),
            )
        )
        self.assertIsNotNone(err)
        self.assertIn("currently in use", err)


class TestAnomalyService(TestBase):
    def test_create_and_resolve_anomaly(self):
        service = AnomalyService(self.db, operator_id=self.admin.id)
        anomaly = service.create_anomaly(
            schemas.AnomalyRecordCreate(
                anomaly_type=AnomalyType.EQUIPMENT_FAULT,
                instrument_id=self.instr.id,
                description="仪器报警",
                severity=3,
            )
        )
        self.assertIsNotNone(anomaly)
        self.assertFalse(anomaly.is_resolved)

        resolved = service.resolve_anomaly(
            anomaly.id,
            schemas.AnomalyRecordResolve(
                resolution_note="已修复", resolved_by=self.admin.id
            ),
        )
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.is_resolved)


class TestStatsService(TestBase):
    def test_instrument_stats(self):
        now = datetime.utcnow()
        start = now - timedelta(days=1)
        end = now + timedelta(days=1)

        res_service = ReservationService(self.db, operator_id=self.user1.id)
        res_service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="统计测试",
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
            )
        )

        service = StatsService(self.db)
        stats = service.get_instrument_stats(self.instr.id, start, end)
        self.assertIsNotNone(stats)
        self.assertGreaterEqual(stats.total_reservations, 1)

    def test_group_stats(self):
        now = datetime.utcnow()
        start = now - timedelta(days=1)
        end = now + timedelta(days=1)

        res_service = ReservationService(self.db, operator_id=self.user1.id)
        res_service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="组统计",
                start_time=now + timedelta(hours=1),
                end_time=now + timedelta(hours=2),
            )
        )

        service = StatsService(self.db)
        stats = service.get_group_stats("测试组", start, end)
        self.assertEqual(stats.group_name, "测试组")
        self.assertGreaterEqual(stats.total_reservations, 1)
        self.assertGreaterEqual(stats.total_users, 2)

    def test_reservation_trace(self):
        now = datetime.utcnow()
        res_service = ReservationService(self.db, operator_id=self.user1.id)
        res, _ = res_service.create_reservation(
            schemas.ReservationCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                title="追溯测试",
                start_time=now + timedelta(minutes=10),
                end_time=now + timedelta(hours=1),
            )
        )

        usage_service = UsageService(self.db, operator_id=self.user1.id)
        usage, _ = usage_service.check_in(
            schemas.UsageRecordCreate(
                instrument_id=self.instr.id,
                user_id=self.user1.id,
                reservation_id=res.id,
                check_in_time=now + timedelta(minutes=15),
            )
        )
        usage_service.check_out(
            usage.id,
            schemas.UsageRecordCheckOut(check_out_time=now + timedelta(minutes=50)),
        )

        service = StatsService(self.db)
        trace = service.get_reservation_trace(res.id)
        self.assertIsNotNone(trace)
        self.assertEqual(trace.reservation.id, res.id)
        self.assertGreater(len(trace.usage_records), 0)
        self.assertGreater(len(trace.audit_logs), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
