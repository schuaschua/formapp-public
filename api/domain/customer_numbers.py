"""Human-readable, typo-safe customer numbers (FORM-218, CAP-10, spine AD-13).

A customer number is ``CUS-`` followed by a 4-digit, zero-padded sequence value and one Luhn
check digit, e.g. sequence ``1002`` -> ``CUS-10025``. The check digit means a single mistyped or
transposed digit almost always resolves to "not a valid number" in Python, before any query ever
runs (:func:`sequence_of` returns ``None``) -- ``find_customer`` (``api/adapters/mcp/server.py``)
never risks matching the wrong customer's neighbouring number.

Generating the *next* number (``nextval('customer_number_seq')``) is the db adapter's job, not
this module's: the sequence must advance in the same transaction as the ``customer`` insert it
numbers, so only the adapter (``adapters/db/proposals.py``) ever calls ``nextval``. This module is
plain Python with no database or framework dependency (AD-2): it only formats a sequence into a
number, or parses a number back into a sequence.
"""

_PREFIX = "CUS-"
_SEQUENCE_DIGITS = 4
_MAX_SEQUENCE = 10**_SEQUENCE_DIGITS - 1


def _luhn_check_digit(payload: str) -> int:
    """The Luhn (mod-10) check digit for ``payload`` (a digit string), doubling every second
    digit counting from the right -- the standard check-digit-generation algorithm (as used for
    credit card and IMEI numbers): the payload's own rightmost digit is doubled first."""
    total = 0
    for index, char in enumerate(reversed(payload)):
        digit = int(char)
        if index % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return (10 - total % 10) % 10


def format_customer_number(sequence: int) -> str:
    """``CUS-<sequence, zero-padded to 4 digits><Luhn check digit>``, e.g. sequence ``1002`` ->
    ``CUS-10025``. Raises ``ValueError`` if ``sequence`` doesn't fit in 4 digits (0-9999)."""
    if not 0 <= sequence <= _MAX_SEQUENCE:
        raise ValueError(f"sequence {sequence} does not fit in {_SEQUENCE_DIGITS} digits")
    body = f"{sequence:0{_SEQUENCE_DIGITS}d}"
    return f"{_PREFIX}{body}{_luhn_check_digit(body)}"


def sequence_of(value: str) -> int | None:
    """The sequence number ``value`` encodes, or ``None`` if it isn't a well-formed customer
    number: wrong prefix, wrong length, a non-digit body, or a check digit that doesn't match what
    :func:`format_customer_number` would have generated for that body -- a single mistyped or
    transposed digit is (almost) always caught here, before any query runs. Case-insensitive and
    trims surrounding whitespace, so "cus-10025" and " CUS-10025 " both parse like "CUS-10025"."""
    if not isinstance(value, str):
        return None
    candidate = value.strip().upper()
    if not candidate.startswith(_PREFIX):
        return None
    rest = candidate[len(_PREFIX) :]
    if len(rest) != _SEQUENCE_DIGITS + 1 or not rest.isdigit():
        return None
    body, check = rest[:_SEQUENCE_DIGITS], rest[_SEQUENCE_DIGITS:]
    if int(check) != _luhn_check_digit(body):
        return None
    return int(body)


def is_valid(value: str) -> bool:
    """Whether ``value`` is a well-formed customer number with a correct check digit."""
    return sequence_of(value) is not None


def normalize(value: str) -> str | None:
    """``value`` re-formatted to its canonical (uppercase, trimmed) form, or ``None`` if it isn't
    a valid customer number at all -- what a store adapter should actually search by, so
    "cus-10025" and "CUS-10025" find the same row."""
    sequence = sequence_of(value)
    return None if sequence is None else format_customer_number(sequence)
