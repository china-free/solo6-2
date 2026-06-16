from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/audit-logs", tags=["audit"])


@router.get("", response_model=List[schemas.AuditLog])
def list_audit_logs(
    entity_type: Optional[str] = Query(None),
    entity_id: Optional[int] = Query(None),
    action: Optional[models.AuditAction] = Query(None),
    operator_id: Optional[int] = Query(None),
    created_from: Optional[datetime] = Query(None),
    created_to: Optional[datetime] = Query(None),
    skip: int = 0,
    limit: int = 200,
    db: Session = Depends(get_db),
):
    query = db.query(models.AuditLog)
    if entity_type:
        query = query.filter(models.AuditLog.entity_type == entity_type)
    if entity_id:
        query = query.filter(models.AuditLog.entity_id == entity_id)
    if action:
        query = query.filter(models.AuditLog.action == action)
    if operator_id:
        query = query.filter(models.AuditLog.operator_id == operator_id)
    if created_from:
        query = query.filter(models.AuditLog.created_at >= created_from)
    if created_to:
        query = query.filter(models.AuditLog.created_at <= created_to)
    return query.order_by(models.AuditLog.created_at.desc()).offset(skip).limit(limit).all()
