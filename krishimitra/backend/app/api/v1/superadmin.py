"""Super admin: roles and permissions, districts, franchises, delivery areas, platform settings, broadcasts."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field as F
from sqlalchemy import delete, func, insert, select
from sqlalchemy.orm import Session

from app.api.deps import district_scope, require, require_any
from app.core.audit import audit
from app.db.base import utcnow
from app.db.session import get_db
from app.models import (District, Franchise, InventoryLocation, Permission, PlatformSetting, Role, RoleName, ServiceablePincode, User, UserStatus,
                        role_permissions)
from app.permissions.rbac import PERMISSIONS
from app.services.notify import notify

router = APIRouter(prefix="/superadmin", tags=["superadmin"])
Sup = Depends(require("superadmin.manage"))


# ---------------- roles & permissions ----------------
@router.get("/roles")
def roles(user: User = Sup, db: Session = Depends(get_db)):
    return {"permissions": PERMISSIONS, "roles": [{"name": r.name.value, "permissions": sorted(p.code for p in r.permissions)} for r in db.scalars(select(Role).order_by(Role.id))]}


class RolePerms(BaseModel):
    permissions: list[str]


@router.put("/roles/{name}")
def set_role_permissions(name: RoleName, body: RolePerms, user: User = Sup, db: Session = Depends(get_db)):
    if name == RoleName.SUPER_ADMIN:
        raise HTTPException(409, "The super admin role always has every permission")
    unknown = [c for c in body.permissions if c not in PERMISSIONS]
    if unknown:
        raise HTTPException(422, f"Unknown permissions: {unknown}")
    role = db.scalar(select(Role).where(Role.name == name))
    ids = dict(db.execute(select(Permission.code, Permission.id).where(Permission.code.in_(body.permissions))).all())
    db.execute(delete(role_permissions).where(role_permissions.c.role_id == role.id))
    if ids:
        db.execute(insert(role_permissions), [{"role_id": role.id, "permission_id": i} for i in ids.values()])
    audit(db, user.id, "role.permissions", "role", name.value, {"permissions": sorted(body.permissions)})
    db.commit()
    return {"ok": True, "note": "Users of this role pick up the change on their next request"}


# ---------------- districts & franchises ----------------
class DistrictIn(BaseModel):
    name: str = F(min_length=2, max_length=120)
    state: str = F(min_length=2, max_length=80)
    code: str = F(pattern=r"^[A-Z0-9_-]{2,20}$")
    status: str = F(default="PLANNED", pattern="^(PLANNED|ACTIVE|PAUSED)$")
    target_launch: str | None = None
    franchise_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None


def d_out(d: District) -> dict:
    return {c: getattr(d, c) for c in ("id", "name", "state", "code", "status", "target_launch", "franchise_id", "latitude", "longitude")}


@router.get("/districts")
def districts(user: User = Depends(require_any("superadmin.manage", "users.manage", "district.manage")), db: Session = Depends(get_db)):
    q = select(District).order_by(District.state, District.name)
    sc = district_scope(user)
    if sc:
        q = q.where(District.id == sc)
    return [d_out(d) for d in db.scalars(q)]


@router.post("/districts", status_code=201)
def add_district(body: DistrictIn, user: User = Sup, db: Session = Depends(get_db)):
    if db.scalar(select(District.id).where(District.code == body.code)) or db.scalar(select(District.id).where(District.name == body.name, District.state == body.state)):
        raise HTTPException(409, "District already exists")
    d = District(**body.model_dump())
    db.add(d)
    audit(db, user.id, "district.create", "district", body.code)
    db.commit()
    return d_out(d)


@router.put("/districts/{did}")
def edit_district(did: int, body: DistrictIn, user: User = Sup, db: Session = Depends(get_db)):
    d = db.get(District, did)
    if not d:
        raise HTTPException(404, "District not found")
    for k, v in body.model_dump().items():
        setattr(d, k, v)
    audit(db, user.id, "district.update", "district", did, {"status": body.status})
    db.commit()
    return d_out(d)


class FranchiseIn(BaseModel):
    name: str = F(min_length=2, max_length=160)
    owner_name: str = F(min_length=2, max_length=160)
    contact: str | None = None
    status: str = "ACTIVE"
    terms_note: str | None = F(default=None, max_length=500)


@router.get("/franchises")
def franchises(user: User = Sup, db: Session = Depends(get_db)):
    return [{"id": f.id, "name": f.name, "owner_name": f.owner_name, "contact": f.contact, "status": f.status, "terms_note": f.terms_note,
             "districts": [d.name for d in db.scalars(select(District).where(District.franchise_id == f.id))]} for f in db.scalars(select(Franchise))]


@router.post("/franchises", status_code=201)
def add_franchise(body: FranchiseIn, user: User = Sup, db: Session = Depends(get_db)):
    if db.scalar(select(Franchise.id).where(Franchise.name == body.name)):
        raise HTTPException(409, "Franchise exists")
    f = Franchise(**body.model_dump())
    db.add(f)
    audit(db, user.id, "franchise.create", "franchise", body.name)
    db.commit()
    return {"id": f.id}


# ---------------- delivery areas (admin or super admin) ----------------
class PinIn(BaseModel):
    pincode: str = F(pattern=r"^\d{6}$")
    district_id: int | None = None
    delivery_fee_paise: int = F(default=0, ge=0, le=100000)
    is_active: bool = True


@router.get("/delivery-areas")
def delivery_areas(user: User = Depends(require_any("delivery.manage", "district.manage")), db: Session = Depends(get_db)):
    q = select(ServiceablePincode).order_by(ServiceablePincode.pincode).limit(1000)
    sc = district_scope(user)
    if sc:
        q = q.where(ServiceablePincode.district_id == sc)
    return [{"id": p.id, "pincode": p.pincode, "district_id": p.district_id, "delivery_fee_paise": p.delivery_fee_paise, "is_active": p.is_active} for p in db.scalars(q)]


@router.put("/delivery-areas")
def set_delivery_area(body: PinIn, user: User = Depends(require_any("delivery.manage", "district.manage")), db: Session = Depends(get_db)):
    sc = district_scope(user)
    if sc and body.district_id != sc:
        raise HTTPException(403, "You can only manage your own district")
    loc = db.scalar(select(InventoryLocation).where(InventoryLocation.supplier_id.is_(None)).order_by(InventoryLocation.id))
    if not loc:
        raise HTTPException(503, "No warehouse configured")
    p = db.scalar(select(ServiceablePincode).where(ServiceablePincode.pincode == body.pincode, ServiceablePincode.location_id == loc.id))
    if not p:
        p = ServiceablePincode(pincode=body.pincode, location_id=loc.id)
        db.add(p)
    p.district_id, p.delivery_fee_paise, p.is_active = body.district_id, body.delivery_fee_paise, body.is_active
    audit(db, user.id, "delivery_area.set", "pincode", body.pincode)
    db.commit()
    return {"ok": True}


# ---------------- platform settings ----------------
@router.get("/settings")
def settings(user: User = Sup, db: Session = Depends(get_db)):
    return [{"key": s.key, "value": s.value, "description": s.description} for s in db.scalars(select(PlatformSetting).order_by(PlatformSetting.key))]


class SettingIn(BaseModel):
    value: dict | list | str | int | float | bool | None
    description: str | None = F(default=None, max_length=200)


@router.put("/settings/{key}")
def put_setting(key: str, body: SettingIn, user: User = Sup, db: Session = Depends(get_db)):
    if not key.replace("_", "").replace(".", "").isalnum() or len(key) > 80:
        raise HTTPException(422, "Invalid key")
    s = db.get(PlatformSetting, key) or PlatformSetting(key=key)
    s.value, s.updated_by, s.updated_at = {"v": body.value}, user.id, utcnow()
    if body.description is not None:
        s.description = body.description
    db.add(s)
    audit(db, user.id, "setting.update", "setting", key)
    db.commit()
    return {"ok": True}


# ---------------- broadcast ----------------
class BroadcastIn(BaseModel):
    title: str = F(min_length=3, max_length=160)
    body: str = F(max_length=500)
    roles: list[RoleName] | None = None
    district_id: int | None = None


@router.post("/broadcast")
def broadcast(body: BroadcastIn, user: User = Sup, db: Session = Depends(get_db)):
    """In-app announcement. Sent in chunks so one request never holds a huge transaction."""
    q = select(User.id).where(User.status == UserStatus.ACTIVE)
    if body.roles:
        q = q.join(Role, Role.id == User.role_id).where(Role.name.in_(body.roles))
    if body.district_id:
        q = q.where(User.district_id == body.district_id)
    ids = db.scalars(q.limit(20000)).all()
    for i, uid in enumerate(ids, 1):
        notify(db, uid, "SYSTEM", body.title, body.body)
        if i % 500 == 0:
            db.flush()
    audit(db, user.id, "broadcast", None, None, {"title": body.title, "recipients": len(ids)})
    db.commit()
    return {"recipients": len(ids)}


@router.get("/overview")
def overview(user: User = Sup, db: Session = Depends(get_db)):
    by_role = dict(db.execute(select(Role.name, func.count(User.id)).join(User, User.role_id == Role.id).group_by(Role.name)).all())
    by_status = dict(db.execute(select(User.status, func.count(User.id)).group_by(User.status)).all())
    return {"users_by_role": {k.value: v for k, v in by_role.items()}, "users_by_status": {k.value: v for k, v in by_status.items()},
            "districts": db.scalar(select(func.count(District.id))), "active_districts": db.scalar(select(func.count(District.id)).where(District.status == "ACTIVE"))}
