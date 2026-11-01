from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models import AuditLog


def audit(db: Session, actor_id: int | None, action: str, entity: str | None = None,
          entity_id: str | int | None = None, detail: dict | None = None) -> None:
    db.add(AuditLog(actor_user_id=actor_id, action=action, entity=entity,
                    entity_id=str(entity_id) if entity_id is not None else None,
                    detail=detail, created_at=utcnow()))
