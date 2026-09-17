import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.dependencies import get_db, get_current_user
from app.modules.map.schemas import HexCreate, HexResponse, HexUpdate, ViewportQuery, MapViewportResponse
from app.modules.map.service import (
    create_hex,
    get_hex_by_id,
    get_hexes_for_user,
    get_hexes_for_viewport,
    update_hex,
)

router = APIRouter()


@router.get("/viewport", response_model=MapViewportResponse)
def viewport_endpoint(
    min_lat: float = Query(...),
    min_lng: float = Query(...),
    max_lat: float = Query(...),
    max_lng: float = Query(...),
    zoom_level: float = Query(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> MapViewportResponse:
    """Get all hexes visible in the current map viewport.

    Called by the Android client on every camera-idle event.
    Requires a valid Bearer token (Supabase JWT).

    The bbox is honored at zoom >= 14 (street level). min_lng > max_lng is
    interpreted as an antimeridian-crossing viewport.
    """
    if min_lat > max_lat:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid bbox: min_lat must be <= max_lat",
        )
    query = ViewportQuery(
        min_lat=min_lat,
        min_lng=min_lng,
        max_lat=max_lat,
        max_lng=max_lng,
        zoom_level=zoom_level,
    )
    user_id = uuid.UUID(current_user["id"])
    return get_hexes_for_viewport(db, query, user_id)



@router.get("/{hex_id}", response_model=HexResponse)
def get_hex_endpoint(hex_id: str, db: Session = Depends(get_db)) -> HexResponse:
    """Get a specific hex by ID.

    M11 note: authenticated, not identity-scoped. Territory ownership is
    already public through `/map/viewport`, which returns every hex in a bbox
    with its king, so this reveals nothing further.
    """
    hex_ownership = get_hex_by_id(db, hex_id)
    if hex_ownership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hex not found")
    return HexResponse.model_validate(hex_ownership)


@router.get("/user/{user_id}", response_model=list[HexResponse])
def get_user_hexes_endpoint(
    user_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[HexResponse]:
    """Get all hexes owned by a user.

    M11 note: authenticated, not identity-scoped, for the same reason as
    `GET /map/{hex_id}` — a player's territory is public by design (the turf
    war is the game), so this is a filtered view of data the viewport already
    returns.
    """
    rows = get_hexes_for_user(db, user_id)
    return [HexResponse.model_validate(row) for row in rows]


@router.post("", response_model=HexResponse, status_code=status.HTTP_201_CREATED)
def create_hex_endpoint(
    payload: HexCreate,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> HexResponse:
    """Create a new hex ownership record.

    M11: the owner is checked against the token. `king_id` arrives in the BODY,
    so this cannot use the path-based `require_own_identity` — without the
    check, any authenticated caller could mint territory in another player's
    name.

    Separately flagged, and deliberately NOT changed here: this endpoint lets a
    client create territory for free, bypassing the run-sync capture rules.
    That is a game-integrity question (M12+), not an identity one.
    """
    if str(payload.king_id) != current_user["id"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You may only claim territory for your own account",
        )
    existing = get_hex_by_id(db, payload.hex_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Hex already exists"
        )
    hex_ownership = create_hex(db, payload.hex_id, payload.king_id, payload.defense_score_steps)
    return HexResponse.model_validate(hex_ownership)


@router.patch("/{hex_id}", response_model=HexResponse)
def update_hex_endpoint(
    hex_id: str, payload: HexUpdate, db: Session = Depends(get_db)
) -> HexResponse:
    """Update a hex's ownership or stats.

    M11 note: authenticated, but neither identity-scoped nor safe to scope —
    `HexUpdate.king_id` can reassign ANY hex to ANY account, including one the
    caller does not own. Territory changes are supposed to happen through
    `/runs/sync` (capture / reinforce / steal, SRS §turf rules), so this route
    is a game-integrity hole, not an identity hole. Left unchanged and flagged
    for review rather than silently redefined.
    """
    hex_ownership = update_hex(db, hex_id, payload)
    if hex_ownership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hex not found")
    return HexResponse.model_validate(hex_ownership)
