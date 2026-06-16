from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime

from .. import schemas
from ..database import get_db
from ..services import StatsService

router = APIRouter(prefix="/stats", tags=["statistics"])


@router.get("/instruments/{instrument_id}", response_model=schemas.InstrumentUsageStats)
def get_instrument_stats(
    instrument_id: int,
    start_time: datetime,
    end_time: datetime,
    db: Session = Depends(get_db),
):
    service = StatsService(db)
    stats = service.get_instrument_stats(instrument_id, start_time, end_time)
    if not stats:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return stats


@router.get("/groups/{group_name}", response_model=schemas.GroupUsageStats)
def get_group_stats(
    group_name: str,
    start_time: datetime,
    end_time: datetime,
    db: Session = Depends(get_db),
):
    service = StatsService(db)
    return service.get_group_stats(group_name, start_time, end_time)


@router.get("/time-range", response_model=schemas.TimeRangeStats)
def get_time_range_stats(
    start_time: datetime,
    end_time: datetime,
    db: Session = Depends(get_db),
):
    service = StatsService(db)
    return service.get_time_range_stats(start_time, end_time)


@router.get("/reservations/{reservation_id}/trace", response_model=schemas.ReservationTrace)
def get_reservation_trace(
    reservation_id: int,
    db: Session = Depends(get_db),
):
    service = StatsService(db)
    trace = service.get_reservation_trace(reservation_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Reservation not found")
    return trace
