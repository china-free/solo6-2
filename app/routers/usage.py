from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime

from .. import models, schemas
from ..database import get_db
from ..services import UsageService

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("", response_model=List[schemas.UsageRecord])
def list_usage_records(
    instrument_id: Optional[int] = Query(None),
    user_id: Optional[int] = Query(None),
    reservation_id: Optional[int] = Query(None),
    active_only: bool = Query(False),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.UsageRecord)
    if instrument_id:
        query = query.filter(models.UsageRecord.instrument_id == instrument_id)
    if user_id:
        query = query.filter(models.UsageRecord.user_id == user_id)
    if reservation_id:
        query = query.filter(models.UsageRecord.reservation_id == reservation_id)
    if active_only:
        query = query.filter(models.UsageRecord.check_out_time == None)
    return query.order_by(models.UsageRecord.check_in_time.desc()).offset(skip).limit(limit).all()


@router.post("/check-in", response_model=schemas.UsageRecord, status_code=201)
def check_in(data: schemas.UsageRecordCreate, db: Session = Depends(get_db)):
    service = UsageService(db, operator_id=data.user_id)
    usage, error = service.check_in(data)
    if error:
        db.rollback()
        raise HTTPException(status_code=400, detail=error)
    db.commit()
    db.refresh(usage)
    return usage


@router.post("/{usage_id}/check-out", response_model=schemas.UsageRecord)
def check_out(usage_id: int, data: schemas.UsageRecordCheckOut, db: Session = Depends(get_db)):
    existing = db.query(models.UsageRecord).filter(models.UsageRecord.id == usage_id).first()
    if not existing:
        raise HTTPException(status_code=404, detail="Usage record not found")
    service = UsageService(db, operator_id=existing.user_id)
    usage, error = service.check_out(usage_id, data)
    if error:
        db.rollback()
        raise HTTPException(status_code=400, detail=error)
    db.commit()
    db.refresh(usage)
    return usage


@router.post("/detect-no-shows", response_model=dict)
def detect_no_shows(db: Session = Depends(get_db)):
    service = UsageService(db)
    count = service.detect_no_shows()
    db.commit()
    return {"no_show_count": count}
