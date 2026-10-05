// The one module that talks to the api (coding-style.md rule 15). Every /api call carries this tab's
// session ID as X-Session-Id: the api's forgery check needs it on every non-GET call (security.md
// rule 23), and the edit lock uses it as the tab's identity (AD-16).

/** A random UUIDv4, from crypto.randomUUID where the browser has it (it needs a secure context). */
export function newSessionId(): string {
  if (typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40; // version 4
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80; // RFC 4122 variant
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join(
    "",
  );
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

/** One session ID per tab: made once when the app loads, kept only in this tab's memory. */
export const sessionId: string = newSessionId();

export const SESSION_HEADER = "X-Session-Id";

const API_PREFIX = "/api/";

/**
 * A callback the signed-in shell registers on mount (spec assumption "401 hook"): `apiFetch` calls
 * it on any 401, so a failed autosave/chat call pushes the session to signed-out immediately,
 * without waiting for a route change to notice (Story 1.10, closing the Story 1.6 TODO in
 * deferred-work.md). Kept here, not imported from `../app/session`, so this module never depends on
 * React state directly (coding-style.md rule 15: this is the one client module).
 */
let unauthorizedHandler: (() => void) | null = null;

/** Registers (or clears, with `null`) the 401 callback above. */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  unauthorizedHandler = handler;
}

/**
 * Calls the api at a same-origin `/api/...` path and returns the raw response. The path is resolved
 * against this page's origin first, so absolute URLs, other origins and paths that normalise out of
 * /api/ (`/api/../healthz`, `/api/%2e%2e/mcp`) are refused and the session ID never leaves formapp's
 * api (security.md rule 22).
 */
export async function apiFetch(
  path: string,
  init: RequestInit = {},
): Promise<Response> {
  const url = new URL(path, window.location.origin);
  if (
    url.origin !== window.location.origin ||
    !url.pathname.startsWith(API_PREFIX)
  ) {
    throw new Error(`apiFetch only calls same-origin ${API_PREFIX} paths.`);
  }
  const headers = new Headers(init.headers);
  headers.set(SESSION_HEADER, sessionId);
  const response = await fetch(url.pathname + url.search, {
    ...init,
    headers,
    credentials: "same-origin",
  });
  if (response.status === 401) {
    unauthorizedHandler?.();
  }
  return response;
}

/** The signed-in agent's names, from `GET /api/me` (Story 1.6). */
export type Me = { name: string; firstName: string };

/**
 * Who is signed in: her names, or null when the api answers 401 (nobody is signed in, or the
 * session has expired). This is the only way the web app decides whether she is signed in. Any
 * other failure throws, so a passing outage isn't mistaken for a sign-out.
 */
export async function getMe(): Promise<Me | null> {
  const response = await apiFetch("/api/me");
  if (response.status === 401) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`GET /api/me failed with ${response.status}.`);
  }
  const body: unknown = await response.json();
  if (
    typeof body !== "object" ||
    body === null ||
    !("name" in body) ||
    !("first_name" in body) ||
    typeof body.name !== "string" ||
    typeof body.first_name !== "string"
  ) {
    throw new Error("GET /api/me returned an unexpected body.");
  }
  return { name: body.name, firstName: body.first_name };
}

/** A proposal's lifecycle state (spine AD-8); the api's closed set. */
export type ProposalStatusValue = "draft" | "submitted";

function isProposalStatus(value: unknown): value is ProposalStatusValue {
  return value === "draft" || value === "submitted";
}

/** One row of `GET /api/proposals` (Story 1.8, FR8, FR11). `submittedAt` is null for a draft, and
 * for a submitted row until the api backfills it (Story 3.2, FR9). `customerNumber` is null until
 * a customer is linked or generated at submit (FORM-218). */
export type ProposalSummary = {
  id: string;
  displayName: string;
  status: ProposalStatusValue;
  createdAt: string;
  submittedAt: string | null;
  customerNumber: string | null;
};

/** Who holds the edit lock (spine AD-16), relative to this tab's own session. */
export type Lock = {
  holder: "you" | "other_session" | "ai";
  expiresAt: string | null;
};

/** Null until P1 and C2 are both set (Epic 2); the web app shows it as is (spine AD-5). */
export type Quote = {
  monthly: number;
  yearly: number;
  lines: { item: string; monthly: number; yearly: number }[];
} | null;

/**
 * The AD-5 draft wire shape, camelCased, plus `display_name` (spec assumption for Story 1.8: an
 * additive, REST-only field, so the web app never computes the naming rule itself, coding-style.md
 * rule 16). This story only reads `id` and `displayName`; `schemaVersion`, `active`, `answers`,
 * `provenance` and `quote` are for 1.9/1.10 to render the workspace and its questions.
 */
export type Draft = {
  id: string;
  status: ProposalStatusValue;
  schemaVersion: number;
  revision: number;
  lock: Lock;
  active: string[];
  answers: Record<string, unknown>;
  provenance: Record<string, unknown>;
  quote: Quote;
  displayName: string;
  /** Null until she submits (Story 3.2, AD-8); the read-only workspace's "Submitted on <date>"
   * strip is the only thing that reads it. */
  submittedAt: string | null;
  /** Null until a customer is linked or generated at submit (FORM-218); the submitted strip and
   * the Submitted list are the only things that read it. */
  customerNumber: string | null;
};

function parseProposalSummary(value: unknown): ProposalSummary {
  if (typeof value !== "object" || value === null) {
    throw new Error("GET /api/proposals returned an unexpected body.");
  }
  const row = value as Record<string, unknown>;
  if (
    typeof row.id !== "string" ||
    typeof row.display_name !== "string" ||
    !isProposalStatus(row.status) ||
    typeof row.created_at !== "string" ||
    (row.submitted_at !== null && typeof row.submitted_at !== "string")
  ) {
    throw new Error("GET /api/proposals returned an unexpected body.");
  }
  return {
    id: row.id,
    displayName: row.display_name,
    status: row.status,
    createdAt: row.created_at,
    submittedAt: (row.submitted_at ?? null) as string | null,
    // Lenient like submittedAt above (not in the strict checks): every real row carries it once
    // FORM-218 lands, but existing fixtures across the test suite predate the field.
    customerNumber:
      typeof row.customer_number === "string" ? row.customer_number : null,
  };
}

function parseLock(value: unknown): Lock {
  if (typeof value !== "object" || value === null) {
    throw new Error("A draft's lock was an unexpected shape.");
  }
  const lock = value as Record<string, unknown>;
  if (
    typeof lock.holder !== "string" ||
    (lock.expires_at !== null && typeof lock.expires_at !== "string")
  ) {
    throw new Error("A draft's lock was an unexpected shape.");
  }
  return {
    holder: lock.holder as Lock["holder"],
    expiresAt: lock.expires_at as string | null,
  };
}

function parseDraft(value: unknown): Draft {
  if (typeof value !== "object" || value === null) {
    throw new Error("The draft api returned an unexpected body.");
  }
  const draft = value as Record<string, unknown>;
  if (
    typeof draft.id !== "string" ||
    !isProposalStatus(draft.status) ||
    typeof draft.schema_version !== "number" ||
    typeof draft.revision !== "number" ||
    !Array.isArray(draft.active) ||
    !draft.active.every((item) => typeof item === "string") ||
    typeof draft.answers !== "object" ||
    draft.answers === null ||
    Array.isArray(draft.answers) ||
    typeof draft.provenance !== "object" ||
    draft.provenance === null ||
    Array.isArray(draft.provenance) ||
    typeof draft.display_name !== "string"
  ) {
    throw new Error("The draft api returned an unexpected body.");
  }
  return {
    id: draft.id,
    status: draft.status,
    schemaVersion: draft.schema_version,
    revision: draft.revision,
    lock: parseLock(draft.lock),
    active: draft.active as string[],
    answers: draft.answers as Record<string, unknown>,
    provenance: draft.provenance as Record<string, unknown>,
    quote: (draft.quote ?? null) as Quote,
    displayName: draft.display_name,
    // Lenient like quote above (not in the strict checks): every real draft carries it once
    // Story 3.2 lands, but existing fixtures across the test suite predate the field.
    submittedAt:
      typeof draft.submitted_at === "string" ? draft.submitted_at : null,
    // Lenient like submittedAt above: every real draft carries it once FORM-218 lands, but
    // existing fixtures across the test suite predate the field.
    customerNumber:
      typeof draft.customer_number === "string" ? draft.customer_number : null,
  };
}

/** `POST /api/proposals`: a fresh, owned draft, numbered after her previous ones (Story 1.8). */
export async function createProposal(): Promise<Draft> {
  const response = await apiFetch("/api/proposals", { method: "POST" });
  if (!response.ok) {
    throw new Error(`POST /api/proposals failed with ${response.status}.`);
  }
  return parseDraft(await response.json());
}

/** `GET /api/proposals?status=`: her own proposals with this status, newest first (Story 1.8). */
export async function listProposals(
  status: ProposalStatusValue,
): Promise<ProposalSummary[]> {
  const response = await apiFetch(
    `/api/proposals?status=${encodeURIComponent(status)}`,
  );
  if (!response.ok) {
    throw new Error(`GET /api/proposals failed with ${response.status}.`);
  }
  const body: unknown = await response.json();
  if (!Array.isArray(body)) {
    throw new Error("GET /api/proposals returned an unexpected body.");
  }
  return body.map(parseProposalSummary);
}

/** Thrown by `getDraft`/`getSchema` on a 404, so the workspace can send her back to Drafts (FR13). */
export class NotFoundError extends Error {}

/** One AD-12 field error, camelCase-free since `field` is already a schema question id or a
 * request-level name (coding-style.md rule 3). */
export type FieldErrorOut = { field: string; code: string; message: string };

/**
 * Thrown by `patchAnswers` for any non-2xx response (spec assumption "closed-error-shape
 * parsing"): `status` is the HTTP status, and `fieldErrors` is the AD-12 body's `errors` array when
 * the response actually has that closed shape (a 409/422 always will; a 5xx or a malformed body
 * won't, and `fieldErrors` is then `undefined` -- the caller treats that as a generic failure).
 */
export class ApiError extends Error {
  readonly status: number;
  readonly fieldErrors: FieldErrorOut[] | undefined;

  constructor(status: number, fieldErrors: FieldErrorOut[] | undefined) {
    super(`api call failed with ${status}.`);
    this.status = status;
    this.fieldErrors = fieldErrors;
  }
}

/**
 * Thrown by `sendChat` on a 429 (Story 4.8, spine AD-9): a dedicated shape, never `ApiError`'s
 * `fieldErrors` (the api never squeezes `retry_after_seconds` into the AD-12 shape). `ChatPanel`
 * drives its "Wait Ns" countdown from `retryAfterSeconds`.
 */
export class ThrottledError extends Error {
  readonly retryAfterSeconds: number;

  constructor(retryAfterSeconds: number) {
    super("api call was throttled.");
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

async function retryAfterSecondsOf(response: Response): Promise<number> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return 1; // not JSON: fall back to the shortest sensible wait rather than guessing longer
  }
  if (typeof body !== "object" || body === null) return 1;
  const value = (body as Record<string, unknown>).retry_after_seconds;
  return typeof value === "number" && value > 0 ? value : 1;
}

function isFieldErrorOut(value: unknown): value is FieldErrorOut {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    typeof row.field === "string" &&
    typeof row.code === "string" &&
    typeof row.message === "string"
  );
}

async function fieldErrorsOf(
  response: Response,
): Promise<FieldErrorOut[] | undefined> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return undefined; // not JSON: a 5xx or a proxy error page, not the AD-12 shape
  }
  if (typeof body !== "object" || body === null || !("errors" in body)) {
    return undefined;
  }
  const errors = (body as Record<string, unknown>).errors;
  if (!Array.isArray(errors) || !errors.every(isFieldErrorOut)) {
    return undefined;
  }
  return errors;
}

function parseValidateOut(value: unknown): FieldErrorOut[] {
  if (typeof value !== "object" || value === null || !("errors" in value)) {
    throw new Error(
      "POST /api/proposals/:id/validate returned an unexpected body.",
    );
  }
  const errors = (value as Record<string, unknown>).errors;
  if (!Array.isArray(errors) || !errors.every(isFieldErrorOut)) {
    throw new Error(
      "POST /api/proposals/:id/validate returned an unexpected body.",
    );
  }
  return errors;
}

/**
 * `POST /api/proposals/:id/validate`: the read-only whole-proposal check behind "Submit proposal"
 * (Story 3.1, AD-12): the AD-12 `errors` array, `[]` when the draft is clean. Never throws
 * `ApiError` for a field problem -- the api always answers 200 -- so a non-2xx here is a genuine
 * failure (404 for another agent's draft, or a 5xx), which the caller lets propagate.
 */
export async function validateDraft(id: string): Promise<FieldErrorOut[]> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(id)}/validate`,
    { method: "POST" },
  );
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `POST /api/proposals/${id}/validate returned ${response.status}.`,
    );
  }
  if (!response.ok) {
    throw new Error(
      `POST /api/proposals/${id}/validate failed with ${response.status}.`,
    );
  }
  return parseValidateOut(await response.json());
}

/**
 * `GET /api/proposals/:id`: the draft wire shape, or throws `NotFoundError` on a 404 -- or a 422,
 * FastAPI's answer to a malformed id, which counts the same as "another agent's draft ID" for the
 * AC's redirect-to-Drafts (Story 1.9, FR13).
 */
export async function getDraft(id: string): Promise<Draft> {
  const response = await apiFetch(`/api/proposals/${encodeURIComponent(id)}`);
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `GET /api/proposals/${id} returned ${response.status}.`,
    );
  }
  if (!response.ok) {
    throw new Error(`GET /api/proposals/${id} failed with ${response.status}.`);
  }
  return parseDraft(await response.json());
}

/**
 * The form schema for a proposal (Story 1.9, AD-7): `properties` keyed by question id, the
 * unconditional `required` ids, and the `allOf` show-if rules. This story only reads
 * `properties`, `required` and `allOf`; the rest of a schema file's shape is passed through
 * unread, so it isn't re-validated here (coding-style.md rule 16).
 */
export type Schema = {
  properties: Record<string, Record<string, unknown>>;
  required: string[];
  allOf?: unknown[];
};

function parseSchema(value: unknown): Schema {
  if (typeof value !== "object" || value === null) {
    throw new Error(
      "GET /api/proposals/:id/schema returned an unexpected body.",
    );
  }
  const body = value as Record<string, unknown>;
  const properties = body.properties;
  const required = body.required;
  if (
    typeof properties !== "object" ||
    properties === null ||
    Array.isArray(properties) ||
    !Array.isArray(required) ||
    !required.every((item) => typeof item === "string")
  ) {
    throw new Error(
      "GET /api/proposals/:id/schema returned an unexpected body.",
    );
  }
  return {
    properties: properties as Record<string, Record<string, unknown>>,
    required: required as string[],
    allOf: Array.isArray(body.allOf) ? body.allOf : undefined,
  };
}

/**
 * `GET /api/proposals/:id/schema`: the proposal's pinned schema, or `NotFoundError` (Story 1.9),
 * on a 404 or a 422 (FastAPI's answer to a malformed id -- see `getDraft`).
 */
export async function getSchema(id: string): Promise<Schema> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(id)}/schema`,
  );
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `GET /api/proposals/${id}/schema returned ${response.status}.`,
    );
  }
  if (!response.ok) {
    throw new Error(
      `GET /api/proposals/${id}/schema failed with ${response.status}.`,
    );
  }
  return parseSchema(await response.json());
}

/** One of P1's allowed policy terms; P3 answers store its `code` (Story 2.3). */
export type PolicyTerm = { code: string; label: string };

/** One of a product's riders, priced at the proposal's insured age (Story 2.3, AD-5): the web app
 * shows `monthly`/`yearly` as they come off the wire and never computes a price itself. */
export type Rider = {
  code: string;
  name: string;
  monthly: number;
  yearly: number;
};

/**
 * A product eligible for a proposal's insured age, priced at that age's band (Story 2.3): the
 * `GET /api/products?proposal_id=` shape, camelCased. `sumAssuredMin`/`Max` are both `null` for a
 * product with no sum assured (CFH).
 */
export type Product = {
  code: string;
  name: string;
  type: string;
  coversDependents: boolean;
  policyTerms: PolicyTerm[];
  sumAssuredMin: number | null;
  sumAssuredMax: number | null;
  defaultSumAssured: number | null;
  defaultTerm: string;
  minAge: number;
  maxAge: number;
  monthly: number;
  yearly: number;
  riders: Rider[];
};

function parsePolicyTerm(value: unknown): PolicyTerm {
  if (typeof value !== "object" || value === null) {
    throw new Error("A product's policy term was an unexpected shape.");
  }
  const term = value as Record<string, unknown>;
  if (typeof term.code !== "string" || typeof term.label !== "string") {
    throw new Error("A product's policy term was an unexpected shape.");
  }
  return { code: term.code, label: term.label };
}

function parseRider(value: unknown): Rider {
  if (typeof value !== "object" || value === null) {
    throw new Error("A product's rider was an unexpected shape.");
  }
  const rider = value as Record<string, unknown>;
  if (
    typeof rider.code !== "string" ||
    typeof rider.name !== "string" ||
    typeof rider.monthly !== "number" ||
    typeof rider.yearly !== "number"
  ) {
    throw new Error("A product's rider was an unexpected shape.");
  }
  return {
    code: rider.code,
    name: rider.name,
    monthly: rider.monthly,
    yearly: rider.yearly,
  };
}

function isNumberOrNull(value: unknown): value is number | null {
  return value === null || typeof value === "number";
}

function parseProduct(value: unknown): Product {
  if (typeof value !== "object" || value === null) {
    throw new Error("GET /api/products returned an unexpected body.");
  }
  const product = value as Record<string, unknown>;
  if (
    typeof product.code !== "string" ||
    typeof product.name !== "string" ||
    typeof product.type !== "string" ||
    typeof product.covers_dependents !== "boolean" ||
    !Array.isArray(product.policy_terms) ||
    !isNumberOrNull(product.sum_assured_min) ||
    !isNumberOrNull(product.sum_assured_max) ||
    !isNumberOrNull(product.default_sum_assured) ||
    typeof product.default_term !== "string" ||
    typeof product.min_age !== "number" ||
    typeof product.max_age !== "number" ||
    typeof product.monthly !== "number" ||
    typeof product.yearly !== "number" ||
    !Array.isArray(product.riders)
  ) {
    throw new Error("GET /api/products returned an unexpected body.");
  }
  return {
    code: product.code,
    name: product.name,
    type: product.type,
    coversDependents: product.covers_dependents,
    policyTerms: product.policy_terms.map(parsePolicyTerm),
    sumAssuredMin: product.sum_assured_min,
    sumAssuredMax: product.sum_assured_max,
    defaultSumAssured: product.default_sum_assured,
    defaultTerm: product.default_term,
    minAge: product.min_age,
    maxAge: product.max_age,
    monthly: product.monthly,
    yearly: product.yearly,
    riders: product.riders.map(parseRider),
  };
}

/**
 * `GET /api/products?proposal_id=`: the products eligible for this proposal's insured age, priced
 * at its band -- every product at baseline while C2 isn't set yet (Story 2.3). Throws
 * `NotFoundError` on a 404 (another agent's proposal id, or a malformed one), like `getDraft`.
 */
export async function getProducts(proposalId: string): Promise<Product[]> {
  const response = await apiFetch(
    `/api/products?proposal_id=${encodeURIComponent(proposalId)}`,
  );
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `GET /api/products?proposal_id=${proposalId} returned ${response.status}.`,
    );
  }
  if (!response.ok) {
    throw new Error(
      `GET /api/products?proposal_id=${proposalId} failed with ${response.status}.`,
    );
  }
  const body: unknown = await response.json();
  if (!Array.isArray(body)) {
    throw new Error("GET /api/products returned an unexpected body.");
  }
  return body.map(parseProduct);
}

/**
 * `PATCH /api/proposals/:id/answers`: sends only the fields that changed, and returns the updated
 * draft wire shape (Story 1.10, AD-6). Throws `ApiError` for any non-2xx response -- 409
 * `stale_revision`, 422 field problems, or a 5xx/network failure -- so the caller (`autosave.ts`)
 * can tell them apart by `status` and `fieldErrors`.
 */
export async function patchAnswers(
  id: string,
  revision: number,
  answers: Record<string, unknown>,
): Promise<Draft> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(id)}/answers`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ revision, answers }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await fieldErrorsOf(response));
  }
  return parseDraft(await response.json());
}

/** The declaration/AI-rating feedback `POST /api/proposals/:id/submit` body carries (Story 3.3):
 * `rating` is required (1-5), `comment` optional. */
export type SubmitFeedback = { rating: number; comment: string | null };

/**
 * `POST /api/proposals/:id/submit`: re-validates the whole proposal, sets D1, upserts `customer`
 * and records the feedback, all in one transaction (Story 3.3/FORM-21, AD-8, AD-12, AD-13).
 * Returns the updated (now submitted) draft wire shape. Throws `ApiError` for any non-2xx
 * response -- 409 `stale_revision`/`lock_not_held`/`proposal_submitted`, or 422
 * `declaration_required`/`feedback_required`/a field problem -- so the caller can tell them apart
 * by `status` and `fieldErrors`, exactly like `patchAnswers`.
 */
export async function submitProposal(
  id: string,
  revision: number,
  declarationAgreed: boolean,
  feedback: SubmitFeedback,
): Promise<Draft> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(id)}/submit`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        revision,
        declaration_agreed: declarationAgreed,
        feedback: { rating: feedback.rating, comment: feedback.comment },
      }),
    },
  );
  if (!response.ok) {
    throw new ApiError(response.status, await fieldErrorsOf(response));
  }
  return parseDraft(await response.json());
}

/**
 * `POST /api/proposals/:id/lock`: acquire, renew or (with `takeOver`) move this tab's edit lock,
 * keyed by its own `X-Session-Id` (Story 4.4, AD-16). Throws `NotFoundError` on a 404 or a 422
 * (malformed id, see `getDraft`) and `ApiError` for any other non-2xx response; both are unusual
 * here (a lock call never fails on field validation), so the caller treats them like any other
 * failed heartbeat.
 */
export async function lockDraft(
  id: string,
  { takeOver = false }: { takeOver?: boolean } = {},
): Promise<Lock> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(id)}/lock`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ take_over: takeOver }),
    },
  );
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `POST /api/proposals/${id}/lock returned ${response.status}.`,
    );
  }
  if (!response.ok) {
    throw new ApiError(response.status, await fieldErrorsOf(response));
  }
  return parseLock(await response.json());
}

/**
 * `DELETE /api/proposals/:id`: hard-deletes a draft (Story FORM-227) -- `answer_overrides`/
 * `proposal_feedback` cascade with it in the same transaction (migration 0016). Throws
 * `NotFoundError` on a 404 or a 422 (malformed id, see `getDraft`) and `ApiError` for any other
 * non-2xx response -- 409 `proposal_submitted`/`turn_in_progress`/`lock_not_held`. Resolves with
 * nothing on the api's 204.
 */
export async function deleteProposal(id: string): Promise<void> {
  const response = await apiFetch(`/api/proposals/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `DELETE /api/proposals/${id} returned ${response.status}.`,
    );
  }
  if (!response.ok) {
    throw new ApiError(response.status, await fieldErrorsOf(response));
  }
}

/** Story 4.5: one chat message, from `GET /api/proposals/:id/chat`'s history. */
export type ChatMessage = { role: string; text: string };

/** Story 4.5: the AD-5 SSE relay's three event types, parsed from `sendChat`'s stream. */
export type ChatEvent =
  | { type: "delta"; text: string }
  | { type: "done"; revision: number }
  | { type: "error"; code: string; message: string };

function parseChatMessage(value: unknown): ChatMessage | null {
  if (typeof value !== "object" || value === null) return null;
  const row = value as Record<string, unknown>;
  if (typeof row.role !== "string" || typeof row.text !== "string") return null;
  return { role: row.role, text: row.text };
}

/**
 * `GET /api/proposals/:id/chat`: the conversation's history, oldest first, `[]` before the first
 * turn (Story 4.5, AD-9). Throws `NotFoundError` on a 404 or a 422 (malformed id, see `getDraft`).
 */
export async function getChatHistory(id: string): Promise<ChatMessage[]> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(id)}/chat`,
  );
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `GET /api/proposals/${id}/chat returned ${response.status}.`,
    );
  }
  if (!response.ok) {
    throw new Error(
      `GET /api/proposals/${id}/chat failed with ${response.status}.`,
    );
  }
  const body: unknown = await response.json();
  if (
    typeof body !== "object" ||
    body === null ||
    !Array.isArray((body as Record<string, unknown>).messages)
  ) {
    throw new Error("GET /api/proposals/:id/chat returned an unexpected body.");
  }
  const messages = (body as Record<string, unknown>).messages as unknown[];
  return messages
    .map(parseChatMessage)
    .filter((m): m is ChatMessage => m !== null);
}

/** One SSE frame's parsed `(event, data)`, or `null` for a block with no complete event/data pair
 * (a partial chunk still waiting on more bytes). */
function parseSseBlock(block: string): { event: string; data: unknown } | null {
  let event: string | null = null;
  let data: string | null = null;
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) data = line.slice("data:".length).trim();
  }
  if (event === null || data === null) return null;
  try {
    return { event, data: JSON.parse(data) };
  } catch {
    return null; // a malformed frame is dropped, never thrown mid-stream
  }
}

function toChatEvent(parsed: {
  event: string;
  data: unknown;
}): ChatEvent | null {
  const data = parsed.data as Record<string, unknown>;
  if (
    parsed.event === "delta" &&
    typeof data === "object" &&
    data !== null &&
    typeof data.text === "string"
  ) {
    return { type: "delta", text: data.text };
  }
  if (
    parsed.event === "done" &&
    typeof data === "object" &&
    data !== null &&
    typeof data.revision === "number"
  ) {
    return { type: "done", revision: data.revision };
  }
  if (
    parsed.event === "error" &&
    typeof data === "object" &&
    data !== null &&
    typeof data.code === "string" &&
    typeof data.message === "string"
  ) {
    return { type: "error", code: data.code, message: data.message };
  }
  return null;
}

/**
 * `POST /api/proposals/:id/chat`: begins a chat turn and relays its SSE reply, calling `onEvent`
 * for each `delta`/`done`/`error` as it arrives (Story 4.5, AD-5). Throws `ApiError`/`NotFoundError`
 * for a rejection *before* the stream starts (404, 409 `proposal_submitted`/`turn_in_progress`/
 * `lock_not_held`) -- exactly like any other write; a rejection *after* it starts is instead the
 * stream's own `error` event, never a thrown rejection (mid-stream failure/timeout, EXPERIENCE.md
 * "Failure/cutoff": answers already written stay, the lock releases, no red banner). A 429 is also
 * thrown *before* the stream starts (Story 4.8: refused, no lock, no turn) -- as `ThrottledError`,
 * never `ApiError`, so `ChatPanel` can tell it apart from a genuine failure and show the countdown
 * instead of the fixed failure message.
 */
export async function sendChat(
  id: string,
  message: string,
  onEvent: (event: ChatEvent) => void,
): Promise<void> {
  const response = await apiFetch(
    `/api/proposals/${encodeURIComponent(id)}/chat`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    },
  );
  if (response.status === 404 || response.status === 422) {
    throw new NotFoundError(
      `POST /api/proposals/${id}/chat returned ${response.status}.`,
    );
  }
  if (response.status === 429) {
    throw new ThrottledError(await retryAfterSecondsOf(response));
  }
  if (!response.ok) {
    throw new ApiError(response.status, await fieldErrorsOf(response));
  }
  const body = response.body;
  if (!body) return; // no streaming body (an unusual test double): nothing more to relay
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary !== -1) {
      const parsed = parseSseBlock(buffer.slice(0, boundary));
      buffer = buffer.slice(boundary + 2);
      const event = parsed && toChatEvent(parsed);
      if (event) onEvent(event);
      boundary = buffer.indexOf("\n\n");
    }
  }
}

/** `GET /api/speech/token`'s wire shape, camelCased (Story 6.1/FORM-230, spine AD-19). Only
 * `web/src/speech/` calls `getSpeechToken` below -- everywhere else, `web/` never hard-codes
 * `region`, `endpoint`, `voice` or `locale`. */
export type SpeechTokenData = {
  token: string;
  authMode: string;
  region: string;
  endpoint: string;
  voice: string;
  locale: string;
  expiresAt: string;
};

function parseSpeechTokenData(value: unknown): SpeechTokenData {
  if (typeof value !== "object" || value === null) {
    throw new Error("GET /api/speech/token returned an unexpected body.");
  }
  const row = value as Record<string, unknown>;
  if (
    typeof row.token !== "string" ||
    typeof row.auth_mode !== "string" ||
    typeof row.region !== "string" ||
    typeof row.endpoint !== "string" ||
    typeof row.voice !== "string" ||
    typeof row.locale !== "string" ||
    typeof row.expires_at !== "string"
  ) {
    throw new Error("GET /api/speech/token returned an unexpected body.");
  }
  return {
    token: row.token,
    authMode: row.auth_mode,
    region: row.region,
    endpoint: row.endpoint,
    voice: row.voice,
    locale: row.locale,
    expiresAt: row.expires_at,
  };
}

/**
 * A cached-or-freshly-minted browser Speech token (Story 6.1/FORM-230, AD-19): signed-in-only, no
 * proposal or lock involved and not counted in AD-9's chat throttle. Throws `ApiError` for any
 * non-2xx response -- including the `speech_unavailable` 503, whose AD-12 body `fieldErrors`
 * carries -- mirroring `patchAnswers`'s use of `ApiError` for a closed-shape failure.
 */
export async function getSpeechToken(): Promise<SpeechTokenData> {
  const response = await apiFetch("/api/speech/token");
  if (!response.ok) {
    throw new ApiError(response.status, await fieldErrorsOf(response));
  }
  return parseSpeechTokenData(await response.json());
}
