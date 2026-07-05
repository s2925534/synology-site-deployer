from __future__ import annotations

import base64
import hashlib
import hmac
import json

from synology_site.supabase.jwt_keys import mint_hs256_jwt, mint_supabase_keys


def _decode_segment(segment: str) -> dict[str, object]:
    padded = segment + "=" * (-len(segment) % 4)
    return json.loads(base64.urlsafe_b64decode(padded))


def test_mint_hs256_jwt_has_three_segments_with_expected_claims() -> None:
    token = mint_hs256_jwt({"role": "anon"}, "s3cret-signing-key")

    header_seg, payload_seg, signature_seg = token.split(".")
    assert _decode_segment(header_seg) == {"alg": "HS256", "typ": "JWT"}
    assert _decode_segment(payload_seg) == {"role": "anon"}
    assert signature_seg


def test_mint_hs256_jwt_signature_verifies_with_secret() -> None:
    secret = "another-secret"
    token = mint_hs256_jwt({"role": "service_role"}, secret)
    header_seg, payload_seg, signature_seg = token.split(".")

    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    expected_b64 = base64.urlsafe_b64encode(expected_sig).rstrip(b"=").decode("ascii")

    assert signature_seg == expected_b64


def test_mint_hs256_jwt_rejects_tampered_signature_under_a_different_secret() -> None:
    token = mint_hs256_jwt({"role": "anon"}, "secret-a")
    header_seg, payload_seg, signature_seg = token.split(".")

    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    wrong_sig = hmac.new(b"secret-b", signing_input, hashlib.sha256).digest()
    wrong_b64 = base64.urlsafe_b64encode(wrong_sig).rstrip(b"=").decode("ascii")

    assert signature_seg != wrong_b64


def test_mint_supabase_keys_returns_distinct_role_claims() -> None:
    anon_key, service_role_key = mint_supabase_keys(
        "the-jwt-secret", issued_at=1000, expires_at=2000
    )

    anon_payload = _decode_segment(anon_key.split(".")[1])
    service_payload = _decode_segment(service_role_key.split(".")[1])

    assert anon_payload["role"] == "anon"
    assert service_payload["role"] == "service_role"
    assert anon_payload["iat"] == 1000
    assert anon_payload["exp"] == 2000
    assert anon_key != service_role_key
