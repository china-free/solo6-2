import json
from datetime import datetime
from typing import Optional, Any

from sqlalchemy.orm import Session

from .models import AuditLog, AuditAction


class AuditLogger:
    def __init__(self, db: Session):
        self.db = db

    def log(
        self,
        entity_type: str,
        entity_id: int,
        action: AuditAction,
        operator_id: Optional[int] = None,
        old_value: Any = None,
        new_value: Any = None,
        change_reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> AuditLog:
        def _serialize(v: Any) -> Optional[str]:
            if v is None:
                return None
            if isinstance(v, (dict, list)):
                return json.dumps(v, ensure_ascii=False, default=str)
            return str(v)

        log_entry = AuditLog(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            operator_id=operator_id,
            old_value=_serialize(old_value),
            new_value=_serialize(new_value),
            change_reason=change_reason,
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.utcnow(),
        )
        self.db.add(log_entry)
        self.db.flush()
        return log_entry

    def log_create(self, entity_type: str, entity_id: int, new_value: Any, **kwargs) -> AuditLog:
        return self.log(entity_type, entity_id, AuditAction.CREATE, new_value=new_value, **kwargs)

    def log_update(
        self, entity_type: str, entity_id: int, old_value: Any, new_value: Any, **kwargs
    ) -> AuditLog:
        return self.log(
            entity_type, entity_id, AuditAction.UPDATE, old_value=old_value, new_value=new_value, **kwargs
        )

    def log_delete(self, entity_type: str, entity_id: int, old_value: Any, **kwargs) -> AuditLog:
        return self.log(entity_type, entity_id, AuditAction.DELETE, old_value=old_value, **kwargs)

    def log_status_change(
        self, entity_type: str, entity_id: int, old_status: Any, new_status: Any, **kwargs
    ) -> AuditLog:
        return self.log(
            entity_type,
            entity_id,
            AuditAction.STATUS_CHANGE,
            old_value={"status": str(old_status)},
            new_value={"status": str(new_status)},
            **kwargs,
        )
