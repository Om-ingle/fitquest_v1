import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlmodel import Session

from app.api.dependencies import get_db, require_admin, require_own_identity
from app.modules.quests.schemas import (
    QuestCreate,
    QuestResponse,
    UserQuestResponse,
    UserQuestUpdate,
)
from app.modules.quests.service import (
    create_quest,
    create_user_quest,
    get_all_quests,
    get_quest_by_id,
    get_user_quest,
    get_user_quests,
    update_user_quest,
)

router = APIRouter()


@router.post("", response_model=QuestResponse, status_code=status.HTTP_201_CREATED)
def create_quest_endpoint(
    payload: QuestCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_admin),
) -> QuestResponse:
    """Create a new quest (admin only).

    M11: the docstring always said "admin only" and nothing enforced it. It now
    checks the ADMIN_USER_IDS allow-list — the same list that gates knowledge-
    base ingestion. Applying it here is a deliberate extension of that decision;
    creating quests is game content, so it belongs to operators, not players.
    """
    quest = create_quest(db, payload)
    return QuestResponse.model_validate(quest)


@router.get("", response_model=list[QuestResponse])
def get_quests_endpoint(db: Session = Depends(get_db)) -> list[QuestResponse]:
    """Get all active quests."""
    quests = get_all_quests(db)
    return [QuestResponse.model_validate(q) for q in quests]


@router.get("/{quest_id}", response_model=QuestResponse)
def get_quest_endpoint(quest_id: uuid.UUID, db: Session = Depends(get_db)) -> QuestResponse:
    """Get a specific quest by ID."""
    quest = get_quest_by_id(db, quest_id)
    if quest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quest not found")
    return QuestResponse.model_validate(quest)


@router.get("/{user_id}/quests", response_model=list[UserQuestResponse])
def get_user_quests_endpoint(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_own_identity),
) -> list[UserQuestResponse]:
    """Get all quests for a specific user.

    M11: self-scoped — quest progress is private per-user data.
    """
    user_quests = get_user_quests(db, user_id)
    return [UserQuestResponse.model_validate(uq) for uq in user_quests]


@router.post(
    "/{user_id}/quests/{quest_id}",
    response_model=UserQuestResponse,
    status_code=status.HTTP_201_CREATED,
)
def enroll_user_quest_endpoint(
    user_id: uuid.UUID,
    quest_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_own_identity),
) -> UserQuestResponse:
    """Enroll a user in a quest.

    M11: self-scoped — a caller may only enroll themselves.
    """
    quest = get_quest_by_id(db, quest_id)
    if quest is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quest not found")

    existing = get_user_quest(db, user_id, quest_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="User already enrolled in this quest"
        )

    user_quest = create_user_quest(db, user_id, quest_id)
    return UserQuestResponse.model_validate(user_quest)


@router.patch(
    "/{user_id}/quests/{quest_id}", response_model=UserQuestResponse
)
def update_user_quest_endpoint(
    user_id: uuid.UUID,
    quest_id: uuid.UUID,
    payload: UserQuestUpdate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(require_own_identity),
) -> UserQuestResponse:
    """Update a user's quest progress.

    M11: self-scoped. This route writes progress counters, so leaving it open
    would let any authenticated account complete another player's quests.
    """
    user_quest = update_user_quest(db, user_id, quest_id, payload)
    if user_quest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User quest not found"
        )
    return UserQuestResponse.model_validate(user_quest)
