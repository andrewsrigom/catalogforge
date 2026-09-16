import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .contracts import LoginInput, SessionOut, WorkspaceOut
from .db import session_dependency
from .models import AuthSession, Membership, User, Workspace

hasher = PasswordHasher()
COOKIE = "catalogforge_session"
DUMMY_HASH = hasher.hash("constant-time-nonexistent-account")


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Principal:
    user: User
    session: AuthSession | None
    workspace_id: str
    role: str


async def session_user(request: Request, db: AsyncSession):
    token = request.cookies.get(COOKIE, "")
    session = await db.get(AuthSession, digest(token))
    if not session or session.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Sign in to continue")
    user = await db.get(User, session.user_id)
    if not user:
        raise HTTPException(401, "Session no longer valid")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session.csrf):
            raise HTTPException(403, "CSRF token missing or invalid; refresh and try again")
    return user, session


async def principal(
    request: Request, db: AsyncSession = Depends(session_dependency, scope="function")
) -> Principal:
    user, session = await session_user(request, db)
    workspace_id = request.headers.get("x-workspace-id", "")
    membership = await db.get(Membership, (workspace_id, user.id))
    if membership is None:
        raise HTTPException(403, "Workspace membership required")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and membership.role == "viewer":
        raise HTTPException(403, "Viewer membership is read-only")
    return Principal(user, session, workspace_id, membership.role)


async def reviewer(actor: Principal = Depends(principal)) -> Principal:
    if actor.role not in {"owner", "reviewer"}:
        raise HTTPException(403, "Reviewer permission required")
    return actor


async def session_result(db: AsyncSession, user: User, session: AuthSession) -> SessionOut:
    rows = (
        await db.execute(
            select(Workspace, Membership.role)
            .join(Membership, Workspace.id == Membership.workspace_id)
            .where(Membership.user_id == user.id)
        )
    ).all()
    return SessionOut(
        id=user.id,
        email=user.email,
        name=user.name,
        csrf=session.csrf,
        workspaces=[WorkspaceOut(id=w.id, name=w.name, role=role) for w, role in rows],
    )


async def login(db: AsyncSession, body: LoginInput, response: Response) -> SessionOut:
    user = await db.scalar(select(User).where(User.email == body.email.strip().lower()))
    try:
        hasher.verify(user.password_hash if user else DUMMY_HASH, body.password)
    except VerificationError:
        raise HTTPException(401, "Email or password is incorrect") from None
    if user is None:
        raise HTTPException(401, "Email or password is incorrect")
    token = secrets.token_urlsafe(32)
    session = AuthSession(
        token_hash=digest(token),
        user_id=user.id,
        csrf=secrets.token_urlsafe(32),
        expires_at=datetime.now(UTC) + timedelta(hours=12),
    )
    db.add(session)
    await db.flush()
    response.set_cookie(
        COOKIE,
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="strict",
        max_age=43200,
    )
    return await session_result(db, user, session)
