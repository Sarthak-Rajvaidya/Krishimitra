from fastapi import Cookie, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.audit import audit
from app.core.security import decode_token
from app.db.base import as_utc, utcnow
from app.db.session import get_db
from app.models import RoleName, User, UserSession, UserStatus

SAFE = {"GET", "HEAD", "OPTIONS"}


def get_current_user(request: Request, db: Session = Depends(get_db),
                     ks_token: str | None = Cookie(default=None),
                     authorization: str | None = Header(default=None),
                     x_km_client: str | None = Header(default=None)) -> User:
    token, from_cookie = None, False
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:]
    elif ks_token:
        token, from_cookie = ks_token, True
    parsed = decode_token(token) if token else None
    if not parsed:
        raise HTTPException(401, "Not authenticated")
    if from_cookie and request.method not in SAFE and x_km_client != "web":
        raise HTTPException(403, "Missing client header")      # CSRF defence for cookie sessions
    uid, sid = parsed
    sess = db.get(UserSession, sid)
    if not sess or sess.revoked or sess.user_id != uid or as_utc(sess.expires_at) < utcnow():
        raise HTTPException(401, "Session expired")
    user = db.get(User, uid)
    if not user or user.status not in (UserStatus.ACTIVE, UserStatus.PENDING_APPROVAL):
        raise HTTPException(401, "Account not available")
    request.state.session_id = sid
    return user


def user_permissions(user: User) -> set[str]:
    if user.status != UserStatus.ACTIVE:       # awaiting approval: sign-in works, features don't
        return set()
    return {p.code for p in user.role.permissions}


def require(*codes: str):
    """Require ALL listed permissions. Roles come from the DB, never from the client."""
    def dep(user: User = Depends(get_current_user)) -> User:
        have = user_permissions(user)
        if not all(c in have for c in codes):
            raise HTTPException(403, "Forbidden")
        return user
    return dep


def require_any(*codes: str):
    def dep(user: User = Depends(get_current_user)) -> User:
        have = user_permissions(user)
        if not any(c in have for c in codes):
            raise HTTPException(403, "Forbidden")
        return user
    return dep


def require_sensitive(code: str, action: str):
    """Permission check that also writes an audit record (for sensitive executive/finance reads)."""
    def dep(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> User:
        if code not in user_permissions(user):
            raise HTTPException(403, "Forbidden")
        audit(db, user.id, action)
        db.commit()
        return user
    return dep


def is_global_staff(user: User) -> bool:
    return user.role.name in (RoleName.ADMIN, RoleName.SUPER_ADMIN)


def district_scope(user: User) -> int | None:
    """District managers only ever see their own district; global staff see everything (None = no restriction)."""
    if user.role.name == RoleName.DISTRICT_MANAGER:
        if not user.district_id:
            raise HTTPException(403, "No district assigned to this manager")
        return user.district_id
    return None
