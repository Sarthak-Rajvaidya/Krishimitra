"""Community: groups, posts (questions / experiences / success stories), comments, likes, reports, moderation."""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field as F
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require
from app.api.v1.common import page_args
from app.core.audit import audit
from app.core.ratelimit import rate_limit
from app.db.session import get_db
from app.models import Comment, CommunityGroup, ContentReport, GroupMember, Post, PostLike, User
from app.services.notify import notify

router = APIRouter(prefix="/community", tags=["community"])
Member = Depends(require("community.use"))
Mod = Depends(require("moderation.manage"))
KINDS = "^(POST|QUESTION|EXPERIENCE|SUCCESS_STORY)$"


def _author(u: User) -> dict:
    public = (u.privacy or {}).get("community_profile_public", True)
    return {"id": u.id, "name": u.full_name if public else u.full_name.split()[0], "role": u.role.name.value}


def post_out(p: Post, u: User, liked: bool = False) -> dict:
    return {"id": p.id, "kind": p.kind, "title": p.title, "body": p.body, "topic": p.topic, "group_id": p.group_id, "likes": p.like_count,
            "comments": p.comment_count, "liked": liked, "author": _author(u), "at": p.created_at.isoformat(), "media": p.media_keys or []}


@router.get("/groups")
def groups(user: User = Member, db: Session = Depends(get_db)):
    mine = set(db.scalars(select(GroupMember.group_id).where(GroupMember.user_id == user.id)))
    n = dict(db.execute(select(GroupMember.group_id, func.count(GroupMember.id)).group_by(GroupMember.group_id)).all())
    return [{"id": g.id, "name": g.name, "topic": g.topic, "description": g.description, "members": n.get(g.id, 0), "joined": g.id in mine}
            for g in db.scalars(select(CommunityGroup).order_by(CommunityGroup.name).limit(200))]


class GroupIn(BaseModel):
    name: str = F(min_length=3, max_length=120)
    topic: str | None = F(default=None, max_length=60)
    description: str | None = F(default=None, max_length=300)


@router.post("/groups", status_code=201)
def create_group(body: GroupIn, user: User = Member, db: Session = Depends(get_db)):
    rate_limit(f"grp:{user.id}", 3, 3600)
    if db.scalar(select(CommunityGroup.id).where(func.lower(CommunityGroup.name) == body.name.lower())):
        raise HTTPException(409, "A group with this name exists")
    g = CommunityGroup(created_by=user.id, **body.model_dump())
    db.add(g)
    db.flush()
    db.add(GroupMember(group_id=g.id, user_id=user.id))
    db.commit()
    return {"id": g.id}


@router.post("/groups/{gid}/join")
def join(gid: int, user: User = Member, db: Session = Depends(get_db)):
    if not db.get(CommunityGroup, gid):
        raise HTTPException(404, "Group not found")
    if not db.scalar(select(GroupMember.id).where(GroupMember.group_id == gid, GroupMember.user_id == user.id)):
        db.add(GroupMember(group_id=gid, user_id=user.id))
        db.commit()
    return {"ok": True}


@router.delete("/groups/{gid}/join")
def leave(gid: int, user: User = Member, db: Session = Depends(get_db)):
    m = db.scalar(select(GroupMember).where(GroupMember.group_id == gid, GroupMember.user_id == user.id))
    if m:
        db.delete(m)
        db.commit()
    return {"ok": True}


@router.get("/posts")
def feed(group_id: int | None = None, kind: str | None = Query(None, pattern=KINDS), topic: str | None = None, q: str | None = Query(None, max_length=60),
         page: int = 1, size: int = 20, user: User = Member, db: Session = Depends(get_db)):
    stmt = select(Post, User).join(User, User.id == Post.user_id).where(Post.status == "PUBLISHED")
    if group_id:
        stmt = stmt.where(Post.group_id == group_id)
    if kind:
        stmt = stmt.where(Post.kind == kind)
    if topic:
        stmt = stmt.where(func.lower(Post.topic) == topic.lower())
    if q:
        stmt = stmt.where(func.lower(Post.body).like(f"%{q.lower()}%") | func.lower(Post.title).like(f"%{q.lower()}%"))
    off, size = page_args(page, size)
    rows = db.execute(stmt.order_by(Post.id.desc()).offset(off).limit(size)).all()
    liked = set(db.scalars(select(PostLike.post_id).where(PostLike.user_id == user.id, PostLike.post_id.in_([p.id for p, _ in rows])))) if rows else set()
    return [post_out(p, u, p.id in liked) for p, u in rows]


class PostIn(BaseModel):
    kind: str = F(default="POST", pattern=KINDS)
    title: str | None = F(default=None, max_length=200)
    body: str = F(min_length=3, max_length=5000)
    topic: str | None = F(default=None, max_length=60)
    group_id: int | None = None


@router.post("/posts", status_code=201)
def create_post(body: PostIn, user: User = Member, db: Session = Depends(get_db)):
    rate_limit(f"post:{user.id}", 10, 3600)
    if body.group_id and not db.scalar(select(GroupMember.id).where(GroupMember.group_id == body.group_id, GroupMember.user_id == user.id)):
        raise HTTPException(403, "Join the group first")
    p = Post(user_id=user.id, is_demo=user.is_demo, **body.model_dump())
    db.add(p)
    db.commit()
    return post_out(p, user)


@router.get("/posts/{pid}")
def get_post(pid: int, user: User = Member, db: Session = Depends(get_db)):
    row = db.execute(select(Post, User).join(User, User.id == Post.user_id).where(Post.id == pid, Post.status == "PUBLISHED")).first()
    if not row:
        raise HTTPException(404, "Post not found")
    cs = db.execute(select(Comment, User).join(User, User.id == Comment.user_id).where(Comment.post_id == pid, Comment.status == "PUBLISHED")
                    .order_by(Comment.id).limit(300)).all()
    return {**post_out(row[0], row[1], bool(db.scalar(select(PostLike.id).where(PostLike.post_id == pid, PostLike.user_id == user.id)))),
            "thread": [{"id": c.id, "body": c.body, "author": _author(u), "is_answer": c.is_answer, "parent_id": c.parent_id, "at": c.created_at.isoformat()} for c, u in cs]}


@router.delete("/posts/{pid}")
def delete_post(pid: int, user: User = Member, db: Session = Depends(get_db)):
    p = db.get(Post, pid)
    if not p or p.user_id != user.id:
        raise HTTPException(404, "Post not found")
    p.status = "REMOVED"
    db.commit()
    return {"ok": True}


class CommentIn(BaseModel):
    body: str = F(min_length=1, max_length=2000)
    parent_id: int | None = None


@router.post("/posts/{pid}/comments", status_code=201)
def comment(pid: int, body: CommentIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Farmers and experts can both answer questions."""
    if not ({"community.use"} <= {p.code for p in user.role.permissions}):
        raise HTTPException(403, "Forbidden")
    rate_limit(f"cmt:{user.id}", 30, 3600)
    p = db.get(Post, pid)
    if not p or p.status != "PUBLISHED":
        raise HTTPException(404, "Post not found")
    c = Comment(post_id=pid, user_id=user.id, body=body.body, parent_id=body.parent_id)
    db.add(c)
    db.execute(update(Post).where(Post.id == pid).values(comment_count=Post.comment_count + 1))
    if p.user_id != user.id:
        notify(db, p.user_id, "COMMUNITY", "New reply on your post", body.body[:100], dedupe_key=f"cm{pid}", dedupe_hours=2)
    db.commit()
    return {"id": c.id}


@router.post("/comments/{cid}/accept")
def accept_answer(cid: int, user: User = Member, db: Session = Depends(get_db)):
    c = db.get(Comment, cid)
    p = db.get(Post, c.post_id) if c else None
    if not c or not p or p.user_id != user.id or p.kind != "QUESTION":
        raise HTTPException(404, "Not found")
    db.execute(update(Comment).where(Comment.post_id == p.id).values(is_answer=False))
    c.is_answer = True
    db.commit()
    return {"ok": True}


@router.post("/posts/{pid}/like")
def like(pid: int, user: User = Member, db: Session = Depends(get_db)):
    if not db.get(Post, pid):
        raise HTTPException(404, "Post not found")
    ex = db.scalar(select(PostLike).where(PostLike.post_id == pid, PostLike.user_id == user.id))
    if ex:
        db.delete(ex)
        db.execute(update(Post).where(Post.id == pid).values(like_count=Post.like_count - 1))
    else:
        db.add(PostLike(post_id=pid, user_id=user.id))
        db.execute(update(Post).where(Post.id == pid).values(like_count=Post.like_count + 1))
    db.commit()
    return {"liked": not ex}


class ReportIn(BaseModel):
    target_type: str = F(pattern="^(POST|COMMENT)$")
    target_id: int
    reason: str = F(min_length=3, max_length=300)


@router.post("/reports", status_code=201)
def report(body: ReportIn, user: User = Member, db: Session = Depends(get_db)):
    rate_limit(f"rep:{user.id}", 10, 3600)
    db.add(ContentReport(reporter_id=user.id, **body.model_dump()))
    db.commit()
    return {"ok": True}


# ---------------- moderation ----------------
@router.get("/moderation/reports")
def open_reports(user: User = Mod, db: Session = Depends(get_db)):
    rows = db.scalars(select(ContentReport).where(ContentReport.status == "OPEN").order_by(ContentReport.id).limit(100))
    out = []
    for r in rows:
        t = db.get(Post if r.target_type == "POST" else Comment, r.target_id)
        out.append({"id": r.id, "target_type": r.target_type, "target_id": r.target_id, "reason": r.reason,
                    "excerpt": (t.body[:200] if t else "(deleted)"), "status": t.status if t else None})
    return out


class ModIn(BaseModel):
    action: str = F(pattern="^(REMOVE|DISMISS)$")


@router.post("/moderation/reports/{rid}")
def moderate(rid: int, body: ModIn, user: User = Mod, db: Session = Depends(get_db)):
    r = db.get(ContentReport, rid)
    if not r or r.status != "OPEN":
        raise HTTPException(404, "Report not found")
    if body.action == "REMOVE":
        t = db.get(Post if r.target_type == "POST" else Comment, r.target_id)
        if t:
            t.status = "REMOVED"
    r.status, r.resolved_by = ("ACTIONED" if body.action == "REMOVE" else "DISMISSED"), user.id
    audit(db, user.id, "moderation.decide", r.target_type.lower(), r.target_id, {"action": body.action})
    db.commit()
    return {"ok": True}
