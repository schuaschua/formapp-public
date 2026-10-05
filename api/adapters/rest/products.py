"""``GET /api/products``: the product catalogue for the web Product page (Story 2.1, AD-2), and,
with ``?proposal_id=``, the priced-and-eligible listing for that proposal's insured age (Story 2.3).

The adapter only calls the domain (``list_products``/``priced_products``) and maps the result to
``snake_case`` JSON; the age itself comes from the stored C2 at the proposal's ``created_at``, the
same convention ``resolve_quote`` already uses. Sign-in is enforced by the ``/api/*`` middleware
(Story 1.6); ``current_principal`` is only depended on here for its ``oid``, to check ownership when
``proposal_id`` is given. Another agent's proposal id answers exactly like ``ensure_owned`` (404,
nothing revealed); the bare call (no ``proposal_id``) is unchanged from Story 2.1.
"""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, PlainSerializer

from adapters.db.products import SqlProductCatalogue
from adapters.db.proposals import SqlProposalStore
from adapters.rest.principal import current_principal
from domain.pricing import age_at
from domain.principal import Principal
from domain.products import PricedProduct, Product, list_products, priced_products
from domain.proposals import _date_of_birth, ensure_owned

_CENTS = Decimal("0.01")


def _money_number(value: Decimal) -> float:
    # coding-style.md rule 4: amounts go on the wire as JSON numbers rounded to 2 decimals.
    return float(value.quantize(_CENTS, rounding=ROUND_HALF_UP))


Money = Annotated[Decimal, PlainSerializer(_money_number, return_type=float)]

router = APIRouter()


class PolicyTermOut(BaseModel):
    code: str
    label: str


class RiderOut(BaseModel):
    code: str
    name: str
    baseline_monthly: Money


class ProductOut(BaseModel):
    code: str
    name: str
    type: str
    covers_dependents: bool
    policy_terms: list[PolicyTermOut]
    sum_assured_min: Money | None
    sum_assured_max: Money | None
    default_sum_assured: Money | None
    default_term: str
    min_age: int
    max_age: int
    baseline_monthly: Money
    riders: list[RiderOut]


class PricedRiderOut(BaseModel):
    code: str
    name: str
    monthly: Money
    yearly: Money


class PricedProductOut(BaseModel):
    """Story 2.3's priced-and-eligible product: every stored field ``ProductOut`` has, minus
    ``baseline_monthly``, plus the age-band ``monthly``/``yearly``."""

    code: str
    name: str
    type: str
    covers_dependents: bool
    policy_terms: list[PolicyTermOut]
    sum_assured_min: Money | None
    sum_assured_max: Money | None
    default_sum_assured: Money | None
    default_term: str
    min_age: int
    max_age: int
    monthly: Money
    yearly: Money
    riders: list[PricedRiderOut]


def _product_out(product: Product) -> ProductOut:
    return ProductOut(
        code=product.code,
        name=product.name,
        type=product.type.value,
        covers_dependents=product.covers_dependents,
        policy_terms=[
            PolicyTermOut(code=term.code, label=term.label)
            for term in product.policy_terms
        ],
        sum_assured_min=product.sum_assured_min,
        sum_assured_max=product.sum_assured_max,
        default_sum_assured=product.default_sum_assured,
        default_term=product.default_term,
        min_age=product.min_age,
        max_age=product.max_age,
        baseline_monthly=product.baseline_monthly,
        riders=[
            RiderOut(
                code=rider.code,
                name=rider.name,
                baseline_monthly=rider.baseline_monthly,
            )
            for rider in product.riders
        ],
    )


def _priced_product_out(product: PricedProduct) -> PricedProductOut:
    return PricedProductOut(
        code=product.code,
        name=product.name,
        type=product.type.value,
        covers_dependents=product.covers_dependents,
        policy_terms=[
            PolicyTermOut(code=term.code, label=term.label)
            for term in product.policy_terms
        ],
        sum_assured_min=product.sum_assured_min,
        sum_assured_max=product.sum_assured_max,
        default_sum_assured=product.default_sum_assured,
        default_term=product.default_term,
        min_age=product.min_age,
        max_age=product.max_age,
        monthly=product.monthly,
        yearly=product.yearly,
        riders=[
            PricedRiderOut(
                code=rider.code,
                name=rider.name,
                monthly=rider.monthly,
                yearly=rider.yearly,
            )
            for rider in product.riders
        ],
    )


@router.get("/api/products", response_model=None)
async def get_products(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    proposal_id: Annotated[UUID | None, Query()] = None,
) -> list[ProductOut] | list[PricedProductOut]:
    """Every product with its stored fields and riders, ordered by code; with ``?proposal_id=``,
    only the products eligible for that proposal's insured age, priced at its band (Story 2.3).

    ``response_model=None`` bypasses FastAPI's response-model inference from the ``Union`` return
    type (which would otherwise validate every row against *both* shapes) -- ``jsonable_encoder``
    still calls each returned model's own ``model_dump``, so the ``Money`` serializer still runs.
    """
    catalogue = SqlProductCatalogue(request.app.state.engine)
    if proposal_id is None:
        products = await list_products(catalogue)
        return [_product_out(product) for product in products]

    store = SqlProposalStore(request.app.state.engine)
    proposal = await ensure_owned(store, proposal_id, principal.oid)
    date_of_birth = _date_of_birth(proposal.answers.get("C2", {}).get("value"))
    age = age_at(date_of_birth, proposal.created_at) if date_of_birth else None
    priced = await priced_products(catalogue, age)
    return [_priced_product_out(product) for product in priced]
