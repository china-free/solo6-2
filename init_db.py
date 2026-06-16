"""Database initialization with seed data."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import Base, engine, SessionLocal
from app import models
from app.models import UserRole, InstrumentStatus


def init_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = models.User(
            name="系统管理员",
            email="admin@lab.edu",
            group_name="管理组",
            role=UserRole.ADMIN,
        )
        user1 = models.User(
            name="张三",
            email="zhangsan@lab.edu",
            group_name="纳米材料课题组",
            role=UserRole.USER,
        )
        user2 = models.User(
            name="李四",
            email="lisi@lab.edu",
            group_name="纳米材料课题组",
            role=UserRole.GROUP_LEADER,
        )
        user3 = models.User(
            name="王五",
            email="wangwu@lab.edu",
            group_name="生物成像课题组",
            role=UserRole.USER,
        )
        db.add_all([admin, user1, user2, user3])
        db.flush()

        instr1 = models.Instrument(
            name="高分辨透射电子显微镜",
            code="TEM-001",
            location="A栋101室",
            description="FEI Titan G2 60-300 kV",
            status=InstrumentStatus.AVAILABLE,
            max_reservation_hours=4.0,
            grace_period_minutes=15,
            no_show_threshold_minutes=30,
            requires_approval=True,
        )
        instr2 = models.Instrument(
            name="X射线衍射仪",
            code="XRD-001",
            location="A栋102室",
            description="Bruker D8 Advance",
            status=InstrumentStatus.AVAILABLE,
            max_reservation_hours=8.0,
            grace_period_minutes=10,
            no_show_threshold_minutes=20,
            requires_approval=False,
        )
        instr3 = models.Instrument(
            name="共聚焦激光扫描显微镜",
            code="CLSM-001",
            location="B栋203室",
            description="Zeiss LSM 980",
            status=InstrumentStatus.AVAILABLE,
            max_reservation_hours=6.0,
            requires_approval=True,
        )
        db.add_all([instr1, instr2, instr3])
        db.flush()

        now = datetime.utcnow()

        res1 = models.Reservation(
            instrument_id=instr2.id,
            user_id=user1.id,
            title="XRD物相分析",
            purpose="对合成样品进行晶相鉴定",
            start_time=now + timedelta(hours=2),
            end_time=now + timedelta(hours=4),
            status=models.ReservationStatus.CONFIRMED,
        )
        res2 = models.Reservation(
            instrument_id=instr1.id,
            user_id=user2.id,
            title="TEM形貌表征",
            purpose="观察纳米颗粒尺寸和分布",
            start_time=now + timedelta(days=1, hours=9),
            end_time=now + timedelta(days=1, hours=12),
            status=models.ReservationStatus.PENDING,
        )
        res3 = models.Reservation(
            instrument_id=instr3.id,
            user_id=user3.id,
            title="细胞荧光成像",
            purpose="活细胞动态观察",
            start_time=now - timedelta(hours=3),
            end_time=now - timedelta(hours=1),
            status=models.ReservationStatus.COMPLETED,
        )
        db.add_all([res1, res2, res3])
        db.flush()

        usage1 = models.UsageRecord(
            reservation_id=res3.id,
            instrument_id=instr3.id,
            user_id=user3.id,
            check_in_time=now - timedelta(hours=3, minutes=5),
            check_out_time=now - timedelta(hours=1, minutes=10),
            actual_duration_minutes=115,
            notes="细胞状态良好，成像效果理想",
        )
        db.add(usage1)

        anomaly1 = models.AnomalyRecord(
            anomaly_type=models.AnomalyType.OVERTIME_OCCUPANCY,
            instrument_id=instr3.id,
            reservation_id=res3.id,
            user_id=user3.id,
            detected_at=now - timedelta(hours=1),
            description="超时占用10分钟",
            severity=2,
            is_resolved=False,
        )
        db.add(anomaly1)

        downtime1 = models.DowntimeRecord(
            instrument_id=instr1.id,
            start_time=now + timedelta(days=7),
            end_time=now + timedelta(days=7, hours=8),
            reason="年度预防性维护",
            is_resolved=False,
        )
        db.add(downtime1)

        db.commit()
        print("Database initialized with seed data successfully!")
        print(f"  Users: {admin.name}, {user1.name}, {user2.name}, {user3.name}")
        print(f"  Instruments: {instr1.name}, {instr2.name}, {instr3.name}")
    finally:
        db.close()


if __name__ == "__main__":
    init_db()
