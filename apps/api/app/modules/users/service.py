import re
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.modules.users.models import User
from app.modules.users.schemas import UserCreate, UserUpdate


def create_user(db: Session, payload: UserCreate) -> User:
    user = User(username=payload.username, avatar_url=payload.avatar_url)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def get_user_by_username(db: Session, username: str) -> User | None:
    statement = select(User).where(User.username == username)
    return db.exec(statement).first()


def get_all_users(db: Session) -> list[User]:
    statement = select(User)
    return list(db.exec(statement).all())


def update_user(db: Session, user_id: uuid.UUID, payload: UserUpdate) -> User | None:
    user = get_user_by_id(db, user_id)
    if user is None:
        return None

    update_data = payload.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(user, key, value)

    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── M11: identity resolution (F-04) ──────────────────────────────────────────

_USERNAME_UNSAFE = re.compile(r"[^a-z0-9_]+")


def get_user_by_auth_subject(db: Session, subject: str) -> User | None:
    """Find the row linked to a verified Supabase subject, if any.

    A NULL subject never matches: the seeded dev/test rows stay unreachable
    through this lookup, which is what keeps them out of real logins without
    needing a production-access rule.
    """
    statement = select(User).where(User.auth_subject == subject)
    return db.exec(statement).first()


def _username_base(subject: str, claims: dict) -> str:
    """Derive a readable, deterministic username from the token's own claims.

    Prefers the email local part because that is what a person recognizes in
    the UI; falls back to the subject when the token carries no usable email.
    Never fails — provisioning must not depend on an optional claim.
    """
    email = str(claims.get("email") or "").strip().lower()
    local = email.split("@", 1)[0] if "@" in email else ""
    slug = _USERNAME_UNSAFE.sub("", local.replace(".", "_").replace("-", "_")).strip("_")
    if len(slug) < 3:
        return f"user_{subject.replace('-', '')[:12]}"
    return slug[:24]


def _allocate_username(db: Session, subject: str, claims: dict) -> str:
    """Pick a unique username. `username` is UNIQUE, so this must not race blindly."""
    base = _username_base(subject, claims)
    if get_user_by_username(db, base) is None:
        return base

    suffixed = f"{base}_{subject.replace('-', '')[:8]}"
    if get_user_by_username(db, suffixed) is None:
        return suffixed

    # Deterministic last resort: the full subject is unique by construction, so
    # this differs from every username derived for any other subject.
    return f"user_{subject.replace('-', '')}"


def resolve_or_provision_user(db: Session, *, subject: str, claims: dict | None = None) -> User:
    """Map a verified JWT subject to a user row, creating it on first login.

    The row is created with `auth_subject = subject` and an internal `id` of
    its own — the internal id is never the external subject, so no domain table
    gains a dependency on the identity provider's identifiers.

    Idempotent under concurrency: the unique index on `auth_subject` is the
    arbiter, and the loser of a first-login race re-reads the winner's row
    instead of failing the request or creating a duplicate account.
    """
    existing = get_user_by_auth_subject(db, subject)
    if existing is not None:
        return existing

    claims = claims or {}
    user = User(
        auth_subject=subject,
        username=_allocate_username(db, subject, claims),
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        # Either a concurrent first login for this subject, or a username race.
        # The unique constraints decide; adopt whatever won.
        db.rollback()
        existing = get_user_by_auth_subject(db, subject)
        if existing is None:
            raise
        return existing

    db.refresh(user)
    return user
