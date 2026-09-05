import math
import uuid
from datetime import datetime

import h3
from sqlmodel import Session, select

from app.modules.map.models import HexOwnership
from app.modules.map.schemas import HexDetailResponse, HexUpdate, MapViewportResponse, ViewportQuery
from app.modules.users.models import User

# Below this zoom the map switches to aggregated view (heatmaps) — the
# aggregation algorithm is not implemented yet, so the placeholder returns
# an empty aggregated response (unchanged contract).
MIN_DETAIL_ZOOM = 14.0

# The mobile client captures territory at H3 resolution 10 (see
# HexCaptureEngine); ownership rows therefore always store res-10 indexes.
H3_RESOLUTION = 10

# Approximate kilometers per degree of latitude (equator-referenced).
KM_PER_DEGREE_LAT = 110.574


def get_hex_by_id(db: Session, hex_id: str) -> HexOwnership | None:
    return db.get(HexOwnership, hex_id)


def get_hexes_for_viewport(
    db: Session, query: ViewportQuery, current_user_id: uuid.UUID
) -> MapViewportResponse:
    # Zoomed out: aggregated placeholder (heatmap algorithm not implemented).
    if query.zoom_level < MIN_DETAIL_ZOOM:
        return MapViewportResponse(is_aggregated=True, hexes=[], heatmaps=[])

    # H3-native viewport filtering: no center lat/lng columns are stored —
    # the geographic position of every hex is recovered from its H3 index.
    # HexOwnership rows join User for the king's username.
    rows = db.exec(
        select(
            HexOwnership.hex_id,
            HexOwnership.king_id,
            User.username,
            HexOwnership.defense_score_steps,
        ).join(User, HexOwnership.king_id == User.id)  # type: ignore[arg-type]
    ).all()

    # Pad the bbox by one res-10 hex edge so cells whose boundary clips the
    # viewport (but whose center lies outside) are still returned.
    edge_km = h3.average_hexagon_edge_length(H3_RESOLUTION, unit="km")
    lat_pad_deg = edge_km / KM_PER_DEGREE_LAT
    center_lat = (query.min_lat + query.max_lat) / 2
    lng_pad_deg = lat_pad_deg / max(math.cos(math.radians(center_lat)), 1e-6)

    # min_lng > max_lng means the bbox crosses the antimeridian.
    crosses_antimeridian = query.min_lng > query.max_lng

    def in_bbox(lat: float, lng: float) -> bool:
        if not (query.min_lat - lat_pad_deg <= lat <= query.max_lat + lat_pad_deg):
            return False
        if crosses_antimeridian:
            return lng >= query.min_lng - lng_pad_deg or lng <= query.max_lng + lng_pad_deg
        return query.min_lng - lng_pad_deg <= lng <= query.max_lng + lng_pad_deg

    hex_details = []
    for row in rows:
        try:
            lat, lng = h3.cell_to_latlng(row.hex_id)
        except (h3.H3FailedError, ValueError):
            # Malformed index in the DB — skip rather than fabricate a position.
            continue
        if not in_bbox(lat, lng):
            continue
        hex_details.append(
            HexDetailResponse(
                hex_id=row.hex_id,
                king_id=row.king_id,
                king_username=row.username,
                defense_score_steps=row.defense_score_steps,
                is_owned_by_me=(row.king_id == current_user_id),
            )
        )

    return MapViewportResponse(
        is_aggregated=False,
        hexes=hex_details,
        heatmaps=[],
    )


def get_hexes_for_user(db: Session, user_id: uuid.UUID) -> list[HexOwnership]:
    statement = select(HexOwnership).where(HexOwnership.king_id == user_id)
    return list(db.exec(statement).all())


def create_hex(
    db: Session, hex_id: str, king_id: uuid.UUID, defense_score_steps: int = 0
) -> HexOwnership:
    hex_ownership = HexOwnership(
        hex_id=hex_id, king_id=king_id, defense_score_steps=defense_score_steps
    )
    db.add(hex_ownership)
    db.commit()
    db.refresh(hex_ownership)
    return hex_ownership


def update_hex(db: Session, hex_id: str, payload: HexUpdate) -> HexOwnership | None:
    hex_ownership = get_hex_by_id(db, hex_id)
    if hex_ownership is None:
        return None

    if payload.king_id is not None:
        hex_ownership.king_id = payload.king_id
        hex_ownership.captured_at = datetime.utcnow()

    if payload.defense_score_steps is not None:
        hex_ownership.defense_score_steps = payload.defense_score_steps

    if payload.times_stolen is not None:
        hex_ownership.times_stolen = payload.times_stolen

    db.add(hex_ownership)
    db.commit()
    db.refresh(hex_ownership)
    return hex_ownership
