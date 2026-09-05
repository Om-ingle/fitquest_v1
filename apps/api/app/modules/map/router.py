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
    """Get a specific hex by ID."""
    hex_ownership = get_hex_by_id(db, hex_id)
    if hex_ownership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hex not found")
    return HexResponse.model_validate(hex_ownership)


@router.get("/user/{user_id}", response_model=list[HexResponse])
def get_user_hexes_endpoint(
    user_id: uuid.UUID, db: Session = Depends(get_db)
) -> list[HexResponse]:
    """Get all hexes owned by a user."""
    rows = get_hexes_for_user(db, user_id)
    return [HexResponse.model_validate(row) for row in rows]


@router.post("", response_model=HexResponse, status_code=status.HTTP_201_CREATED)
def create_hex_endpoint(payload: HexCreate, db: Session = Depends(get_db)) -> HexResponse:
    """Create a new hex ownership record."""
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
    """Update a hex's ownership or stats."""
    hex_ownership = update_hex(db, hex_id, payload)
    if hex_ownership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Hex not found")
    return HexResponse.model_validate(hex_ownership)
