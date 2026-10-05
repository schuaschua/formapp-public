"""The product catalogue: products, their riders, and the listing service (Story 2.1, spine AD-2).

The catalogue lives in PostgreSQL (AD-10); the domain reads it only through the ``ProductCatalogue``
port, which the db adapter implements. Pricing by age band (Story 2.2) builds on these types, and
:func:`priced_products` (Story 2.3) builds the priced-and-eligible listing that both
``GET /api/products?proposal_id=`` and the MCP ``get_products`` (Epic 4) will reuse.
"""

from collections.abc import Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from domain.pricing import band_index, item_price


class ProductType(StrEnum):
    """A product's type, with N1's answer codes."""

    LIFE = "life"
    LIFE_HEALTH = "life_health"
    HEALTH = "health"


@dataclass(frozen=True, slots=True)
class PolicyTerm:
    """One allowed policy term; P3 answers store its code."""

    code: str
    label: str


@dataclass(frozen=True, slots=True)
class Rider:
    """An optional rider; it belongs to exactly one product, and its code is unique across all."""

    code: str
    name: str
    baseline_monthly: Decimal


@dataclass(frozen=True, slots=True)
class Product:
    """A product with its stored fields and its riders.

    The sum-assured fields are all None for a product without a sum assured (CFH). Money is RM.
    """

    code: str
    name: str
    type: ProductType
    covers_dependents: bool
    policy_terms: tuple[PolicyTerm, ...]
    sum_assured_min: Decimal | None
    sum_assured_max: Decimal | None
    default_sum_assured: Decimal | None
    default_term: str
    min_age: int
    max_age: int
    baseline_monthly: Decimal
    riders: tuple[Rider, ...]


class ProductCatalogue(Protocol):
    """Port to the stored catalogue; implemented by the db adapter."""

    async def products(self) -> Sequence[Product]:
        """Return every stored product with its riders, in any order."""
        ...


async def list_products(catalogue: ProductCatalogue) -> tuple[Product, ...]:
    """Return every product ordered by code, each with its riders ordered by code."""
    products = await catalogue.products()
    return tuple(
        replace(product, riders=tuple(sorted(product.riders, key=_code)))
        for product in sorted(products, key=_code)
    )


def _code(item: Product | Rider) -> str:
    return item.code


@dataclass(frozen=True, slots=True)
class PricedRider:
    """A rider priced at a product's age band (Story 2.3): ``pricing.item_price`` on its own
    baseline, on top of the product's own line."""

    code: str
    name: str
    monthly: Decimal
    yearly: Decimal


@dataclass(frozen=True, slots=True)
class PricedProduct:
    """A product priced at the insured's age band, every stored field
    ``GET /api/products?proposal_id=`` needs, with ``monthly``/``yearly`` in place of
    ``baseline_monthly`` and its riders priced the same way (Story 2.3)."""

    code: str
    name: str
    type: ProductType
    covers_dependents: bool
    policy_terms: tuple[PolicyTerm, ...]
    sum_assured_min: Decimal | None
    sum_assured_max: Decimal | None
    default_sum_assured: Decimal | None
    default_term: str
    min_age: int
    max_age: int
    monthly: Decimal
    yearly: Decimal
    riders: tuple[PricedRider, ...]


def _priced_rider(rider: Rider, index: int) -> PricedRider:
    price = item_price(rider.baseline_monthly, index)
    return PricedRider(
        code=rider.code, name=rider.name, monthly=price.monthly, yearly=price.yearly
    )


def _priced_product(product: Product, index: int) -> PricedProduct:
    price = item_price(product.baseline_monthly, index)
    return PricedProduct(
        code=product.code,
        name=product.name,
        type=product.type,
        covers_dependents=product.covers_dependents,
        policy_terms=product.policy_terms,
        sum_assured_min=product.sum_assured_min,
        sum_assured_max=product.sum_assured_max,
        default_sum_assured=product.default_sum_assured,
        default_term=product.default_term,
        min_age=product.min_age,
        max_age=product.max_age,
        monthly=price.monthly,
        yearly=price.yearly,
        riders=tuple(_priced_rider(rider, index) for rider in product.riders),
    )


async def priced_products(
    catalogue: ProductCatalogue, age: int | None
) -> tuple[PricedProduct, ...]:
    """The priced-and-eligible product listing (Story 2.3), ordered by code, riders by code.

    ``age`` is the insured's age at the proposal's ``created_at``, or ``None`` when C2 isn't set
    yet. A known age drops any product whose ``min_age``/``max_age`` range excludes it, and prices
    the rest at that age's band; ``None`` returns every product, priced at band 0 -- its baseline
    price unchanged, since the band-0 multiplier is exactly 1 (spec Design Notes), never a separate
    "unpriced" shape.
    An age with no band at all (over 70) is priced at nobody -- there is no age-band index to price
    it with -- so the listing is empty.
    """
    products = await list_products(catalogue)
    if age is None:
        return tuple(_priced_product(product, 0) for product in products)
    index = band_index(age)
    if index is None:
        return ()
    # Owner decision (owner, 2026-09-27): a product's min_age/max_age no longer hides it; every
    # product is listed, priced for the insured's age band.
    return tuple(_priced_product(product, index) for product in products)
