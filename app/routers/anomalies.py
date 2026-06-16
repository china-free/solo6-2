from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from datetime import datetime

from .. import models, schemas
from ..database import get_db
from ..services import AnomalyService

router = APIRouter(prefix="/anomalies", tags=["anomalies"])


@router.get("", response_model=List[schemas.AnomalyRecord])
def list_anomalies(
    instrument_id: Optional[int] = Query(None),
    anomaly_type: Optional[models.AnomalyType] = Query(None),
    is_resolved: Optional[bool] = Query(None),
    detected_from: Optional[datetime] = Query(None),
    detected_to: Optional[datetime] = Query(None),
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db),
):
    query = db.query(models.AnomalyRecord)
    if instrument_id:
        query = query.filter(models.AnomalyRecord.instrument_id == instrument_id)
    if anomaly_type:
        query = query.filter(models.AnomalyRecord.anomaly_type == anomaly_type)
    if is_resolved is not None:
        query = query.filter(models.AnomalyRecord.is_resolved == is_resolved)
    if detected_from:
        query = query.filter(models.AnomalyRecord.detected_at >= detected_from)
    if detected_to:
        query = query.filter(models.AnomalyRecord.detected_at <= detected_to)
    return query.order_by(models.AnomalyRecord.detected_at.desc()).offset(skip).limit(limit).all()


@router.post("", response_model=schemas.AnomalyRecord, status_code=201)
def create_anomaly(data: schemas.AnomalyRecordCreate, db: Session = Depends(get_db)):
    service = AnomalyService(db)
    anomaly = service.create_anomaly(data)
    db.commit()
    db.refresh(anomaly)
    return anomaly


@router.get("/{anomaly_id}", response_model=schemas.AnomalyRecord)
def get_anomaly(anomaly_id: int, db: Session = Depends(get_db)):
    anomaly = db.query(models.AnomalyRecord).filter(models.AnomalyRecord.id == anomaly_id).first()
    if not anomaly:
        raise HTTPException(status_code=404, detail="Anomaly record not found")
    return anomaly


@router.post("/{anomaly_id}/resolve", response_model=schemas.AnomalyRecord)
def resolve_anomaly(
    anomaly_id: int, data: schemas.AnomalyRecordResolve, db: Session = Depends(get_db)
):
    service = AnomalyService(db, operator_id=data.resolved_by)
    anomaly = service.resolve_anomaly(anomaly_id, data)
    if not anomaly:
        db.rollback()
        raise HTTPException(status_code=400, detail="Cannot resolve anomaly (already resolved or not found)")
    db.commit()
    db.refresh(anomaly)
    return anomaly
