"""Development/test seeding.

M11 changed what this script is for. It is now the ONLY place that grants a
seeded user an ``auth_subject``, which is what makes those rows reachable by a
verified token in development and tests while leaving them unreachable in
production: Supabase Auth — the only issuer whose tokens this backend verifies
— has no account with these UUIDs, so no real login can ever resolve to them.

The HS256 test token this script used to print is gone with the shared secret
it was signed by. Tokens now come from Supabase Auth (see
``app/core/security.py``); nothing in the backend can mint one.
"""
import uuid

from sqlmodel import Session, select

from app.core.database import create_db_and_tables, engine
from app.modules.map.models import HexOwnership  # noqa: F401  (metadata)
from app.modules.quests.models import Quest, UserQuest  # noqa: F401  (metadata)
from app.modules.runs.models import CapturedHex, RunSession  # noqa: F401  (metadata)
from app.modules.users.models import Friendship, User

# Must match DEV_USER_ID in app/api/dependencies.py: it is the identity the
# local data belongs to, and PostgreSQL enforces the hexownership/runsession
# foreign keys — so the dev user must exist.
DEV_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
TEST_USER_ID = uuid.UUID("11111111-2222-3333-4444-555555555555")


def _provision(session: Session, user_id: uuid.UUID, username: str, **stats) -> None:
    """Create the seeded user if absent; link it to its own subject if unlinked.

    Idempotent, and deliberately narrow: it only ever sets ``auth_subject`` to
    the user's OWN id, so re-running the seed can never hand an existing row to
    a different identity.
    """
    user = session.get(User, user_id)
    if user is None:
        # The subject is this row's OWN id, so a fresh seed is complete in one
        # run and a second run has nothing left to do.
        user = User(id=user_id, username=username, auth_subject=str(user_id), **stats)
        session.add(user)
        session.commit()
        print(f"✅ Seeded user {username}.")
        return

    if user.auth_subject != str(user_id):
        # Provisioning the dev/test identity, not backfilling a real account:
        # the subject is this row's own UUID and nothing else.
        user.auth_subject = str(user_id)
        session.add(user)
        session.commit()
        print(f"✅ Linked seeded user {username} to its development identity.")
    else:
        print(f"✅ User {username} already exists.")


def seed_db() -> None:
    print("Seeding database...")
    create_db_and_tables()

    with Session(engine) as session:
        _provision(session, DEV_USER_ID, "devuser")
        _provision(
            session,
            TEST_USER_ID,
            "testuser",
            total_lifetime_steps=1000,
            total_hexes_captured=5,
        )

    print(
        "\nℹ️  Access tokens are issued by Supabase Auth (M11). This script no "
        "longer mints one — see apps/api/README.md.\n"
    )


if __name__ == "__main__":
    seed_db()
