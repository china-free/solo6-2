from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime

from .. import models, schemas
from ..database import get_db
from ..services import ReservationService, ACTIVE_STATUSES

router = APIRouter(prefix="/reservations", tags=["reservations"])


@router.get("", response_model=List[schemas.Reservation])
def list_reservations(
    instrument_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    status: Optional[models.ReservationStatus] = Query(None),
    start_from: Optional[datetime] = Query(None),
    start_to: Optional[datetime] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.Reservation)
    if instrument_id:
        query = query.filter(models.Reservation.instrument_id == instrument_id)
    if user_id:
        query = query.filter(models.Reservation.user_id == user_id)
    if status:
        query = query.filter(models.Reservation.status == status)
    if start_from:
        query = query.filter(models.Reservation.start_time >= start_from)
    if start_to:
        query = query.filter(models.Reservation.start_time <= start_to)
    return query.order_by(models.Reservation.start_time.desc()).offset(skip).limit(limit).all()


@router.get("/conflicts", response_model=schemas.ReservationConflictInfo)
def check_reservation_conflicts(
    instrument_id: int,
    start_time: datetime,
    end_time: datetime,
    exclude_reservation_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    service = ReservationService(db)
    return service.check_conflicts(instrument_id, start_time, end_time, exclude_reservation_id)


@router.post("", response_model=schemas.Reservation, status_code=201)
def create_reservation(data: schemas.ReservationCreate, db: Session = Depends(get_db)):
    service = ReservationService(db, operator_id=data.user_id)
    reservation, conflict = service.create_reservation(data)
    if conflict:
        db.rollback()
        raise HTTPException(status_code=409, detail=conflict.model_dump())
    db.commit()
    db.refresh(reservation)
    return reservation


@router.get("/{reservation_id}", response_model=schemas.ReservationDetail)
def get_reservation(reservation_id: int, db: Session = Depends(get_db)):
    reservation = db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    detail = schemas.ReservationDetail.model_validate(reservation)
    detail.user = schemas.User.model_validate(
        db.query(models.User).filter(models.User.id == reservation.user_id).first()
    )
    detail.instrument = schemas.Instrument.model_validate(
        db.query(models.Instrument).filter(models.Instrument.id == reservation.instrument_id).first()
    )
    return detail


@router.put("/{reservation_id}", response_model=schemas.Reservation)
def update_reservation(
    reservation_id: int, data: schemas.ReservationUpdate, db: Session = Depends(get_db)
):
    existing = db.query(models.Reservation).filter(models.Reservation.id == reservation_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Reservation not found")
    service = ReservationService(db, operator_id=existing.user_id)
    reservation, error = service.update_reservation(reservation_id, data)
    if error:
        db.rollback()
        raise HTTPException(status_code=400, detail=error)
    db.commit()
    db.refresh(reservation)
    return reservation


@router.post("/{reservation_id}/approve", response_model=schemas.Reservation)
def approve_reservation(
    reservation_id: int,
    approver_id: int,
    db: Session = Depends(get_db),
):
    service = ReservationService(db, operator_id=approver_id)
    reservation = service.approve_reservation(reservation_id, approver_id)
    if not reservation:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot approve reservation")
    db.commit()
    db.refresh(reservation)
    return reservation


@router.post("/{reservation_id}/reject", response_model=schemas.Reservation)
def reject_reservation(
    reservation_id: int,
    rejecter_id: int,
    reason: str,
    db: Session = Depends(get_db),
):
    service = ReservationService(db, operator_id=rejecter_id)
    reservation = service.reject_reservation(reservation_id, rejecter_id, reason)
    if not reservation:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot reject reservation")
    db.commit()
    db.refresh(reservation)
    return reservation


@router.post("/{reservation_id}/cancel", response_model=schemas.Reservation)
def cancel_reservation(
    reservation_id: int,
    canceller_id: int,
    reason: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    service = ReservationService(db, operator_id=canceller_id)
    reservation = service.cancel_reservation(reservation_id, canceller_id, reason)
    if not reservation:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot cancel reservation")
    db.commit()
    db.refresh(reservation)
    return reservation


@router.post("/auto-expire", response_model=dict)
def auto_expire_reservations(db: Session = Depends(get_db)):
    service = ReservationService(db)
    count = service.auto_expire_stale_reservations()
    db.commit()
    return {"expired_count": count}
