"""Proposal creation, ownership, naming and the AD-5 draft wire shape (Story 1.8).

The shared builder later stories extend: 1.9 adds the schema endpoint, 1.10 answer writes, 3.x
submit. Story 4.4 adds the real edit lock (``lock_holder``/``lock_expires_at``, AD-16), keyed by
the caller's per-tab ``X-Session-Id``. ``quote`` (Story 2.2 Part B) is resolved separately by
:func:`resolve_quote`, since it needs the catalogue port; :func:`draft_view` alone always leaves it
null.
"""

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator

from domain.clock import Clock
from domain.customer_fields import ColumnType, DbColumn
from domain.errors import DomainError, ErrorCode, FieldError
from domain.pricing import Quote, age_at, build_quote
from domain.products import Product, ProductCatalogue
from domain.schema import Schema, latest_version, load_schema, questions
from domain.visibility import active_questions, inactive_answer_ids, required_questions

# The lock expires this long after its last acquire/renew (Story 4.4, AD-16); the web app renews
# it every 20s, well inside this window.
LOCK_DURATION = timedelta(seconds=60)

# Story 4.5, AC1/AD-4: a real chat turn's own safety window -- distinct from LOCK_DURATION, which
# is the human tab's renew-every-20s heartbeat. begin_turn (Story 4.3's test-only plumbing) still
# uses LOCK_DURATION for its own fixture convenience; start_chat_turn -- the seam a real chat POST
# actually goes through -- uses this one.
AI_TURN_SAFETY_WINDOW = timedelta(minutes=5)

# The AI never loses the lock to a take-over (Story 4.5 sets this holder; refused here already so
# the check has one place to live before that story adds any AI code).
_AI_HOLDER = "ai"


class ProposalStatus(StrEnum):
    """A proposal's lifecycle state (spine AD-8)."""

    DRAFT = "draft"
    SUBMITTED = "submitted"


@dataclass(frozen=True, slots=True)
class Proposal:
    """A stored proposal row. ``answers`` is the AD-6 shape: ``{qid: {value, source, updated_at}}``.

    ``lock_holder`` is a session id or ``"ai"``, and ``lock_expires_at`` when it was last
    acquired/renewed until (Story 4.4, AD-16); both are ``None`` until the first
    ``POST .../lock`` acquires it. ``current_turn_id`` is the ``tid`` of the turn token currently
    bound to the proposal while ``lock_holder`` is ``"ai"`` (Story 4.3, AD-4); ``None`` until a
    turn begins.

    ``submitted_at`` is ``None`` until the real submit endpoint (Story 3.3/FORM-21) sets it; this
    story (3.2) only reads and honours it -- test data sets it directly (spec Intent).
    """

    id: UUID
    customer_id: UUID | None
    owner_oid: str
    owner_seq: int
    schema_version: int
    status: ProposalStatus
    revision: int
    conversation_id: str | None
    answers: Mapping[str, Mapping[str, Any]]
    created_at: datetime
    updated_at: datetime
    lock_holder: str | None
    lock_expires_at: datetime | None
    current_turn_id: UUID | None
    submitted_at: datetime | None


class ProposalNotFoundError(LookupError):
    """No proposal with this id exists, or it isn't owned by the caller (spine AD-8, FR13, NFR6)."""

    def __init__(self, proposal_id: object) -> None:
        super().__init__(f"No proposal {proposal_id!r} for this caller.")
        self.proposal_id = proposal_id


class ProposalStore(Protocol):
    """Port to the stored proposals; implemented by the db adapter."""

    async def create(
        self,
        *,
        owner_oid: str,
        schema_version: int,
        answers: Mapping[str, Mapping[str, Any]],
        now: datetime,
    ) -> Proposal:
        """Insert a new draft for ``owner_oid``, allocating the next ``owner_seq`` for her, with
        ``answers`` (the AD-15 create-time defaults) already applied."""
        ...

    async def get(self, proposal_id: UUID) -> Proposal | None:
        """Return the proposal, or None if no row has this id."""
        ...

    async def list_for_owner(
        self, owner_oid: str, status: ProposalStatus
    ) -> Sequence[Proposal]:
        """Return ``owner_oid``'s proposals with this status, newest ``created_at`` first."""
        ...

    async def update_answers(
        self,
        proposal_id: UUID,
        expected_revision: int,
        apply: Callable[["Proposal"], "Proposal | None"],
        *,
        model_deployment: str,
        overridden_by: str,
    ) -> "Proposal | None":
        """Lock the row (``SELECT ... FOR UPDATE``), call ``apply(current)`` in that same
        transaction and write its result. Returns ``None`` -- writing nothing -- when ``apply``
        itself returns ``None`` (a stale ``expected_revision``, mapped by the caller to
        ``stale_revision``) or the row no longer exists (Story 1.10, AD-6).

        Story 4.9 (AD-17): also logs every human override of a previously non-human answer into
        ``answer_overrides``, on this same connection/transaction, tagged with ``model_deployment``
        (the configured Foundry deployment name) and ``overridden_by`` (the caller's ``oid``)."""
        ...

    async def acquire_lock(
        self,
        proposal_id: UUID,
        session_id: str,
        now: datetime,
        expires_at: datetime,
        take_over: bool,
    ) -> "Proposal | None":
        """One atomic CAS (Story 4.4, AD-16): move the lock to ``session_id`` when it is free
        (never held, or ``lock_expires_at`` is before ``now``), already ``session_id``'s own
        (a renew), or -- when ``take_over`` -- held live by any other session (never ``ai``).
        Returns the row after the attempt either way, so the caller can report the relative
        holder whether or not this call actually moved the lock; ``None`` only when the proposal
        itself doesn't exist."""
        ...

    async def apply_agent_patch(
        self,
        proposal_id: UUID,
        apply: Callable[["Proposal"], "Proposal | None"],
    ) -> "Proposal | None":
        """Like ``update_answers``, but with no client-supplied ``expected_revision`` (Story 4.3):
        lock the row (``SELECT ... FOR UPDATE``), call ``apply(current)`` in that same
        transaction and write its result with no precondition on the ``UPDATE``'s own ``WHERE`` --
        the row lock is the only guard. Returns ``None`` when ``apply`` itself returns ``None`` or
        the row no longer exists; propagates whatever ``apply`` raises (the transaction rolls
        back)."""
        ...

    async def set_turn(
        self,
        proposal_id: UUID,
        *,
        lock_holder: str | None,
        lock_expires_at: datetime | None,
        current_turn_id: UUID | None,
    ) -> "Proposal | None":
        """Write the lock/turn columns directly, with no CAS and no precondition (Story 4.3):
        test-only plumbing for :func:`begin_turn`/:func:`end_turn` -- no REST route calls this;
        Story 4.5's chat adapter is what sets these for real. ``None`` only when the proposal
        doesn't exist."""
        ...

    async def begin_chat_turn(
        self,
        proposal_id: UUID,
        apply: Callable[["Proposal"], "Proposal"],
    ) -> "Proposal | None":
        """The one atomic seam that starts a real chat turn (Story 4.5, AD-4, AD-9, AD-16): lock
        the row (``SELECT ... FOR UPDATE``), call ``apply(current)`` in that same transaction and
        write only its ``lock_holder``/``lock_expires_at``/``current_turn_id`` -- never
        ``revision``/``answers`` -- so a second ``POST /chat`` racing the first sees the first's
        ``lock_holder = "ai"`` already committed and ``apply`` (:func:`start_chat_turn`) raises
        ``turn_in_progress`` instead of both winning. Whatever ``apply`` raises (``DomainError``:
        ``proposal_submitted``, ``turn_in_progress``, ``lock_not_held``) propagates and rolls the
        transaction back, writing nothing. ``None`` only when the proposal doesn't exist."""
        ...

    async def ensure_conversation(
        self, proposal_id: UUID, conversation_id: str
    ) -> str:
        """The AD-9 conditional ``UPDATE ... WHERE conversation_id IS NULL`` (Story 4.5): stores
        ``conversation_id`` only if the proposal has none yet, then returns whichever conversation
        id is actually stored -- ``conversation_id`` itself on a win, or the one a racing turn
        already stored on a loss (the race loser drops its own and reuses the stored one)."""
        ...

    async def link_customer(
        self,
        proposal_id: UUID,
        customer_id: UUID,
        apply: Callable[["Proposal", Mapping[str, Any] | None], "Proposal"],
    ) -> "Proposal | None":
        """One transaction (Story 5.2, AD-13): lock the proposal row (``SELECT ... FOR UPDATE``),
        read the ``customer`` row by ``customer_id`` on the same connection (``None`` if no such
        row), call ``apply(current, customer_row)`` and write its result's
        ``revision``/``answers``/``customer_id``/``updated_at``. Whatever ``apply`` raises
        (``DomainError``: ``lock_not_held``, ``proposal_submitted``, ``invalid_value`` on an
        unknown customer) propagates and rolls the transaction back, writing nothing -- so an
        unknown ``customer_id`` and a concurrent edit are both caught atomically. ``None`` only
        when the proposal doesn't exist.
        """
        ...

    async def submit(
        self,
        proposal_id: UUID,
        expected_revision: int,
        apply: Callable[["Proposal"], Awaitable["SubmitResult | None"]],
    ) -> "Proposal | None":
        """Lock the row (``SELECT ... FOR UPDATE``), ``await apply(current)`` in that same
        transaction, then write its result: the proposal's own update, the ``customer`` upsert
        (insert when this proposal had no ``customer_id`` yet, update otherwise) and the
        ``proposal_feedback`` insert, all in one transaction (Story 3.3, AD-8, AD-13). Returns
        ``None`` -- writing nothing -- when ``apply`` itself returns ``None`` (a stale
        ``expected_revision``, mapped by the caller to ``stale_revision``) or the row no longer
        exists; propagates whatever ``apply`` raises (the transaction rolls back), same as
        :meth:`apply_agent_patch`."""
        ...

    async def delete(self, proposal_id: UUID, owner_oid: str) -> bool:
        """Hard-delete the ``proposal`` row in one transaction (Story FORM-227, migration 0016):
        ``answer_overrides`` and ``proposal_feedback`` cascade with it at the database level, never
        a second application-level delete step. The caller (:func:`delete_draft`) has already run
        every domain check (ownership, submitted, turn, lock); this is the one write itself.
        Returns ``False`` when no row matched ``proposal_id`` (already gone -- the caller maps
        that to :class:`ProposalNotFoundError`), ``True`` once it's gone."""
        ...


async def create_draft(store: ProposalStore, owner_oid: str, clock: Clock) -> Proposal:
    """Create a new draft for ``owner_oid``, pinned to the latest schema version (AD-7, AD-8).

    Starts with the AD-15 defaults already applied -- every active, unanswered ``x-simple``
    question (Y3 and H7-H14 on the released schema) is "No" at ``source: default`` -- at
    revision 0 (FR10, FR34).
    """
    schema_version = latest_version()
    now = clock.now()
    answers = _recompute(load_schema(schema_version), {}, now)
    return await store.create(
        owner_oid=owner_oid, schema_version=schema_version, answers=answers, now=now
    )


async def ensure_owned(
    store: ProposalStore, proposal_id: UUID, owner_oid: str
) -> Proposal:
    """Return the proposal if ``owner_oid`` owns it; raise ``ProposalNotFoundError`` otherwise.

    The one check every proposal route uses (spine AD-8, FR13, NFR6): a proposal owned by someone
    else and one that doesn't exist raise the identical error, so a caller can't tell them apart.
    """
    proposal = await store.get(proposal_id)
    if proposal is None or proposal.owner_oid != owner_oid:
        raise ProposalNotFoundError(proposal_id)
    return proposal


def relative_holder(holder: str | None, session_id: str) -> str:
    """The lock holder relative to the caller (Story 4.4, AD-16): ``"you"`` when nobody holds it
    or she does, ``"ai"`` when the agent does, ``"other_session"`` for any other session. The
    caller passes ``None`` for an expired lock, since expired is free (spec Intent)."""
    if holder is None or holder == session_id:
        return "you"
    if holder == _AI_HOLDER:
        return "ai"
    return "other_session"


def lock_view(proposal: Proposal, session_id: str) -> dict[str, Any]:
    """The AD-5 ``lock`` wire shape, relative to the caller (Story 4.4)."""
    return {
        "holder": relative_holder(proposal.lock_holder, session_id),
        "expires_at": _iso(proposal.lock_expires_at)
        if proposal.lock_expires_at is not None
        else None,
    }


async def acquire_lock(
    store: ProposalStore,
    proposal_id: UUID,
    owner_oid: str,
    session_id: str,
    take_over: bool,
    clock: Clock,
) -> dict[str, Any]:
    """``POST /api/proposals/:id/lock`` (Story 4.4, AD-16): acquire, renew or take over the
    caller's edit lock, keyed by her per-tab ``X-Session-Id``. 404s the same as any other proposal
    route for an unowned or unknown id (FR13, NFR6). A live lock held by another session blocks a
    plain acquire; ``take_over`` moves it from another session but never from ``ai`` (Story 4.5).
    An expired lock -- ``lock_expires_at`` in the past -- is free, whoever it last belonged to.
    """
    await ensure_owned(store, proposal_id, owner_oid)
    now = clock.now()
    updated = await store.acquire_lock(
        proposal_id, session_id, now, now + LOCK_DURATION, take_over
    )
    if updated is None:
        # The row vanished between ensure_owned and the CAS (no code path deletes proposals, but
        # 404 is still the right shape if it somehow did).
        raise ProposalNotFoundError(proposal_id)
    return lock_view(updated, session_id)


async def begin_turn(
    store: ProposalStore, proposal_id: UUID, clock: Clock, tid: UUID | None = None
) -> Proposal | None:
    """Bind ``proposal_id`` to a fresh AI turn: ``lock_holder = "ai"``, ``lock_expires_at`` a
    :data:`LOCK_DURATION` window from now, ``current_turn_id`` a fresh ``tid`` (Story 4.3, AD-4).

    Test-only plumbing -- no REST route calls this; :func:`domain.turn_tokens.issue_turn_token`
    mints the token this same ``tid`` must match, and Story 4.5's chat adapter
    (:func:`start_chat_turn`, called atomically through ``ProposalStore.begin_chat_turn``) is what
    actually starts a turn in production. ``tid`` is a fresh UUIDv4 unless a caller passes one
    (Story 4.5's own test support threads the token's own ``tid`` through, the same way
    :func:`start_chat_turn` does for real). Returns ``None`` if the proposal doesn't exist.
    """
    now = clock.now()
    return await store.set_turn(
        proposal_id,
        lock_holder=_AI_HOLDER,
        lock_expires_at=now + LOCK_DURATION,
        current_turn_id=tid if tid is not None else uuid4(),
    )


async def end_turn(
    store: ProposalStore,
    proposal_id: UUID,
    *,
    lock_holder: str | None = None,
    lock_expires_at: datetime | None = None,
) -> Proposal | None:
    """Clear a proposal's AI turn (Story 4.3): ``current_turn_id`` always clears. By default the
    lock is freed entirely (``lock_holder=None``, this function's original test-only-plumbing
    behaviour); Story 4.5's chat adapter passes ``lock_holder=<the session that started the
    turn>`` and a fresh ``lock_expires_at``, so a finished chat turn hands the edit lock back to
    the human session that started it (AC1, AD-4, AD-16) instead of freeing it. Returns ``None``
    if the proposal doesn't exist."""
    return await store.set_turn(
        proposal_id,
        lock_holder=lock_holder,
        lock_expires_at=lock_expires_at,
        current_turn_id=None,
    )


_TURN_IN_PROGRESS_MESSAGE = (
    "The AI is already replying to this proposal. Wait for it to finish."
)


def _turn_running(proposal: Proposal, now: datetime) -> bool:
    """Whether an AI turn is already live on ``proposal`` (Story 4.5, AD-9): the lock is held by
    ``ai`` and its safety expiry hasn't passed."""
    return (
        proposal.lock_holder == _AI_HOLDER
        and proposal.lock_expires_at is not None
        and proposal.lock_expires_at >= now
    )


def start_chat_turn(
    proposal: Proposal, session_id: str, tid: UUID, clock: Clock
) -> Proposal:
    """The pure step behind ``POST /api/proposals/:id/chat`` (Story 4.5, AC1, AC6, AC7, AC8, AD-4,
    AD-9, AD-16): raises ``DomainError`` -- ``proposal_submitted``, ``turn_in_progress`` (another
    turn is already running; checked before the lock, since a live AI turn already means the
    caller's own session can't hold it either) or ``lock_not_held`` (the caller's session doesn't
    hold a live lock) -- and changes nothing on any of the three; otherwise returns ``proposal``
    with the lock moved to ``ai``, a fresh :data:`AI_TURN_SAFETY_WINDOW` safety expiry, and
    ``current_turn_id`` bound to ``tid`` -- the exact ``tid`` :func:`domain.turn_tokens.issue_turn_token`
    minted for this same turn, so the stored turn and the token agree (AD-4).

    The caller (``adapters.chat.turns.open_chat_turn``) applies this atomically inside one
    row-locked transaction (``ProposalStore.begin_chat_turn``), so two chat ``POST``s racing each
    other can't both win.
    """
    now = clock.now()
    if proposal.status is ProposalStatus.SUBMITTED:
        raise DomainError.single(
            "proposal", ErrorCode.PROPOSAL_SUBMITTED, _PROPOSAL_SUBMITTED_MESSAGE
        )
    if _turn_running(proposal, now):
        raise DomainError.single(
            "turn", ErrorCode.TURN_IN_PROGRESS, _TURN_IN_PROGRESS_MESSAGE
        )
    if not _lock_held_by(proposal, session_id, now):
        raise DomainError.single(
            "lock", ErrorCode.LOCK_NOT_HELD, _LOCK_NOT_HELD_MESSAGE
        )
    return replace(
        proposal,
        lock_holder=_AI_HOLDER,
        lock_expires_at=now + AI_TURN_SAFETY_WINDOW,
        current_turn_id=tid,
    )


_LOCK_NOT_HELD_MESSAGE = (
    "This proposal is being edited in another window. Reload to take over."
)

_PROPOSAL_SUBMITTED_MESSAGE = (
    "This proposal has already been submitted and can't be changed."
)

_SIMPLE_DEFAULT_VALUE = "No"

_RANGE_KEYWORDS = frozenset(
    {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum"}
)

_UNKNOWN_FIELD_MESSAGE = "This isn't a question on this proposal."
_INACTIVE_FIELD_MESSAGE = "This question isn't showing on the form right now."
_CANNOT_CLEAR_MESSAGE = "This answer can't be cleared."


def _iso(moment: datetime) -> str:
    """ISO 8601 UTC, ``Z``-suffixed (coding-style.md rule 5)."""
    return moment.isoformat().replace("+00:00", "Z")


def _default_eligible_ids(schema: Schema) -> frozenset[str]:
    """The ids ``x-simple`` implies ``x-fill: default`` for, derived from the schema every time
    (spec assumption: never a hardcoded list, the drift earlier stories' reviews flagged)."""
    return frozenset(
        question_id
        for question_id, question in questions(schema).items()
        if question.get("x-fill") == "default"
    )


def _recompute(
    schema: Schema, answers: Mapping[str, Mapping[str, Any]], now: datetime
) -> dict[str, Mapping[str, Any]]:
    """The AD-15 post-write step, reused for creation too: drop the answers to questions the
    active set no longer includes (never D1, which is never active), then default every active,
    unanswered ``x-simple`` question to "No" at ``source: default`` -- never overwriting an
    answer already there, whatever its source.
    """
    plain = {question_id: entry.get("value") for question_id, entry in answers.items()}
    inactive_ids = inactive_answer_ids(schema, plain)
    kept: dict[str, Mapping[str, Any]] = {
        question_id: entry
        for question_id, entry in answers.items()
        if question_id not in inactive_ids
    }
    active = active_questions(schema, plain)
    for question_id in _default_eligible_ids(schema):
        if question_id in active and question_id not in kept:
            kept[question_id] = {
                "value": _SIMPLE_DEFAULT_VALUE,
                "source": "default",
                "updated_at": _iso(now),
            }
    return kept


def _is_choice_shaped(question: Mapping[str, Any]) -> bool:
    """Yes/no, single-choice and multi-choice questions: the ones ``null`` can never clear (AD-6)."""
    return "enum" in question or question.get("type") == "array"


def _code_for(keyword: str) -> ErrorCode:
    if keyword == "format":
        return ErrorCode.INVALID_FORMAT
    if keyword in _RANGE_KEYWORDS:
        return ErrorCode.OUT_OF_RANGE
    return ErrorCode.INVALID_VALUE


def _schema_error_message(
    question: Mapping[str, Any], code: ErrorCode, keyword: str
) -> str:
    if code is ErrorCode.OUT_OF_RANGE:
        # N2/N5 use exclusiveMinimum with no minimum (a budget/coverage amount must be > 0), so
        # fall back to the exclusive bound: still a plain-English number, just not the exact
        # boundary's inclusivity.
        lower = question.get("minimum", question.get("exclusiveMinimum"))
        upper = question.get("maximum", question.get("exclusiveMaximum"))
        return f"Enter a value between {lower} and {upper}."
    if code is ErrorCode.INVALID_FORMAT:
        return (
            "Enter a valid date."
            if question.get("format") == "date"
            else "Enter a valid email address."
        )
    if keyword == "minItems":
        return "Choose at least one option."
    if keyword == "uniqueItems":
        return "Choose each option only once."
    if "enum" in question:
        return "Choose one of the listed options."
    return "Enter a valid answer."


def _c2_age_error(
    question: Mapping[str, Any], value: str, now: datetime
) -> FieldError | None:
    """C2's domain check on top of its plain ``format: date`` (spec assumption): a valid date whose
    age at ``now`` falls outside ``x-age-range`` is ``out_of_range``, worded from that range."""
    age_range = question.get("x-age-range", {})
    min_age, max_age = age_range.get("min"), age_range.get("max")
    age = age_at(date.fromisoformat(value), now)
    if (min_age is not None and age < min_age) or (
        max_age is not None and age > max_age
    ):
        earliest = now.year - max_age if max_age is not None else None
        latest = now.year - min_age if min_age is not None else None
        return FieldError(
            "C2",
            ErrorCode.OUT_OF_RANGE,
            f"Enter a date between {earliest} and {latest}",
        )
    return None


def _product_for(products: Sequence[Product], code: object) -> Product | None:
    """The stored product this code names, or ``None`` for anything else (unset, unknown, or not
    a string) -- one lookup shared by the P1 exists-check and every P2/P3/N5 sibling check."""
    if not isinstance(code, str):
        return None
    return next((product for product in products if product.code == code), None)


def _selected_product(
    merged_plain: Mapping[str, Any], products: Sequence[Product]
) -> Product | None:
    """P1's *merged* (current + this PATCH's incoming) product, or ``None`` when P1 is unset or
    unknown -- the P2/P3/N5 checks all skip their own check in that case (spec Design Notes,
    epic-2-context.md "If P1 is not set, P3 and N5 are not checked against a product")."""
    return _product_for(products, merged_plain.get("P1"))


_UNKNOWN_PRODUCT_MESSAGE = "Choose one of the listed products."
_FOREIGN_RIDER_MESSAGE = "Choose only this product's riders."
_NOT_A_TERM_MESSAGE = "Choose one of this product's terms."
_NO_SUM_ASSURED_MESSAGE = "This product has no sum assured to set."


def _p1_error(
    value: Any,
    merged_plain: Mapping[str, Any],
    products: Sequence[Product],
    now: datetime,
) -> FieldError | None:
    """P1 must name a stored product (else ``invalid_value``); once C2 (merged) is a real date of
    birth, the insured's age at ``now`` -- the caller passes ``proposal.created_at``, the moment
    pricing and the eligible-product list also use -- must fall in that product's range (else
    ``out_of_range``).
    No C2 yet: only the exists-check runs (epic-2-context.md)."""
    product = _product_for(products, value)
    if product is None:
        return FieldError("P1", ErrorCode.INVALID_VALUE, _UNKNOWN_PRODUCT_MESSAGE)
    # Owner decision (owner, 2026-09-27): no product age-range check; any stored product is valid.
    return None


def _p2_error(
    value: Any, merged_plain: Mapping[str, Any], products: Sequence[Product]
) -> FieldError | None:
    """Every P2 code must belong to P1's (merged) product (else ``invalid_value``)."""
    product = _selected_product(merged_plain, products)
    if product is None:
        return None
    rider_codes = {rider.code for rider in product.riders}
    codes = value if isinstance(value, list) else []
    if any(code not in rider_codes for code in codes):
        return FieldError("P2", ErrorCode.INVALID_VALUE, _FOREIGN_RIDER_MESSAGE)
    return None


def _p3_error(
    value: Any, merged_plain: Mapping[str, Any], products: Sequence[Product]
) -> FieldError | None:
    """P3 must be one of P1's (merged) product's terms (else ``invalid_value``)."""
    product = _selected_product(merged_plain, products)
    if product is None:
        return None
    term_codes = {term.code for term in product.policy_terms}
    if value not in term_codes:
        return FieldError("P3", ErrorCode.INVALID_VALUE, _NOT_A_TERM_MESSAGE)
    return None


def _n5_error(
    value: Any, merged_plain: Mapping[str, Any], products: Sequence[Product]
) -> FieldError | None:
    """N5 must be within P1's (merged) product's sum-assured range (else ``out_of_range``); a
    product with no sum assured (CFH) rejects any N5 at all (``invalid_value``). Decimal(str(...)),
    never float, for the comparison (coding-style.md rule 4)."""
    product = _selected_product(merged_plain, products)
    if product is None:
        return None
    if product.sum_assured_min is None or product.sum_assured_max is None:
        return FieldError("N5", ErrorCode.INVALID_VALUE, _NO_SUM_ASSURED_MESSAGE)
    amount = Decimal(str(value))
    if not (product.sum_assured_min <= amount <= product.sum_assured_max):
        return FieldError(
            "N5",
            ErrorCode.OUT_OF_RANGE,
            f"Enter an amount between {product.sum_assured_min} and {product.sum_assured_max}.",
        )
    return None


def _schema_value_error(
    question_id: str, question: Mapping[str, Any], value: Any
) -> FieldError | None:
    """``value``'s own ``jsonschema`` subschema check for one question (shared by ``_answer_error``
    -- a PATCH's live write validation -- and ``validate_proposal``'s whole-proposal check)."""
    validator = Draft202012Validator(
        question, format_checker=Draft202012Validator.FORMAT_CHECKER
    )
    schema_errors = list(validator.iter_errors(value))
    if not schema_errors:
        return None
    keyword = str(schema_errors[0].validator)
    code = _code_for(keyword)
    return FieldError(question_id, code, _schema_error_message(question, code, keyword))


def _answer_error(
    question_id: str,
    question: Mapping[str, Any] | None,
    value: Any,
    active_after: frozenset[str],
    merged_plain: Mapping[str, Any],
    products: Sequence[Product],
    age_moment: datetime,
) -> FieldError | None:
    """One incoming field's error, in AD-12's short-circuit order (spec Design Notes): unknown,
    then inactive (against the set computed *after* merging this PATCH's diff), then null on a
    choice-shaped question, then the question's own ``jsonschema`` subschema, then C2's age check
    or the Story 2.3 P1/P2/P3/N5 product checks (Story 2.3: checked only on an incoming field,
    against the merged current+incoming answers, never retroactively on a stored one this write
    didn't touch). Ages are measured at ``age_moment`` (the proposal's ``created_at``).
    """
    if question is None:
        return FieldError(question_id, ErrorCode.UNKNOWN_FIELD, _UNKNOWN_FIELD_MESSAGE)
    if question_id not in active_after:
        return FieldError(
            question_id, ErrorCode.INACTIVE_FIELD, _INACTIVE_FIELD_MESSAGE
        )
    if value is None:
        if _is_choice_shaped(question):
            return FieldError(
                question_id, ErrorCode.INVALID_VALUE, _CANNOT_CLEAR_MESSAGE
            )
        return None
    error = _schema_value_error(question_id, question, value)
    if error is not None:
        return error
    if question_id == "C2":
        return _c2_age_error(question, value, age_moment)
    if question_id == "P1":
        return _p1_error(value, merged_plain, products, age_moment)
    if question_id == "P2":
        return _p2_error(value, merged_plain, products)
    if question_id == "P3":
        return _p3_error(value, merged_plain, products)
    if question_id == "N5":
        return _n5_error(value, merged_plain, products)
    return None


def _lock_held_by(proposal: Proposal, session_id: str, now: datetime) -> bool:
    """Whether ``session_id`` currently holds the write lock (Story 4.4, AD-16): the stored
    holder must be exactly this session, and its lock not yet expired -- an expired lock is free,
    never still "held" by the session that let it lapse (spec Intent). The boundary matches the
    CAS's own freeness check (``lock_expires_at < now`` is free): still held at the exact expiry
    instant, so the two never disagree."""
    return (
        proposal.lock_holder == session_id
        and proposal.lock_expires_at is not None
        and proposal.lock_expires_at >= now
    )


def _lock_blocks_delete(proposal: Proposal, session_id: str, now: datetime) -> bool:
    """Whether a live lock blocks *deleting* ``proposal`` (Story FORM-227) -- contrast with
    :func:`_lock_held_by`, which requires the caller herself to hold it: this is true only when a
    *different* session's lock is still live. ``None`` (never acquired), an expired lock, or the
    caller's own live lock never block a delete -- a free or self-held lock has nothing left to
    protect from the one agent about to remove the row anyway."""
    return (
        proposal.lock_holder is not None
        and proposal.lock_holder != session_id
        and proposal.lock_expires_at is not None
        and proposal.lock_expires_at >= now
    )


async def delete_draft(
    store: ProposalStore,
    proposal_id: UUID,
    owner_oid: str,
    session_id: str,
    clock: Clock,
) -> None:
    """``DELETE /api/proposals/:id`` (Story FORM-227, owner decision comment 2026-09-27): hard-
    delete a draft the caller owns, never a submitted proposal (AD-2, AD-8). Same checks as every
    other write, in the same order: :func:`ensure_owned` (404 for an unowned or unknown id, FR13,
    NFR6), ``proposal_submitted`` once submitted, ``turn_in_progress`` while an AI turn is live
    (:func:`_turn_running`, checked before the lock -- a live AI turn already means the caller's own
    session can't hold it either, same reasoning as :func:`start_chat_turn`), then
    ``lock_not_held`` only when a *different* session's live lock would be broken by the delete
    (:func:`_lock_blocks_delete` -- unlike every write above, a delete is allowed when the lock is
    free or already the caller's own). On success: :meth:`ProposalStore.delete` removes the row --
    ``answer_overrides``/``proposal_feedback`` cascade with it in the same transaction (migration
    0016) -- and raises :class:`ProposalNotFoundError` itself if the row had already vanished
    between the ``ensure_owned`` read and this call (never expected in practice, since nothing else
    deletes a proposal, but the same defensive shape :func:`acquire_lock` already uses). The
    Foundry ``conversation_id``, if any, is never deleted here -- it is simply left orphaned.
    """
    proposal = await ensure_owned(store, proposal_id, owner_oid)
    if proposal.status is ProposalStatus.SUBMITTED:
        raise DomainError.single(
            "proposal", ErrorCode.PROPOSAL_SUBMITTED, _PROPOSAL_SUBMITTED_MESSAGE
        )
    now = clock.now()
    if _turn_running(proposal, now):
        raise DomainError.single(
            "turn", ErrorCode.TURN_IN_PROGRESS, _TURN_IN_PROGRESS_MESSAGE
        )
    if _lock_blocks_delete(proposal, session_id, now):
        raise DomainError.single(
            "lock", ErrorCode.LOCK_NOT_HELD, _LOCK_NOT_HELD_MESSAGE
        )
    deleted = await store.delete(proposal_id, owner_oid)
    if not deleted:
        raise ProposalNotFoundError(proposal_id)


class TurnClaims(Protocol):
    """Structural stand-in for ``domain.turn_tokens.TurnTokenClaims`` (Story 4.3): this module has
    no dependency on the JWT layer, only on the fresh-per-turn ``tid`` a decoded token carries.

    A read-only property (not a plain attribute) so a frozen dataclass -- whose fields are
    read-only -- structurally satisfies it under mypy's protocol variance rules."""

    @property
    def tid(self) -> UUID: ...


def turn_bound(proposal: Proposal, claims: TurnClaims, now: datetime) -> bool:
    """Whether ``claims`` still binds the caller to this proposal's current AI turn (Story 4.3,
    AD-4, security.md rule 36): mirrors :func:`_lock_held_by`, but for the ``ai`` holder and its
    ``tid`` rather than a human session id -- the lock must be held by ``"ai"``, not yet expired,
    and this exact turn (``current_turn_id``) still the one the token names. A stale ``tid`` (an
    earlier turn's token replayed after a new one began) is never bound, even while ``ai`` still
    holds the lock."""
    return (
        proposal.lock_holder == _AI_HOLDER
        and proposal.lock_expires_at is not None
        and proposal.lock_expires_at >= now
        and proposal.current_turn_id == claims.tid
    )


def apply_answers(
    schema: Schema,
    proposal: Proposal,
    expected_revision: int,
    incoming: Mapping[str, Any],
    clock: Clock,
    products: Sequence[Product],
    session_id: str,
) -> Proposal | None:
    """Validate and store one PATCH's diff in a pure step (Story 1.10, AD-6, AD-12, AD-15, Story
    2.3's P1/P2/P3/N5 product checks, and the Story 4.4 lock check, AD-16).

    Returns ``None`` on a stale ``expected_revision``: the caller maps that to ``stale_revision``
    and writes nothing. Raises ``DomainError`` -- ``proposal_submitted`` once the proposal has been
    submitted (Story 3.2, AD-2, AD-8: the one shared write path every adapter is meant to call
    through), ``lock_not_held`` when ``session_id`` isn't the live lock holder, or any field
    problem (unknown, inactive, or failing its own validation -- schema-level, C2's age range, or
    Story 2.3's P1/P2/P3/N5 product checks), at most one error per field -- and writes nothing
    either way (AD-12). A write is checked only on the fields it carries -- looping over
    ``incoming.items()`` only -- so a C2 or P1 change is always accepted even when it makes a
    *stored* P1/P2/P3/N5 answer stale; that whole-proposal re-check is Story 3.1's job. On success:
    only the incoming values that actually changed (Python ``==``) are (re)stored at
    ``source: human``, the rest keep their stored ``source``/``updated_at``; the active set is
    then recomputed (inactive answers dropped, never D1; unanswered active ``x-simple`` questions
    defaulted); and ``revision`` becomes ``expected_revision + 1``.
    """
    if proposal.revision != expected_revision:
        return None

    if proposal.status is ProposalStatus.SUBMITTED:
        # A submitted proposal has no meaningful lock state to check (spec Code Map): this runs
        # before the lock check below, whatever session_id or the stored lock_holder say.
        raise DomainError.single(
            "proposal", ErrorCode.PROPOSAL_SUBMITTED, _PROPOSAL_SUBMITTED_MESSAGE
        )

    now = clock.now()
    if not _lock_held_by(proposal, session_id, now):
        raise DomainError.single(
            "lock", ErrorCode.LOCK_NOT_HELD, _LOCK_NOT_HELD_MESSAGE
        )

    props = questions(schema)
    current_plain = {
        question_id: entry.get("value")
        for question_id, entry in proposal.answers.items()
    }
    merged_plain = {**current_plain, **incoming}
    active_after = active_questions(schema, merged_plain)

    errors: list[FieldError] = []
    for question_id, value in incoming.items():
        error = _answer_error(
            question_id,
            props.get(question_id),
            value,
            active_after,
            merged_plain,
            products,
            # Every age check -- here, in validate_proposal and in pricing -- is measured at the
            # proposal's creation, so a birthday mid-draft can't make them disagree.
            proposal.created_at,
        )
        if error is not None:
            errors.append(error)
    if errors:
        raise DomainError(errors)

    answers = dict(proposal.answers)
    for question_id, value in incoming.items():
        stored = answers.get(question_id)
        if stored is not None and stored.get("value") == value:
            continue  # a no-op: source/updated_at stay exactly as they were
        answers[question_id] = {
            "value": value,
            "source": "human",
            "updated_at": _iso(now),
        }

    return replace(
        proposal,
        revision=expected_revision + 1,
        answers=_recompute(schema, answers, now),
        updated_at=now,
    )


_NOT_AGENT_WRITABLE_MESSAGE = "The AI agent can't set this field."
_HUMAN_LOCKED_MESSAGE = "The agent already answered this; the AI can't change it."
# _PROPOSAL_SUBMITTED_MESSAGE: reuses the module-level constant defined above for
# apply_answers() (Story 3.2) -- one message, not two sources of truth.


def _label_to_code(question: Mapping[str, Any] | None, value: Any) -> Any:
    """FORM-219 safety net: if ``value`` is a string that case-insensitively equals one of
    ``question``'s ``x-labels`` labels (e.g. "malaysia" for C4/C5's "Malaysia"), return that
    label's enum code instead ("MY"); otherwise return ``value`` unchanged.

    This is generic over every ``x-labels`` question, not only the countries (C4/C5) the live
    incident was about: any enum question that carries ``x-labels`` gets the same mapping, so the
    agent never has to ask the insurance agent for a raw code, and ``patch_draft`` never rejects a
    label it could resolve on its own. A value that already is a valid code (or matches nothing)
    passes through untouched, so an unknown label still surfaces as the schema's own
    ``invalid_value``/``invalid_enum`` error, not a silent no-op.
    """
    if question is None or not isinstance(value, str):
        return value
    labels = question.get("x-labels")
    if not isinstance(labels, Mapping):
        return value
    folded = value.casefold()
    for code, label in labels.items():
        if isinstance(label, str) and label.casefold() == folded:
            return code
    return value


def apply_agent_patch(
    schema: Schema,
    proposal: Proposal,
    incoming: Mapping[str, Any],
    clock: Clock,
    products: Sequence[Product],
    claims: TurnClaims,
) -> tuple[Proposal, list[str], list[FieldError]]:
    """Validate and partially apply one MCP ``patch_draft`` call in a pure step (Story 4.3, AD-3,
    AD-6, AD-14, AD-15).

    FORM-219: before anything else, every incoming value is passed through :func:`_label_to_code`,
    so a value that case-insensitively equals one of its question's ``x-labels`` labels (any enum
    question that has one, not only C4/C5's countries) is stored as that label's code -- the agent
    itself is told never to ask for or show a raw code, and this is the safety net for whenever it
    sends a label anyway.

    Unlike :func:`apply_answers` (the all-or-nothing human sibling), a per-field problem never
    aborts the whole call -- only a turn-binding failure (``lock_not_held``, spec Intent's frozen
    ASSUMPTION) or an already-``SUBMITTED`` proposal (``proposal_submitted``) does, and both raise
    ``DomainError`` and change nothing.

    Every other field in ``incoming`` is checked independently, in this precedence (spec Intent's
    frozen ASSUMPTION -- the brief lists the codes, not their order): an unknown question id is
    ``unknown_field``; a known question with ``x-agent-writable: false`` (D1, and any future field
    marked the same way, AD-3) is ``not_agent_writable``; a known, writable question whose
    *stored* answer already has ``source: "human"`` is ``human_locked`` (AD-6, a human edit is
    final); otherwise :func:`_answer_error` decides (inactive -- unless this same patch activates
    it, AD-15 -- null-on-choice, schema, C2's age range, or the Story 2.3 P1/P2/P3/N5 product
    checks), reused verbatim so the same rules never drift between the human and AI write paths. A
    ``source`` key in ``incoming`` has no special meaning: it is just another (unknown) field id,
    since every accepted field is stored at ``source: "ai"`` regardless of anything the caller sent
    (AD-3: ``patch_draft`` never accepts a caller-supplied ``source``).

    On success: every accepted field is (re)stored at ``source: "ai"`` (a no-op write, matching
    ``value``, keeps its stored ``source``/``updated_at`` exactly as :func:`apply_answers` does),
    the active set is recomputed (AD-15), and ``revision`` is bumped by one whether or not any
    field actually changed (the existing convention, not a new one). Returns the updated proposal,
    the accepted field ids (``incoming``'s own order) and the rejected fields' errors.
    """
    now = clock.now()
    if not turn_bound(proposal, claims, now):
        raise DomainError.single("turn", ErrorCode.LOCK_NOT_HELD, _LOCK_NOT_HELD_MESSAGE)
    if proposal.status is ProposalStatus.SUBMITTED:
        raise DomainError.single(
            "proposal", ErrorCode.PROPOSAL_SUBMITTED, _PROPOSAL_SUBMITTED_MESSAGE
        )

    props = questions(schema)
    # FORM-219: resolve any x-labels label to its enum code before anything else runs, so the
    # rest of this function -- merged_plain, active_after, validation and storage -- only ever
    # sees codes, exactly as if the agent had sent one itself.
    incoming = {
        question_id: _label_to_code(props.get(question_id), value)
        for question_id, value in incoming.items()
    }
    current_plain = {
        question_id: entry.get("value")
        for question_id, entry in proposal.answers.items()
    }
    merged_plain = {**current_plain, **incoming}
    active_after = active_questions(schema, merged_plain)

    applied: list[str] = []
    errors: list[FieldError] = []
    answers = dict(proposal.answers)
    for question_id, value in incoming.items():
        question = props.get(question_id)
        stored = proposal.answers.get(question_id)
        if question is not None and question.get("x-agent-writable") is False:
            errors.append(
                FieldError(
                    question_id, ErrorCode.NOT_AGENT_WRITABLE, _NOT_AGENT_WRITABLE_MESSAGE
                )
            )
            continue
        if question is not None and stored is not None and stored.get("source") == "human":
            errors.append(
                FieldError(question_id, ErrorCode.HUMAN_LOCKED, _HUMAN_LOCKED_MESSAGE)
            )
            continue
        error = _answer_error(
            question_id,
            question,
            value,
            active_after,
            merged_plain,
            products,
            proposal.created_at,
        )
        if error is not None:
            errors.append(error)
            continue
        applied.append(question_id)
        if stored is None or stored.get("value") != value:
            answers[question_id] = {
                "value": value,
                "source": "ai",
                "updated_at": _iso(now),
            }

    updated = replace(
        proposal,
        revision=proposal.revision + 1,
        answers=_recompute(schema, answers, now),
        updated_at=now,
    )
    return updated, applied, errors


_UNKNOWN_CUSTOMER_MESSAGE = "This customer doesn't exist."


def link_customer(
    schema: Schema,
    proposal: Proposal,
    customer_id: UUID,
    customer_row: Mapping[str, Any] | None,
    clock: Clock,
    claims: TurnClaims,
    customer_columns: Sequence[DbColumn],
) -> tuple[Proposal, list[str]]:
    """Link ``proposal`` to an existing customer and copy their particulars in one pure step
    (Story 5.2, AD-3, AD-13, AD-15): the seventh MCP tool's domain rule.

    Mirrors :func:`apply_agent_patch`'s guard order (spec Boundaries "Always"): the caller's turn
    binding is checked first (``lock_not_held``), then an already-``SUBMITTED`` proposal
    (``proposal_submitted``), then an unknown ``customer_id`` -- ``customer_row`` is ``None`` here
    exactly when the store's own lookup, inside the same locked transaction, found no such row --
    (``invalid_value`` on field ``customer_id``). Each raises ``DomainError`` and changes nothing.

    On success: every ``customer_columns`` question (C1-C15, AD-13; never ``H*``/``G*``, whatever
    the schema version) is copied into ``answers`` at ``source: "db"``, *except* one whose stored
    answer already has ``source: "human"`` -- that one is left exactly as it was and its id is
    returned in the skipped list (AD-13's "skipping any field set by a human"; a stored ``ai``,
    ``default`` or unanswered entry is overwritten). A ``ColumnType.DATE`` column's value (a real
    ``date`` from the store) is stored as its ISO string, the same shape as every other date
    answer. The active set is then recomputed (AD-15), same as every other write path, and
    ``revision`` bumps by one. Returns the updated proposal and the skipped question ids
    (``customer_columns``' own order).
    """
    now = clock.now()
    if not turn_bound(proposal, claims, now):
        raise DomainError.single("turn", ErrorCode.LOCK_NOT_HELD, _LOCK_NOT_HELD_MESSAGE)
    if proposal.status is ProposalStatus.SUBMITTED:
        raise DomainError.single(
            "proposal", ErrorCode.PROPOSAL_SUBMITTED, _PROPOSAL_SUBMITTED_MESSAGE
        )
    if customer_row is None:
        raise DomainError.single(
            "customer_id", ErrorCode.INVALID_VALUE, _UNKNOWN_CUSTOMER_MESSAGE
        )

    answers = dict(proposal.answers)
    skipped: list[str] = []
    for column in customer_columns:
        stored = proposal.answers.get(column.question_id)
        if stored is not None and stored.get("source") == "human":
            skipped.append(column.question_id)
            continue
        value = customer_row.get(column.column)
        if column.type is ColumnType.DATE and isinstance(value, date):
            value = value.isoformat()
        answers[column.question_id] = {
            "value": value,
            "source": "db",
            "updated_at": _iso(now),
        }

    updated = replace(
        proposal,
        customer_id=customer_id,
        revision=proposal.revision + 1,
        answers=_recompute(schema, answers, now),
        updated_at=now,
    )
    return updated, skipped


def _answer_value(answers: Mapping[str, Mapping[str, Any]], question_id: str) -> object:
    entry = answers.get(question_id)
    return entry.get("value") if entry is not None else None


_WHITESPACE_RUN = re.compile(r"\s+")


def display_name(proposal: Proposal) -> str:
    """"<C1>_<C13>_Proposal_NNN" once she has a first and last name; else Untitled_Proposal_NNN
    (FR11, UX-DR12).

    ``NNN`` is the proposal's own ``owner_seq``, zero-padded to 3 digits -- the same number as its
    ``Untitled_Proposal_NNN`` name -- so a draft's display name never changes as its owner creates
    more drafts, and doesn't change on submit either. Each name is trimmed of leading/trailing
    whitespace, and any internal run of whitespace becomes a single ``_`` (spec assumption: the
    owner wasn't asked about whitespace).
    """
    first_name = _answer_value(proposal.answers, "C1")
    last_name = _answer_value(proposal.answers, "C13")
    if (
        isinstance(first_name, str)
        and first_name.strip()
        and isinstance(last_name, str)
        and last_name.strip()
    ):
        first = _WHITESPACE_RUN.sub("_", first_name.strip())
        last = _WHITESPACE_RUN.sub("_", last_name.strip())
        return f"{first}_{last}_Proposal_{proposal.owner_seq:03d}"
    return f"Untitled_Proposal_{proposal.owner_seq:03d}"


def draft_view(proposal: Proposal, session_id: str) -> dict[str, Any]:
    """The AD-5 draft wire shape, plus ``display_name`` (spec assumption: additive, REST-only).

    ``active`` is recomputed from the pinned schema and the plain answer values every time, never
    stored (AD-15). ``quote`` is always null here; the caller resolves it separately with
    :func:`resolve_quote` and :func:`quote_view`, since pricing needs the catalogue port and this
    function takes no I/O (Story 2.2 Part B). ``lock`` is relative to ``session_id``, the caller's
    per-tab ``X-Session-Id`` (Story 4.4, AD-16).
    """
    schema = load_schema(proposal.schema_version)
    plain_answers = {
        question_id: entry.get("value")
        for question_id, entry in proposal.answers.items()
    }
    provenance = {
        question_id: {
            "source": entry.get("source"),
            "updated_at": entry.get("updated_at"),
        }
        for question_id, entry in proposal.answers.items()
    }
    active = sorted(active_questions(schema, plain_answers))
    return {
        "id": proposal.id,
        "status": proposal.status.value,
        "schema_version": proposal.schema_version,
        "revision": proposal.revision,
        "lock": lock_view(proposal, session_id),
        "active": active,
        "answers": plain_answers,
        "provenance": provenance,
        "quote": None,
        "display_name": display_name(proposal),
        # Story 3.2: additive, REST-only, like display_name above -- the workspace's read-only
        # "Submitted on <date>" strip needs it once status is submitted.
        "submitted_at": proposal.submitted_at,
    }


def _rider_codes(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [code for code in value if isinstance(code, str)]


def _date_of_birth(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        # A malformed C2 is as unpriceable as a missing one; degrade to null like every other
        # unpriceable case rather than raising (Story 2.2 Part B review).
        return None


async def resolve_quote(
    proposal: Proposal, catalogue: ProductCatalogue
) -> Quote | None:
    """Price P1 and P2 for the insured's age at ``proposal.created_at`` (Story 2.2 Part B, AD-5).

    Resolves P1 through ``catalogue`` and passes it, the P2 codes, C2 and ``created_at`` to
    :func:`domain.pricing.build_quote`. Never stored: recomputed on every call. ``None`` when P1 or
    C2 is unset, P1 doesn't match a stored product, the age has no band, or a P2 code isn't one of
    P1's riders (the last three are ``build_quote``'s job).
    """
    product_code = _answer_value(proposal.answers, "P1")
    if not isinstance(product_code, str) or not product_code:
        return None
    products = await catalogue.products()
    product = next(
        (candidate for candidate in products if candidate.code == product_code), None
    )
    rider_codes = _rider_codes(_answer_value(proposal.answers, "P2"))
    date_of_birth = _date_of_birth(_answer_value(proposal.answers, "C2"))
    return build_quote(product, rider_codes, date_of_birth, proposal.created_at)


def quote_view(quote: Quote | None) -> dict[str, Any] | None:
    """The AD-5 ``quote`` wire shape (``{monthly, yearly, lines}``), or ``None``."""
    if quote is None:
        return None
    return {
        "monthly": quote.monthly,
        "yearly": quote.yearly,
        "lines": [
            {"item": line.item, "monthly": line.monthly, "yearly": line.yearly}
            for line in quote.lines
        ],
    }


# Story 3.1: validate_proposal -- the read-only whole-proposal check behind
# POST /api/proposals/:id/validate (AD-7, AD-12, AD-15).

_REQUIRED_MESSAGE = "Answer required"


async def _product_rule_errors(
    active: frozenset[str],
    plain: Mapping[str, object],
    errors: Mapping[str, FieldError],
    catalogue: ProductCatalogue,
    now: datetime,
) -> dict[str, FieldError]:
    """P1-P3/N5's domain rules (AD-7), reusing the same checks a PATCH runs (Story 2.3): the
    product exists, the insured's age (at ``now``, which the caller passes as
    ``proposal.created_at``) is within its age range, every P2 rider belongs to it, P3 is one of
    its policy terms, and N5 -- if answered -- is within its sum-assured range (a product with
    none, such as CFH, takes no N5 at all).

    Skips a field that already has a schema-level error (AD-12: at most one per field), and skips
    P2/P3/N5 entirely once P1 fails to resolve to a stored product -- there is nothing to check
    them against (spec Design Notes "Product rules order").
    """
    found: dict[str, FieldError] = {}
    if "P1" not in active or "P1" in errors or plain.get("P1") is None:
        return found
    products = await catalogue.products()
    p1_error = _p1_error(plain["P1"], plain, products, now)
    if p1_error is not None:
        found["P1"] = p1_error
    if _selected_product(plain, products) is None:
        return found
    sibling_checks = (("P2", _p2_error), ("P3", _p3_error), ("N5", _n5_error))
    for question_id, check in sibling_checks:
        value = plain.get(question_id)
        if question_id in active and question_id not in errors and value is not None:
            error = check(value, plain, products)
            if error is not None:
                found[question_id] = error
    return found


async def validate_proposal(
    schema: Schema, proposal: Proposal, catalogue: ProductCatalogue
) -> list[FieldError]:
    """The read-only whole-proposal check behind ``POST .../validate`` (Story 3.1, FR42, AD-7,
    AD-12, AD-15): every active question's own ``jsonschema`` rule, ``required`` for an
    active-and-unanswered required question, C2's age at ``proposal.created_at`` -- never "now" --
    and the P1-P3/N5 product rules. Inactive questions and D1 are never checked (the loop only
    walks :func:`active_questions`, which never includes either); at most one error per field
    (AD-12). Never mutates ``proposal`` and never raises: always returns the (possibly empty) list
    of :class:`FieldError`, sorted by field id for a deterministic result.
    """
    props = questions(schema)
    plain = {
        question_id: entry.get("value")
        for question_id, entry in proposal.answers.items()
    }
    active = active_questions(schema, plain)
    required = required_questions(schema, plain)
    now = proposal.created_at

    errors: dict[str, FieldError] = {}
    for question_id in active:
        question = props.get(question_id)
        if question is None:
            continue
        value = plain.get(question_id)
        if value is None:
            if question_id in required:
                errors[question_id] = FieldError(
                    question_id, ErrorCode.REQUIRED, _REQUIRED_MESSAGE
                )
            continue
        error = _schema_value_error(question_id, question, value)
        if error is not None:
            errors[question_id] = error
            continue
        if question_id == "C2":
            c2_error = _c2_age_error(question, value, now)
            if c2_error is not None:
                errors[question_id] = c2_error

    errors.update(await _product_rule_errors(active, plain, errors, catalogue, now))

    return [errors[question_id] for question_id in sorted(errors)]


# Story 3.3/FORM-21: submit_proposal -- declaration, AI rating and the real submit endpoint
# (POST /api/proposals/:id/submit, FR18-20, AD-2, AD-8, AD-12, AD-13, AD-16).

_DECLARATION_REQUIRED_MESSAGE = "Confirm the declaration before submitting."
_FEEDBACK_REQUIRED_MESSAGE = "Pick a rating before submitting."


@dataclass(frozen=True, slots=True)
class SubmitFeedback:
    """The agent's own feedback on the AI, recorded at submit (spec Intent's "Key finding"): a
    1-5 star rating and an optional comment. Not a live agent call -- Story 4.5 is not a
    dependency, and this is never generated, only stored verbatim."""

    rating: int
    comment: str | None


@dataclass(frozen=True, slots=True)
class SubmitResult:
    """The pure output of :func:`submit_proposal`: the updated proposal (D1 set, status
    submitted, revision bumped, a ``customer_id`` whether newly generated or already there) plus
    the ``customer`` column values to upsert and the feedback row to insert. The store writes all
    three in the same transaction as the row lock that produced this."""

    proposal: Proposal
    customer_values: dict[str, Any]
    feedback: SubmitFeedback


def _feedback_error(feedback: Mapping[str, Any]) -> FieldError | None:
    """``feedback.rating`` missing, non-integer or outside 1-5 is ``feedback_required`` (spec I/O
    matrix "Bad rating"); ``bool`` is excluded even though it's an ``int`` subtype in Python."""
    rating = feedback.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or not (1 <= rating <= 5):
        return FieldError(
            "feedback", ErrorCode.FEEDBACK_REQUIRED, _FEEDBACK_REQUIRED_MESSAGE
        )
    return None


def _customer_values(
    proposal: Proposal, customer_columns: Sequence[DbColumn]
) -> dict[str, Any]:
    """The ``x-fill: db`` answers' current values, keyed by their fixed ``customer`` column
    (``customer_fields.py:db_columns``), for the submit-time upsert (AD-13). C2's date string is
    parsed to a real ``date`` for ``date_of_birth`` -- degrading a malformed one to ``None``, the
    same as :func:`resolve_quote` does, rather than handing the store adapter a raw string for a
    ``DATE`` column."""
    plain = {qid: entry.get("value") for qid, entry in proposal.answers.items()}
    values: dict[str, Any] = {}
    for column in customer_columns:
        value = plain.get(column.question_id)
        if column.type is ColumnType.DATE and isinstance(value, str):
            value = _date_of_birth(value)
        values[column.column] = value
    return values


async def submit_proposal(
    schema: Schema,
    proposal: Proposal,
    expected_revision: int,
    declaration_agreed: bool,
    feedback: Mapping[str, Any],
    clock: Clock,
    catalogue: ProductCatalogue,
    session_id: str,
    customer_columns: Sequence[DbColumn],
) -> SubmitResult | None:
    """Validate and submit a proposal in one pure step (Story 3.3, FR18-20, AD-2, AD-8, AD-12,
    AD-13, AD-16): the shared write path behind ``POST /api/proposals/:id/submit``.

    Mirrors :func:`apply_answers`'s guard order (spec Boundaries "Always"): a stale
    ``expected_revision`` returns ``None`` (writes nothing; the caller maps it to
    ``stale_revision``); an already-``SUBMITTED`` proposal raises ``proposal_submitted``; then
    the caller's write lock must be held, or this raises ``lock_not_held`` -- both checks run
    before either of this story's own, exactly as they do in ``apply_answers``. Next: an
    unagreed or missing declaration is ``declaration_required``, and a missing or out-of-range
    feedback rating is ``feedback_required`` -- both are collected into one ``DomainError`` when
    both fail, the same one-call/many-field-errors shape every other write path already uses
    (AD-12). Only once those pass does the read-only whole-proposal :func:`validate_proposal`
    re-check run; its own field errors are raised verbatim, never re-implemented here. Every
    failure raises ``DomainError`` (or returns ``None`` for a stale revision) and changes
    nothing.

    On success: D1 is stored ``True`` at ``source: human`` (D1 is never agent-writable, but this
    is the one write path allowed to set it at all, FR18) with no other recompute -- D1 is never
    active and never touched by :func:`_recompute`, so setting it directly is exactly what every
    other read of it already assumes. Status becomes ``submitted``, ``submitted_at`` is
    ``clock.now()``, and ``revision`` bumps by one, the same convention as every other write path.
    The ``customer`` columns are read from these now-final answers; a proposal with no
    ``customer_id`` yet gets a freshly generated one (AD-13) so the store can tell an insert from
    an update, without needing to touch the database itself.
    """
    if proposal.revision != expected_revision:
        return None

    if proposal.status is ProposalStatus.SUBMITTED:
        raise DomainError.single(
            "proposal", ErrorCode.PROPOSAL_SUBMITTED, _PROPOSAL_SUBMITTED_MESSAGE
        )

    now = clock.now()
    if not _lock_held_by(proposal, session_id, now):
        raise DomainError.single(
            "lock", ErrorCode.LOCK_NOT_HELD, _LOCK_NOT_HELD_MESSAGE
        )

    errors: list[FieldError] = []
    if declaration_agreed is not True:
        errors.append(
            FieldError(
                "declaration",
                ErrorCode.DECLARATION_REQUIRED,
                _DECLARATION_REQUIRED_MESSAGE,
            )
        )
    feedback_error = _feedback_error(feedback)
    if feedback_error is not None:
        errors.append(feedback_error)
    if errors:
        raise DomainError(errors)

    validation_errors = await validate_proposal(schema, proposal, catalogue)
    if validation_errors:
        raise DomainError(validation_errors)

    answers = dict(proposal.answers)
    answers["D1"] = {"value": True, "source": "human", "updated_at": _iso(now)}
    updated = replace(
        proposal,
        revision=expected_revision + 1,
        answers=answers,
        status=ProposalStatus.SUBMITTED,
        submitted_at=now,
        updated_at=now,
        customer_id=proposal.customer_id if proposal.customer_id is not None else uuid4(),
    )
    return SubmitResult(
        proposal=updated,
        customer_values=_customer_values(updated, customer_columns),
        feedback=SubmitFeedback(
            rating=feedback["rating"], comment=feedback.get("comment")
        ),
    )
