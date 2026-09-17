"""M11 — bearer-token verification (F-04).

Every case here drives the real verifier: a real ES256 signature checked
against a real JWKS document, with the real claim requirements. Nothing is
mocked except the JWKS *fetch* (tests/authkit.py), so an ACCEPT proves the
signature and every claim were genuinely validated, and a REJECT is the
verifier's own decision rather than a test double's.

The rejection cases are the point of the file. A verifier that accepts
everything passes a "valid token works" test; it fails these.
"""
import pytest
from fastapi import HTTPException
from sqlmodel import Session, SQLModel

from app.api.dependencies import DEV_USER_ID, get_current_user
from app.core.database import engine
from app.core.jwks import JwksUnavailable
from app.core.security import InvalidTokenError, decode_supabase_jwt
from tests.authkit import (
    TRUSTED_KID,
    install_jwks,
    jwks_outage,
    link_identity,
    user_row,
)
from tests.conftest import DEV_USER_SUBJECT, OTHER_USER_SUBJECT


class _Creds:
    def __init__(self, token: str) -> None:
        self.credentials = token
        self.scheme = "Bearer"


def _call_get_current_user(db, token: str | None):
    """Invoke the dependency body directly, as FastAPI would."""
    credentials = None if token is None else _Creds(token)
    return get_current_user(credentials=credentials, db=db)


@pytest.fixture()
def db():
    """A session over a fresh schema, with the seeded account already linked.

    These tests drive the dependency directly rather than over HTTP, so they
    own their schema setup instead of borrowing the ``client`` fixture's. The
    dev row is linked to its subject first, exactly as ``_running_client`` does
    — a row without one is invisible to subject resolution, and provisioning
    would then create a second, unrelated account.
    """
    SQLModel.metadata.create_all(engine)
    link_identity(DEV_USER_ID, "devuser")
    try:
        with Session(engine) as session:
            yield session
    finally:
        SQLModel.metadata.drop_all(engine)


# ─────────────────────────────────────────────────────────────────────────────
# Accept
# ─────────────────────────────────────────────────────────────────────────────


def test_valid_token_is_accepted_and_returns_its_claims(jwks):
    token = jwks.factory.token(DEV_USER_SUBJECT, email="dev@example.com")
    claims = decode_supabase_jwt(token)

    assert claims["sub"] == DEV_USER_SUBJECT
    assert claims["aud"] == "authenticated"
    assert claims["iss"] == jwks.factory.issuer


def test_key_is_selected_by_kid_from_the_published_document(jwks):
    """The header's kid is what selects the key — the trusted one is published."""
    token = jwks.factory.token(DEV_USER_SUBJECT)
    header_kid = jwks.trusted.kid
    assert header_kid == TRUSTED_KID
    assert decode_supabase_jwt(token)["sub"] == DEV_USER_SUBJECT


# ─────────────────────────────────────────────────────────────────────────────
# Reject — signature and key provenance
# ─────────────────────────────────────────────────────────────────────────────


def test_foreign_key_token_is_rejected_unknown_kid(jwks):
    """Signed by a key this project does not publish, naming its own kid."""
    token = jwks.factory.foreign_token(jwks.foreign, OTHER_USER_SUBJECT)
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


def test_foreign_key_token_is_rejected_when_it_claims_a_trusted_kid(jwks):
    """The same foreign key, presenting itself as the trusted key.

    This is the case a careless implementation gets wrong: the kid resolves to
    a real published key, so only the SIGNATURE check stands between the
    attacker and an authenticated session.
    """
    token = jwks.foreign.sign(
        jwks.factory.claims(OTHER_USER_SUBJECT), kid=TRUSTED_KID
    )
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


def test_tampered_signature_is_rejected(jwks):
    """A single flipped signature bit must fail verification.

    The bit is flipped in the DECODED signature and re-encoded, not by editing
    the base64 text: the final base64 character of a 64-byte signature carries
    four padding bits, so changing it frequently decodes to identical bytes and
    would "tamper" with nothing.
    """
    import base64

    token = jwks.factory.token(DEV_USER_SUBJECT)
    header, payload, signature = token.split(".")
    raw = bytearray(base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4)))
    raw[0] ^= 0x01  # one bit of the first signature byte
    tampered = base64.urlsafe_b64encode(bytes(raw)).rstrip(b"=").decode()

    assert tampered != signature
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(f"{header}.{payload}.{tampered}")


def test_tampered_payload_is_rejected(jwks):
    """Re-encoding the payload with a new subject must break the signature."""
    import base64
    import json

    token = jwks.factory.token(DEV_USER_SUBJECT)
    header, payload, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    claims["sub"] = OTHER_USER_SUBJECT
    forged = (
        base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    )
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(f"{header}.{forged}.{signature}")


def test_algorithm_none_is_rejected(jwks):
    """The classic algorithm-confusion attempt: an unsigned token."""
    token = jwks.factory.unsigned_token(DEV_USER_SUBJECT)
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


def test_hs256_signed_with_a_shared_secret_is_rejected(jwks):
    """No HS256 fallback (decision D2).

    The old implementation would have verified this token if the secret
    matched — and its default secret was the published string "change-me".
    """
    token = jwks.factory.hs256_token(DEV_USER_SUBJECT, "change-me")
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


def test_unknown_kid_is_rejected_even_though_the_document_was_read(jwks):
    """A readable key set that lacks the kid is a bad token, NOT an outage.

    Misclassifying this as an outage is what turns an identity-provider blip
    into a 401 storm, or worse, invites an "unverifiable → trust it" fallback.
    """
    token = jwks.factory.token(DEV_USER_SUBJECT)
    header, payload, signature = token.split(".")
    import base64
    import json

    head = json.loads(base64.urlsafe_b64decode(header + "=" * (-len(header) % 4)))
    head["kid"] = "no-such-key-in-this-project"
    forged_header = (
        base64.urlsafe_b64encode(json.dumps(head).encode()).rstrip(b"=").decode()
    )
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(f"{forged_header}.{payload}.{signature}")


# ─────────────────────────────────────────────────────────────────────────────
# Reject — claims
# ─────────────────────────────────────────────────────────────────────────────


def test_expired_token_is_rejected(jwks):
    token = jwks.factory.token(DEV_USER_SUBJECT, ttl_seconds=-60)
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


def test_token_without_expiry_is_rejected(jwks):
    """An eternal token must not pass; exp is required, not merely checked."""
    claims = jwks.factory.claims(DEV_USER_SUBJECT)
    claims.pop("exp")
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(jwks.trusted.sign(claims))


def test_wrong_audience_is_rejected(jwks):
    """A service-role / anon token must not authenticate as an app user.

    The old code passed `verify_aud: False`, so this is a regression guard.
    """
    token = jwks.factory.token(DEV_USER_SUBJECT, aud="service_role")
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


def test_wrong_issuer_is_rejected(jwks):
    """A token minted for another Supabase project must not work here."""
    token = jwks.factory.token(
        DEV_USER_SUBJECT, iss="https://someone-elses-project.supabase.co/auth/v1"
    )
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


def test_token_without_subject_is_rejected(jwks):
    claims = jwks.factory.claims(DEV_USER_SUBJECT)
    claims.pop("sub")
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(jwks.trusted.sign(claims))


# ─────────────────────────────────────────────────────────────────────────────
# Reject — malformed input
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "token",
    ["", "not-a-jwt", "a.b", "a.b.c.d", "....", "Bearer x.y.z"],
)
def test_malformed_tokens_are_rejected(jwks, token):
    with pytest.raises(InvalidTokenError):
        decode_supabase_jwt(token)


# ─────────────────────────────────────────────────────────────────────────────
# Failure classification
# ─────────────────────────────────────────────────────────────────────────────


def test_jwks_outage_raises_unavailable_rather_than_invalid(monkeypatch, tokens):
    """An unreachable key set is a 5xx, never a 401.

    A perfectly valid token cannot be checked during an identity-provider blip;
    answering 401 would sign every user out for the duration.

    The token here is valid in every respect — that is the whole point. A
    malformed one would fail at header parsing and prove nothing about the
    outage path.
    """
    install_jwks(monkeypatch, jwks_outage())
    with pytest.raises(JwksUnavailable):
        decode_supabase_jwt(tokens.token(DEV_USER_SUBJECT))


def test_jwks_is_fetched_once_and_reused(jwks, monkeypatch):
    """The document is cached, so verification is not a network call per request."""
    from app.core.jwks import JwksCache

    calls = {"n": 0}

    def _counting_refresh(self):
        calls["n"] += 1
        self._keys = {jwks.trusted.kid: jwks.trusted.jwk}
        import time as _time

        self._fetched_at = _time.monotonic()

    monkeypatch.setattr(JwksCache, "_refresh", _counting_refresh)

    first = decode_supabase_jwt(jwks.factory.token(DEV_USER_SUBJECT))
    second = decode_supabase_jwt(jwks.factory.token(DEV_USER_SUBJECT))

    assert first["sub"] == second["sub"] == DEV_USER_SUBJECT
    # One fetch for two verifications: the second was served from the cache.
    assert calls["n"] == 1


def test_unknown_kid_forces_a_refresh_so_rotation_is_immediate(
    jwks, monkeypatch, es256_key
):
    """A rotated key is honored on first use, not after the cache TTL expires."""
    from app.core.jwks import JwksCache, jwks_cache

    rotated = type(es256_key)("fitquest-test-es256-rotated")
    state = {"keys": {jwks.trusted.kid: jwks.trusted.jwk}}
    refreshes = {"n": 0}

    def _refresh(self):
        refreshes["n"] += 1
        self._keys = dict(state["keys"])
        import time as _time

        self._fetched_at = _time.monotonic()

    monkeypatch.setattr(JwksCache, "_refresh", _refresh)
    jwks_cache.clear()

    # Warm the cache with the original key only.
    decode_supabase_jwt(jwks.factory.token(DEV_USER_SUBJECT))
    assert refreshes["n"] == 1

    # Rotate: publish the new key and start signing with it.
    state["keys"] = {rotated.kid: rotated.jwk}
    rotated_token = rotated.sign(jwks.factory.claims(DEV_USER_SUBJECT))

    # No TTL wait, no cache clear — the unknown kid must trigger exactly one
    # more fetch and then verify.
    assert decode_supabase_jwt(rotated_token)["sub"] == DEV_USER_SUBJECT
    assert refreshes["n"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# get_current_user — identity resolution at the dependency boundary
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_credentials_are_401_with_a_challenge(jwks, db):
    with pytest.raises(HTTPException) as exc:
        _call_get_current_user(db, None)
    assert exc.value.status_code == 401
    assert exc.value.headers["WWW-Authenticate"] == "Bearer"


def test_blank_credentials_are_401(jwks, db):
    with pytest.raises(HTTPException) as exc:
        _call_get_current_user(db, "   ")
    assert exc.value.status_code == 401


def test_invalid_token_is_401_not_500(jwks, db):
    with pytest.raises(HTTPException) as exc:
        _call_get_current_user(db, "not.a.token")
    assert exc.value.status_code == 401


def test_jwks_outage_is_503_not_401(monkeypatch, tokens, db):
    """The dependency must translate an outage into a retryable status."""
    install_jwks(monkeypatch, jwks_outage())
    with pytest.raises(HTTPException) as exc:
        _call_get_current_user(db, tokens.token(DEV_USER_SUBJECT))
    assert exc.value.status_code == 503


def test_identity_is_the_internal_id_and_the_subject_is_reported_separately(jwks, db):
    """Both id spaces are reported, and identity is a REAL row's primary key.

    For the seeded development account the two coincide by construction —
    ``seed.py`` grants a seeded row its own id as its subject — so the
    separation is exercised below with a Supabase-style subject, which is the
    case that actually distinguishes them.
    """
    identity = _call_get_current_user(db, jwks.factory.token(DEV_USER_SUBJECT))

    assert set(identity.keys()) == {"id", "subject"}
    assert identity["subject"] == DEV_USER_SUBJECT
    assert identity["id"] == DEV_USER_ID
    assert user_row(identity["id"]).auth_subject == DEV_USER_SUBJECT

    # A real subject is a Supabase auth.users id, NOT a FitQuest id. Resolving
    # it yields the internal id, and the two remain distinct values.
    supabase_subject = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    real = _call_get_current_user(db, jwks.factory.token(supabase_subject))

    assert real["subject"] == supabase_subject
    assert real["id"] != supabase_subject
    assert user_row(real["id"]).auth_subject == supabase_subject


def test_a_new_subject_provisions_exactly_one_linked_row(jwks, db):
    """First login creates the account; the second login reuses it."""
    new_subject = "11111111-1111-4111-8111-111111111111"
    token = jwks.factory.token(new_subject, email="newcomer@example.com")

    first = _call_get_current_user(db, token)
    second = _call_get_current_user(db, token)

    assert first["id"] == second["id"]
    row = user_row(first["id"])
    assert row.auth_subject == new_subject
    # Username derives from the email local part — recognizable in the UI.
    assert row.username == "newcomer"


def test_a_subject_without_an_email_still_provisions(jwks, db):
    """Provisioning must not depend on an optional claim."""
    subject = "22222222-2222-4222-8222-222222222222"
    identity = _call_get_current_user(db, jwks.factory.token(subject))

    assert user_row(identity["id"]).auth_subject == subject


def test_username_collisions_get_distinct_accounts(jwks, db):
    """Two accounts claiming the same email local part must not collide."""
    first_subject = "33333333-3333-4333-8333-333333333333"
    second_subject = "44444444-4444-4444-8444-444444444444"

    a = _call_get_current_user(db, jwks.factory.token(first_subject, email="sam@a.com"))
    b = _call_get_current_user(db, jwks.factory.token(second_subject, email="sam@b.com"))

    assert a["id"] != b["id"]
    assert user_row(a["id"]).username != user_row(b["id"]).username


def test_a_real_subject_is_never_mapped_onto_the_seeded_dev_user(jwks, db):
    """Decision D4: DEV_USER_ID is not a fallback and is never adopted.

    A brand-new Supabase subject gets its OWN row; it must not inherit the
    seeded development account, its data, or its id.
    """
    from app.api.dependencies import DEV_USER_ID

    fresh_subject = "55555555-5555-4555-8555-555555555555"
    identity = _call_get_current_user(db, jwks.factory.token(fresh_subject))

    assert identity["id"] != DEV_USER_ID
    assert identity["subject"] == fresh_subject
    # The dev row still belongs to the dev subject and to nobody else.
    assert user_row(DEV_USER_ID).auth_subject == DEV_USER_SUBJECT
    assert OTHER_USER_SUBJECT not in (identity["subject"], identity["id"])
