from __future__ import annotations

import base64
import hashlib
import hmac
import json

# Self-hosted Supabase's ANON_KEY/SERVICE_ROLE_KEY must be JWTs signed with
# JWT_SECRET carrying a specific role claim -- GoTrue/PostgREST/Kong check
# the `role` claim, not just that the token is well-formed. This is a plain
# stdlib HS256 encoder rather than a PyJWT dependency, since only this one
# narrow shape of token is ever minted here.

_HEADER = {"alg": "HS256", "typ": "JWT"}


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def mint_hs256_jwt(payload: dict[str, object], secret: str) -> str:
    segments = [
        _b64url(json.dumps(_HEADER, separators=(",", ":")).encode("utf-8")),
        _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8")),
    ]
    signing_input = ".".join(segments).encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    segments.append(_b64url(signature))
    return ".".join(segments)


def mint_supabase_keys(jwt_secret: str, *, issued_at: int, expires_at: int) -> tuple[str, str]:
    """Returns (anon_key, service_role_key)."""
    anon_key = mint_hs256_jwt(
        {"role": "anon", "iss": "supabase", "iat": issued_at, "exp": expires_at}, jwt_secret
    )
    service_role_key = mint_hs256_jwt(
        {"role": "service_role", "iss": "supabase", "iat": issued_at, "exp": expires_at},
        jwt_secret,
    )
    return anon_key, service_role_key
