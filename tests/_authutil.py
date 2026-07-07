"""Shared test helper: mint Supabase-style asymmetric (ES256) access tokens.

Supabase Auth is the ONLY identity path the backend accepts (the legacy custom
HS256 JWT path was retired in fix/auth-hardening). Tests therefore authenticate
by minting real ES256 tokens signed with a throwaway EC P-256 keypair whose
public half is published as a stubbed JWKS (see the autouse `_supabase_auth_env`
fixture in conftest.py — no network).

Import `mint_supabase_token` in any test/fixture that needs an auth token for a
given user id:

    from tests._authutil import mint_supabase_token
    token = mint_supabase_token(sub=str(user.id))
    headers = {"Authorization": f"Bearer {token}"}
"""

from __future__ import annotations

import time
import uuid
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from jose import jwk, jwt
from jose.constants import ALGORITHMS

TEST_ISSUER_BASE = "https://test-project.supabase.co"
TEST_ISSUER = f"{TEST_ISSUER_BASE}/auth/v1"
TEST_AUDIENCE = "authenticated"
TEST_KID = "test-key-1"

# One throwaway EC P-256 keypair for the whole test session. The private half
# signs tokens; the public half is served as the (stubbed) JWKS.
_PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())
PRIVATE_PEM = _PRIVATE_KEY.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
_PUBLIC_PEM = _PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo,
).decode()
PUBLIC_JWK = jwk.construct(_PUBLIC_PEM, ALGORITHMS.ES256).to_dict()
PUBLIC_JWK["kid"] = TEST_KID
PUBLIC_JWK["alg"] = "ES256"
PUBLIC_JWK["use"] = "sig"


def mint_supabase_token(
    *,
    sub: Optional[str] = None,
    email: str = "user@example.com",
    aud: str = TEST_AUDIENCE,
    iss: str = TEST_ISSUER,
    exp_delta: int = 3600,
    kid: Optional[str] = TEST_KID,
    metadata: Optional[dict] = None,
    key: Optional[str] = None,
    algorithm: str = "ES256",
) -> str:
    """Mint a Supabase-style access token.

    Defaults produce a VALID token for the stubbed JWKS. Override individual
    fields to build rejection cases: `iss`/`aud`/`exp_delta` for claim checks,
    `key` for a foreign-signature forgery, `algorithm="HS256"` for a symmetric /
    algorithm-confusion attempt, `kid` for an unknown key id.
    """
    now = int(time.time())
    claims = {
        "sub": sub or str(uuid.uuid4()),
        "aud": aud,
        "iss": iss,
        "role": "authenticated",
        "email": email,
        "iat": now,
        "exp": now + exp_delta,
    }
    if metadata is not None:
        claims["user_metadata"] = metadata
    headers = {"kid": kid} if kid is not None else {}
    return jwt.encode(claims, key or PRIVATE_PEM, algorithm=algorithm, headers=headers)
