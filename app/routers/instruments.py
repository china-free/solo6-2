from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..audit import AuditLogger
from ..models import AuditAction

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=List[schemas.Instrument])
def list_instruments(
    status: Optional[models.InstrumentStatus] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.Instrument)
    if status:
        query = query.filter(models.Instrument.status == status)
    return query.offset(skip).limit(limit).all()


@router.post("", response_model=schemas.Instrument, status_code=201)
def create_instrument(data: schemas.InstrumentCreate, db: Session = Depends(get_db)):
    existing = db.query(models.Instrument).filter(models.Instrument.code == data.code).first()
    if existing:
        raise HTTPException(status_code=400, detail="Instrument code already exists")
    instrument = models.Instrument(**data.model_dump())
    db.add(instrument)
    db.flush()
    AuditLogger(db).log_create("instrument", instrument.id, data.model_dump())
    db.commit()
    db.refresh(instrument)
    return instrument


@router.get("/{instrument_id}", response_model=schemas.Instrument)
def get_instrument(instrument_id: int, db: Session = Depends(get_db)):
    instrument = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    return instrument


@router.put("/{instrument_id}", response_model=schemas.Instrument)
def update_instrument(
    instrument_id: int, data: schemas.InstrumentUpdate, db: Session = Depends(get_db)
):
    instrument = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    old_data = schemas.Instrument.model_validate(instrument).model_dump()
    update_data = data.model_dump(exclude_unset=True)
    old_status = instrument.status
    for key, value in update_data.items():
        setattr(instrument, key, value)
    db.flush()
    audit = AuditLogger(db)
    audit.log_update("instrument", instrument.id, old_data, schemas.Instrument.model_validate(instrument).model_dump())
    if "status" in update_data and old_status != instrument.status:
        audit.log_status_change("instrument", instrument.id, old_status, instrument.status)
    db.commit()
    db.refresh(instrument)
    return instrument


@router.get("/{instrument_id}/downtimes", response_model=List[schemas.DowntimeRecord])
def list_downtimes(instrument_id: int, db: Session = Depends(get_db)):
    return (
        db.query(models.DowntimeRecord)
        .filter(models.DowntimeRecord.instrument_id == instrument_id)
        .order_by(models.DowntimeRecord.start_time.desc())
        .all()
    )


@router.post("/{instrument_id}/downtimes", response_model=schemas.DowntimeRecord, status_code=201)
def create_downtime(
    instrument_id: int, data: schemas.DowntimeRecordCreate, db: Session = Depends(get_db)
):
    instrument = db.query(models.Instrument).filter(models.Instrument.id == instrument_id).first()
    if not instrument:
        raise HTTPException(status_code=404, detail="Instrument not found")
    if data.end_time <= data.start_time:
        raise HTTPException(status_code=400, detail="End time must be after start time")
    downtime = models.DowntimeRecord(**data.model_dump())
    db.add(downtime)
    db.flush()
    AuditLogger(db).log_create("downtime", downtime.id, data.model_dump())
    db.commit()
    db.refresh(downtime)
    return downtime
