"""Age-band pricing and the draft's quote (Story 2.2; spine AD-5, AD-10).

This is the only place prices are computed. It takes plain inputs and knows nothing of the
catalogue's storage: any product with a name, a baseline and riders can be priced.

Money is ``Decimal`` throughout. Each amount is rounded to 2 decimals once, at the end, half up:
lines from each item's unrounded price, totals from the unrounded sums, so the lines may differ
from the total by a cent.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

# Age is counted on the Malaysian calendar date of created_at (stored in UTC). A fixed offset
# rather than ZoneInfo: Malaysia has had no DST since 1982, and the slim image may lack tzdata.
PRICING_TIMEZONE = timezone(timedelta(hours=8), "Asia/Kuala_Lumpur")

_BAND_STEP = Decimal("1.05")  # FR4: x1.05 per band, compounded
_YEARLY_FACTOR = 12 * Decimal("0.95")  # FR5: 12 months with 5% off for paying yearly
_CENT = Decimal("0.01")

_FIRST_BAND_MAX_AGE = 18
_SECOND_BAND_MAX_AGE = 25
_MAX_AGE = 70


class PricedRider(Protocol):
    """A rider as pricing reads it."""

    @property
    def code(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def baseline_monthly(self) -> Decimal: ...


class PricedProduct(Protocol):
    """A product as pricing reads it, with the riders that belong to it."""

    @property
    def name(self) -> str: ...

    @property
    def baseline_monthly(self) -> Decimal: ...

    @property
    def riders(self) -> Sequence[PricedRider]: ...


@dataclass(frozen=True)
class ItemPrice:
    """One item's monthly and yearly price, rounded to 2 decimals."""

    monthly: Decimal
    yearly: Decimal


@dataclass(frozen=True)
class QuoteLine:
    """One priced item of a quote: the product or one rider."""

    item: str
    monthly: Decimal
    yearly: Decimal


@dataclass(frozen=True)
class Quote:
    """The totals and the per-item lines, product first, then riders in the order chosen."""

    monthly: Decimal
    yearly: Decimal
    lines: tuple[QuoteLine, ...]


def _require_aware(created_at: datetime) -> None:
    if created_at.utcoffset() is None:
        raise ValueError("created_at must be timezone-aware")


def age_at(date_of_birth: date, created_at: datetime) -> int:
    """Return the age in whole years on the Malaysian calendar date of created_at.

    A 29 February birthday counts from 1 March in non-leap years. Raises ``ValueError`` for a
    naive created_at, which is a programming error.
    """
    _require_aware(created_at)
    on = created_at.astimezone(PRICING_TIMEZONE).date()
    before_birthday = (on.month, on.day) < (date_of_birth.month, date_of_birth.day)
    return on.year - date_of_birth.year - before_birthday


def band_index(age: int) -> int | None:
    """Return the age band index 0-10, or ``None`` for an age outside 0-70."""
    if age < 0 or age > _MAX_AGE:
        return None
    if age <= _FIRST_BAND_MAX_AGE:
        return 0
    if age <= _SECOND_BAND_MAX_AGE:
        return 1
    return (age - _SECOND_BAND_MAX_AGE - 1) // 5 + 2


def _monthly(baseline: Decimal, index: int) -> Decimal:
    # Exact multiplier 1.05^index, never the 4-decimal table.
    return baseline * _BAND_STEP**index


def _round(amount: Decimal) -> Decimal:
    return amount.quantize(_CENT, rounding=ROUND_HALF_UP)


def item_price(baseline: Decimal, index: int) -> ItemPrice:
    """Price one item's monthly baseline at a band index, rounded once at the end."""
    monthly = _monthly(baseline, index)
    return ItemPrice(monthly=_round(monthly), yearly=_round(monthly * _YEARLY_FACTOR))


def build_quote(
    product: PricedProduct | None,
    rider_codes: Sequence[str],
    date_of_birth: date | None,
    created_at: datetime,
) -> Quote | None:
    """Price a product and its chosen riders for the insured's age at created_at.

    Returns ``None`` when there is no product or date of birth, the age has no band, or any rider
    code is not one of the product's riders.
    """
    _require_aware(created_at)
    if product is None or date_of_birth is None:
        return None
    index = band_index(age_at(date_of_birth, created_at))
    if index is None:
        return None
    riders_by_code = {rider.code: rider for rider in product.riders}
    if any(code not in riders_by_code for code in rider_codes):
        return None

    items = [(product.name, product.baseline_monthly)] + [
        (riders_by_code[code].name, riders_by_code[code].baseline_monthly)
        for code in rider_codes
    ]
    monthly_total = Decimal(0)
    lines = []
    for name, baseline in items:
        monthly = _monthly(baseline, index)
        monthly_total += monthly
        lines.append(
            QuoteLine(
                item=name,
                monthly=_round(monthly),
                yearly=_round(monthly * _YEARLY_FACTOR),
            )
        )
    return Quote(
        monthly=_round(monthly_total),
        yearly=_round(monthly_total * _YEARLY_FACTOR),
        lines=tuple(lines),
    )
