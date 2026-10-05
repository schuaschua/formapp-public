"""Story 2.1: the domain lists the catalogue through its port, ordered by code (AD-2).

Story 2.3's ``priced_products`` -- the priced-and-eligible listing ``GET
/api/products?proposal_id=`` reuses -- lives here too, next to the catalogue types it prices.
"""

import asyncio
from collections.abc import Sequence
from decimal import Decimal

from domain.products import (
    PolicyTerm,
    PricedProduct,
    PricedRider,
    Product,
    ProductCatalogue,
    ProductType,
    Rider,
    list_products,
    priced_products,
)


class FakeCatalogue:
    """An in-memory ProductCatalogue that returns products in the order given."""

    def __init__(self, products: Sequence[Product]) -> None:
        self._products = products
        self.calls = 0

    async def products(self) -> Sequence[Product]:
        self.calls += 1
        return self._products


def _product(code: str, *riders: Rider, sum_assured: bool = True) -> Product:
    amount = Decimal("100000.00") if sum_assured else None
    return Product(
        code=code,
        name=f"Synthetic {code}",
        type=ProductType.LIFE,
        covers_dependents=True,
        policy_terms=(PolicyTerm(code="10_yrs", label="10 yrs"),),
        sum_assured_min=amount,
        sum_assured_max=amount,
        default_sum_assured=amount,
        default_term="10_yrs",
        min_age=18,
        max_age=60,
        baseline_monthly=Decimal("60.00"),
        riders=riders,
    )


def _rider(code: str) -> Rider:
    return Rider(code=code, name=f"Rider {code}", baseline_monthly=Decimal("5.00"))


def test_story_2_1_list_products_orders_products_and_riders_by_code() -> None:
    catalogue = FakeCatalogue(
        [
            _product("LWL", _rider("R13"), _rider("R12")),
            _product("CFH", _rider("R11"), _rider("R10"), sum_assured=False),
            _product("FSH"),
        ]
    )
    port: ProductCatalogue = catalogue

    products = asyncio.run(list_products(port))

    assert [product.code for product in products] == ["CFH", "FSH", "LWL"]
    assert [rider.code for rider in products[0].riders] == ["R10", "R11"]
    assert [rider.code for rider in products[2].riders] == ["R12", "R13"]
    assert products[1].riders == ()
    # Everything else is passed through unchanged, including a product's null sum assured.
    assert products[0].sum_assured_min is None
    assert products[2].baseline_monthly == Decimal("60.00")
    assert catalogue.calls == 1


def test_story_2_1_list_products_of_an_empty_catalogue_is_empty() -> None:
    assert asyncio.run(list_products(FakeCatalogue([]))) == ()


def test_story_2_1_product_types_are_the_n1_codes() -> None:
    assert [item.value for item in ProductType] == ["life", "life_health", "health"]


# Story 2.3: priced_products, the priced-and-eligible listing.


def _fsh() -> Product:
    # The Ally reference case (epic-2-context.md): FSH baseline 160, min/max age 18-55.
    return Product(
        code="FSH",
        name="FamilyShield Life & Health",
        type=ProductType.LIFE_HEALTH,
        covers_dependents=True,
        policy_terms=(PolicyTerm(code="20_yrs", label="20 yrs"),),
        sum_assured_min=Decimal("200000.00"),
        sum_assured_max=Decimal("600000.00"),
        default_sum_assured=Decimal("300000.00"),
        default_term="20_yrs",
        min_age=18,
        max_age=55,
        baseline_monthly=Decimal("160.00"),
        riders=(
            Rider(
                code="R07",
                name="Maternity & newborn",
                baseline_monthly=Decimal("30.00"),
            ),
        ),
    )


def _cfh() -> Product:
    # CFH: no sum assured, min/max age 18-65, out of FSH's/Ally's own age band 3 (31-35).
    return Product(
        code="CFH",
        name="CareFirst Health",
        type=ProductType.HEALTH,
        covers_dependents=True,
        policy_terms=(PolicyTerm(code="1_yr_renewable", label="1 yr, renewable"),),
        sum_assured_min=None,
        sum_assured_max=None,
        default_sum_assured=None,
        default_term="1_yr_renewable",
        min_age=18,
        max_age=65,
        baseline_monthly=Decimal("45.00"),
        riders=(),
    )


def _lwl_over_60() -> Product:
    # LWL: min age 61, so a 31-year-old is not eligible for it.
    return Product(
        code="LWL",
        name="Legacy Whole Life",
        type=ProductType.LIFE,
        covers_dependents=True,
        policy_terms=(PolicyTerm(code="whole_of_life", label="Whole of life"),),
        sum_assured_min=Decimal("250000.00"),
        sum_assured_max=Decimal("1000000.00"),
        default_sum_assured=Decimal("500000.00"),
        default_term="whole_of_life",
        min_age=61,
        max_age=70,
        baseline_monthly=Decimal("260.00"),
        riders=(),
    )


def test_story_2_3_priced_products_at_a_known_age_prices_ally_through_fsh() -> None:
    catalogue = FakeCatalogue([_fsh(), _cfh(), _lwl_over_60()])

    products = asyncio.run(priced_products(catalogue, 31))

    assert [product.code for product in products] == [
        "CFH",
        "FSH",
        "LWL",
    ]  # FORM-18 (owner decision 2026-09-27): no product is excluded by its age range
    fsh = next(product for product in products if product.code == "FSH")
    assert isinstance(fsh, PricedProduct)
    assert (fsh.monthly, fsh.yearly) == (Decimal("185.22"), Decimal("2111.51"))
    [rider] = fsh.riders
    assert isinstance(rider, PricedRider)
    assert (rider.code, rider.monthly, rider.yearly) == (
        "R07",
        Decimal("34.73"),
        Decimal("395.91"),
    )
    # Every other stored field passes through unchanged.
    assert fsh.sum_assured_min == Decimal("200000.00")
    assert fsh.default_term == "20_yrs"


def test_form_18_priced_products_keeps_products_outside_their_age_range() -> None:
    """Owner decision (owner, 2026-09-27): a product's min_age/max_age no longer hides it."""
    products = asyncio.run(priced_products(FakeCatalogue([_lwl_over_60()]), 31))

    assert [product.code for product in products] == ["LWL"]


def test_story_2_3_priced_products_with_no_age_prices_every_product_at_band_0() -> None:
    products = asyncio.run(
        priced_products(FakeCatalogue([_fsh(), _lwl_over_60()]), None)
    )

    assert [product.code for product in products] == ["FSH", "LWL"]  # nothing excluded
    fsh = next(product for product in products if product.code == "FSH")
    # Band 0's multiplier is 1.05**0 == 1: the baseline price, unchanged (spec Design Notes).
    assert (fsh.monthly, fsh.yearly) == (Decimal("160.00"), Decimal("1824.00"))


def test_story_2_3_priced_products_at_an_age_with_no_band_is_empty() -> None:
    products = asyncio.run(priced_products(FakeCatalogue([_fsh(), _cfh()]), 71))

    assert products == ()


def test_story_2_3_priced_products_orders_products_and_riders_by_code() -> None:
    products = asyncio.run(
        priced_products(FakeCatalogue([_lwl_over_60(), _cfh(), _fsh()]), None)
    )

    assert [product.code for product in products] == ["CFH", "FSH", "LWL"]
