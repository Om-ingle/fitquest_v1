import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.dependencies import get_db, require_own_identity
from app.modules.users.schemas import UserCreate, UserResponse, UserUpdate
from app.modules.users.service import (
    create_user,
    get_all_users,
    get_user_by_id,
    get_user_by_username,
    update_user,
)

router = APIRouter()


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user_endpoint(payload: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """Create a new user.

    M11 note, deliberately left as-is: this route mints a user row with no
    `auth_subject`, so the row it creates can never be logged into — user rows
    now come from `resolve_or_provision_user` on first verified login. It is
    authenticated but NOT identity-scoped, which is not a privacy hole (it
    reads nobody's data) though it does allow username squatting. Removing it
    is an API decision, not an auth fix; flagged for review.
    """
    if get_user_by_username(db, payload.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Username already exists"
        )
    user = create_user(db, payload)
    return UserResponse.model_validate(user)


@router.get("", response_model=list[UserResponse])
def get_users_endpoint(db: Session = Depends(get_db)) -> list[UserResponse]:
    """Get all users.

    M11 note: authenticated, not identity-scoped — a player directory. It does
    expose every account's lifetime steps and streaks to any logged-in caller,
    which is broader than the leaderboard (usernames + territory counts).
    Narrowing it is a product decision; flagged for review.
    """
    users = get_all_users(db)
    return [UserResponse.model_validate(u) for u in users]


@router.get("/{user_id}", response_model=UserResponse)
def get_user_endpoint(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_own_identity),
) -> UserResponse:
    """Get a specific user by ID.

    M11: self-scoped. `UserResponse` carries lifetime steps and streaks — the
    user's own activity — so this is "read my profile", not a public profile
    lookup. Viewing another player's profile is a social feature and is not
    part of M11.
    """
    user = get_user_by_id(db, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)


@router.patch("/{user_id}", response_model=UserResponse)
def update_user_endpoint(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_own_identity),
) -> UserResponse:
    """Update a user's profile.

    M11: self-scoped. Without this, any authenticated account could rewrite
    every other account's profile and stats.
    """
    user = update_user(db, user_id, payload)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserResponse.model_validate(user)
