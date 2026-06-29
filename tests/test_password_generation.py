from synology_site.database.passwords import generate_password


def test_password_generation_length() -> None:
    assert len(generate_password(32)) == 32


def test_password_generation_randomness() -> None:
    assert generate_password(32) != generate_password(32)
