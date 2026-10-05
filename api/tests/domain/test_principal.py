"""Story 1.6: the principal's first name."""

import dataclasses

import pytest

from domain.principal import Principal, first_name_of


@pytest.mark.parametrize(
    ("name", "given_name", "expected"),
    [
        ("Ally Macbeal", "Ally", "Ally"),
        ("Ally Macbeal", None, "Ally"),
        ("Ally Macbeal", "", "Ally"),
        ("  Ally   Macbeal ", None, "Ally"),
        ("Ally", None, "Ally"),
        ("", None, ""),
        ("   ", None, "   "),
    ],
)
def test_story_1_6_first_name_rule(
    name: str, given_name: str | None, expected: str
) -> None:
    assert first_name_of(name, given_name) == expected


def test_story_1_6_principal_is_immutable() -> None:
    principal = Principal(oid="synthetic-oid", name="Ally Macbeal", first_name="Ally")

    with pytest.raises(dataclasses.FrozenInstanceError):
        principal.oid = "other"  # type: ignore[misc]
