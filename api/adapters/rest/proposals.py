"""``POST/GET /api/proposals``, ``GET /api/proposals/:id``, ``GET /api/proposals/:id/schema``,
``PATCH /api/proposals/:id/answers`` and ``POST /api/proposals/:id/lock`` (Stories 1.8, 1.9, 1.10
and 4.4, spine AD-5, AD-6, AD-7, AD-8, AD-12, AD-15, AD-16).

Sign-in is enforced by the ``/api/*`` middleware (Story 1.6); ownership by the domain's
``ensure_owned``, so a proposal that doesn't exist and one owned by someone else answer with the
same 404 (``ProposalNotFoundError``, registered in ``adapters.rest.errors``).

Story 2.2 Part B: ``quote`` is resolved through the catalogue on every read and mapped to JSON
numbers by the ``Money`` serializer (coding-style.md rule 4); it is never stored.

Story 4.4: the lock identity is the caller's per-tab ``X-Session-Id`` (Story 1.4/AD-16); the
``SessionHeaderMiddleware`` already requires it on every non-GET call, so it's read straight off
the request here rather than reinvented.

Story 4.9: ``settings.foundry_model`` is required in the demo deployment (Story 4.5's guard) but
stays optional outside it (local/CI, where the AgentGateway stub is used and no real Foundry
deployment exists) -- a grep-able placeholder stands in for it there rather than making every
other settings fixture in the repo carry a real value.
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel

from adapters.db.products import SqlProductCatalogue
from adapters.db.proposals import SqlProposalStore
from adapters.rest.middleware import SESSION_HEADER
from adapters.rest.principal import current_principal
from adapters.rest.products import Money
from domain.customer_fields import db_columns
from domain.errors import DomainError, ErrorCode
from domain.principal import Principal
from domain.products import ProductCatalogue, list_products
from domain.proposals import (
    Proposal,
    ProposalStatus,
    SubmitResult,
    acquire_lock,
    apply_answers,
    create_draft,
    delete_draft,
    display_name,
    draft_view,
    ensure_owned,
    quote_view,
    resolve_quote,
    submit_proposal,
    validate_proposal,
)
from domain.schema import load_schema, thaw

router = APIRouter()

# Story 4.9: logged on an answer_overrides row when FOUNDRY_MODEL isn't set (local/CI outside the
# demo deployment, where Story 4.5's guard requires it) -- grep-able rather than silently blank.
_MODEL_DEPLOYMENT_NOT_CONFIGURED = "model-deployment-not-configured"


def _session_id(request: Request) -> str:
    """The caller's per-tab lock identity (Story 4.4, AD-16); empty when a GET carries none."""
    return request.headers.get(SESSION_HEADER, "")


class LockOut(BaseModel):
    holder: str
    expires_at: str | None


class QuoteLineOut(BaseModel):
    item: str
    monthly: Money
    yearly: Money


class QuoteOut(BaseModel):
    monthly: Money
    yearly: Money
    lines: list[QuoteLineOut]


class DraftOut(BaseModel):
    """The AD-5 draft wire shape, plus ``display_name``, ``submitted_at`` and ``customer_number``
    (spec assumption: all additive, REST-only -- Story 3.2's read-only workspace strip needs
    ``submitted_at``; FORM-218's strip and the Submitted list need ``customer_number``). ``None``
    until a customer is linked (Story 5.2) or a new one is generated at submit (FORM-218)."""

    id: UUID
    status: str
    schema_version: int
    revision: int
    lock: LockOut
    active: list[str]
    answers: dict[str, Any]
    provenance: dict[str, Any]
    quote: QuoteOut | None
    display_name: str
    submitted_at: datetime | None
    customer_number: str | None


class ProposalSummaryOut(BaseModel):
    id: UUID
    display_name: str
    status: str
    created_at: datetime
    submitted_at: datetime | None
    customer_number: str | None


class FieldErrorOut(BaseModel):
    """One AD-12 field error, the same closed shape ``PATCH .../answers`` already raises on."""

    field: str
    code: str
    message: str


class ValidateOut(BaseModel):
    """``POST /api/proposals/:id/validate``'s body (Story 3.1, AD-12): ``[]`` when clean."""

    errors: list[FieldErrorOut]


class PatchAnswersIn(BaseModel):
    """``PATCH /api/proposals/:id/answers`` body: the diff the web app computed, plus the revision
    it read the draft at (Story 1.10, AD-6)."""

    revision: int
    answers: dict[str, Any]


class LockIn(BaseModel):
    """``POST /api/proposals/:id/lock`` body (Story 4.4, AD-16)."""

    take_over: bool = False


class FeedbackIn(BaseModel):
    """``POST /api/proposals/:id/submit``'s ``feedback`` body (Story 3.3): kept loose (``rating``
    optional, no range) so a missing or out-of-range rating is this story's own
    ``feedback_required`` (AD-12), never FastAPI's generic body-validation shape."""

    rating: int | None = None
    comment: str | None = None


class SubmitIn(BaseModel):
    """``POST /api/proposals/:id/submit`` body (Story 3.3, AD-8): the revision she read the draft
    at, whether she agreed the declaration, and her AI-rating feedback. ``declaration_agreed``
    defaults false, so a caller that omits it is treated the same as an explicit false (spec I/O
    matrix "Missing declaration")."""

    revision: int
    declaration_agreed: bool = False
    feedback: FeedbackIn = FeedbackIn()


def _store(request: Request) -> SqlProposalStore:
    return SqlProposalStore(request.app.state.engine)


def _catalogue(request: Request) -> ProductCatalogue:
    return SqlProductCatalogue(request.app.state.engine)


async def _draft_out(
    proposal: Proposal,
    catalogue: ProductCatalogue,
    session_id: str,
    store: SqlProposalStore,
) -> DraftOut:
    """The draft wire shape with ``quote`` resolved from the catalogue (Story 2.2 Part B),
    ``lock`` relative to the caller's session (Story 4.4), and ``customer_number`` resolved from
    ``customer`` when a customer is linked (FORM-218) -- a single-id batched lookup, same method
    ``list_proposals`` uses for many."""
    view = draft_view(proposal, session_id)
    view["quote"] = quote_view(await resolve_quote(proposal, catalogue))
    numbers = (
        await store.customer_numbers([proposal.customer_id])
        if proposal.customer_id is not None
        else {}
    )
    view["customer_number"] = numbers.get(proposal.customer_id)
    return DraftOut(**view)


@router.post("/api/proposals", status_code=201)
async def create_proposal(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
) -> DraftOut:
    """Create a draft owned by the caller, numbered after her previous drafts (FR10, AD-8)."""
    store = _store(request)
    proposal = await create_draft(store, principal.oid, request.app.state.clock)
    return await _draft_out(proposal, _catalogue(request), _session_id(request), store)


@router.get("/api/proposals")
async def list_proposals(
    request: Request,
    principal: Annotated[Principal, Depends(current_principal)],
    status: Annotated[ProposalStatus, Query()] = ProposalStatus.DRAFT,
) -> list[ProposalSummaryOut]:
    """The caller's own proposals with this status (FR8): newest ``created_at`` first for drafts,
    newest ``submitted_at`` first for submitted proposals (Story 3.2, FR9)."""
    store = _store(request)
    proposals = await store.list_for_owner(principal.oid, status)
    numbers = await store.customer_numbers(
        [proposal.customer_id for proposal in proposals if proposal.customer_id is not None]
    )
    return [
        ProposalSummaryOut(
            id=proposal.id,
            display_name=display_name(proposal),
            status=proposal.status.value,
            created_at=proposal.created_at,
            submitted_at=proposal.submitted_at,
            customer_number=(
                numbers.get(proposal.customer_id)
                if proposal.customer_id is not None
                else None
            ),
        )
        for proposal in proposals
    ]


@router.get("/api/proposals/{proposal_id}")
async def get_proposal(
    request: Request,
    proposal_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
) -> DraftOut:
    """The draft wire shape for a proposal the caller owns; 404 otherwise (FR13, NFR6)."""
    store = _store(request)
    proposal = await ensure_owned(store, proposal_id, principal.oid)
    return await _draft_out(proposal, _catalogue(request), _session_id(request), store)


@router.post("/api/proposals/{proposal_id}/lock")
async def lock_proposal(
    request: Request,
    proposal_id: UUID,
    body: LockIn,
    principal: Annotated[Principal, Depends(current_principal)],
) -> LockOut:
    """Acquire, renew or (with ``take_over``) move the caller's edit lock; 404 for a non-owner or
    unknown id (Story 4.4, AD-16, FR13)."""
    lock = await acquire_lock(
        _store(request),
        proposal_id,
        principal.oid,
        _session_id(request),
        body.take_over,
        request.app.state.clock,
    )
    return LockOut(**lock)


@router.get("/api/proposals/{proposal_id}/schema")
async def get_proposal_schema(
    request: Request,
    proposal_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
) -> dict[str, Any]:
    """The exact schema pinned on this proposal, verbatim; 404 otherwise (Story 1.9, AD-7, FR13)."""
    proposal = await ensure_owned(_store(request), proposal_id, principal.oid)
    return thaw(load_schema(proposal.schema_version))


@router.patch("/api/proposals/{proposal_id}/answers")
async def patch_answers(
    request: Request,
    proposal_id: UUID,
    body: PatchAnswersIn,
    principal: Annotated[Principal, Depends(current_principal)],
) -> DraftOut:
    """Diff, validate and store a human answer edit in one transaction; 404 for a non-owner or
    unknown id, 409 ``stale_revision`` if the draft moved on or ``lock_not_held`` if the caller
    doesn't hold the edit lock, 422 in the closed shape for any field problem (Story 1.10, AD-6,
    AD-12, AD-15; Story 2.3's P1/P2/P3/N5 product checks; Story 4.4, AD-16). Story 4.9: logs every
    human override of a previously non-human answer into ``answer_overrides``, in the same
    transaction, with the caller's ``oid`` and the configured model deployment name (AD-17)."""
    store = _store(request)
    proposal = await ensure_owned(store, proposal_id, principal.oid)
    schema = load_schema(proposal.schema_version)
    clock = request.app.state.clock
    products = await list_products(_catalogue(request))
    session_id = _session_id(request)

    def apply(current: Proposal) -> Proposal | None:
        return apply_answers(
            schema, current, body.revision, body.answers, clock, products, session_id
        )

    updated = await store.update_answers(
        proposal_id,
        body.revision,
        apply,
        model_deployment=(
            request.app.state.settings.foundry_model or _MODEL_DEPLOYMENT_NOT_CONFIGURED
        ),
        overridden_by=principal.oid,
    )
    if updated is None:
        raise DomainError.single(
            "revision", ErrorCode.STALE_REVISION, "Reload the draft."
        )
    return await _draft_out(updated, _catalogue(request), session_id, store)


@router.post("/api/proposals/{proposal_id}/validate")
async def validate_proposal_route(
    request: Request,
    proposal_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
) -> ValidateOut:
    """The read-only whole-proposal check behind the "Submit proposal" button (Story 3.1, AD-7,
    AD-12, AD-15): 404 for a non-owner or unknown id (identical to every other route), otherwise
    always 200 with the AD-12 errors shape -- never a 422, and never touches the stored draft."""
    proposal = await ensure_owned(_store(request), proposal_id, principal.oid)
    schema = load_schema(proposal.schema_version)
    errors = await validate_proposal(schema, proposal, _catalogue(request))
    return ValidateOut(errors=[FieldErrorOut(**error.to_dict()) for error in errors])


@router.post("/api/proposals/{proposal_id}/submit")
async def submit_proposal_route(
    request: Request,
    proposal_id: UUID,
    body: SubmitIn,
    principal: Annotated[Principal, Depends(current_principal)],
) -> DraftOut:
    """Declaration, AI-rating feedback and the real submit (Story 3.3/FORM-21, FR18-20, AD-2, AD-8,
    AD-12, AD-13, AD-16): re-validates the whole proposal, sets D1, upserts ``customer`` from
    C1-C15, records the feedback and marks the proposal submitted, all in one transaction. 404 for
    a non-owner or unknown id (identical to every other route); 409 ``stale_revision``,
    ``lock_not_held`` or ``proposal_submitted``; 422 in the closed AD-12 shape for a missing
    declaration, a missing/out-of-range rating, or any field problem :func:`validate_proposal`
    still finds.
    """
    store = _store(request)
    proposal = await ensure_owned(store, proposal_id, principal.oid)
    schema = load_schema(proposal.schema_version)
    clock = request.app.state.clock
    catalogue = _catalogue(request)
    session_id = _session_id(request)
    customer_columns = db_columns(schema)

    async def apply(current: Proposal) -> SubmitResult | None:
        return await submit_proposal(
            schema,
            current,
            body.revision,
            body.declaration_agreed,
            {"rating": body.feedback.rating, "comment": body.feedback.comment},
            clock,
            catalogue,
            session_id,
            customer_columns,
        )

    updated = await store.submit(proposal_id, body.revision, apply)
    if updated is None:
        raise DomainError.single(
            "revision", ErrorCode.STALE_REVISION, "Reload the draft."
        )
    return await _draft_out(updated, catalogue, session_id, store)


@router.delete("/api/proposals/{proposal_id}", status_code=204)
async def delete_proposal_route(
    request: Request,
    proposal_id: UUID,
    principal: Annotated[Principal, Depends(current_principal)],
) -> Response:
    """Hard-delete a draft (Story FORM-227, owner decision comment 2026-09-27): 404 for a non-owner
    or unknown id (identical to every other route); 409 ``proposal_submitted``, ``turn_in_progress``
    or ``lock_not_held`` -- the same checks as every other write, except delete allows the caller's
    own live lock (or a free/expired one), never only a different session's (``delete_draft``'s own
    ``_lock_blocks_delete``). ``answer_overrides``/``proposal_feedback`` cascade in the same
    transaction (migration 0016); the Foundry ``conversation_id``, if any, is left orphaned, never
    deleted. No MCP tool exposes this (AD-3): REST-only."""
    await delete_draft(
        _store(request),
        proposal_id,
        principal.oid,
        _session_id(request),
        request.app.state.clock,
    )
    return Response(status_code=204)
