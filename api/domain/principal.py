"""The signed-in insurance agent (spine AD-4, AD-8).

Framework-free: the REST adapter builds it from the Container Apps sign-in header, and ownership
checks (Story 1.8) compare ``oid`` with a proposal's ``owner_oid``.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Principal:
    """A signed-in agent: her Entra object id, display name and first name."""

    oid: str
    name: str
    first_name: str


def first_name_of(name: str, given_name: str | None) -> str:
    """The ``given_name`` claim when present, else the first word of ``name``, else ``name``."""
    if given_name and given_name.strip():
        return given_name.strip()
    words = name.split()
    return words[0] if words else name
