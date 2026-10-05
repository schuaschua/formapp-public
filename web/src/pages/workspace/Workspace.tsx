import Form from "@rjsf/core";
import type {
  FieldTemplateProps,
  ObjectFieldTemplateProps,
  RJSFSchema,
} from "@rjsf/utils";
import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import { Navigate, useNavigate } from "react-router";
import {
  ApiError,
  deleteProposal,
  getDraft,
  getProducts,
  getSchema,
  NotFoundError,
  submitProposal,
  validateDraft,
  type Draft,
  type Product,
  type Schema,
} from "../../api/client";
import { useBreadcrumb } from "../../app/breadcrumb";
import { paths } from "../../app/paths";
import {
  DeleteConfirmModal,
  deleteFailedMessage,
} from "../../components/DeleteConfirmModal";
import { GlassCard } from "../../components/GlassCard";
import { InfoNote } from "../../components/InfoNote";
import { PillButton } from "../../components/PillButton";
import { strings } from "../../strings";
import { useAutosave, type FieldProblem } from "./autosave";
import { ChatPanel } from "./ChatPanel";
import { WorkspaceUiContext, useWorkspaceUi } from "./context";
import { useEditLock } from "./useEditLock";
import { PageMenu, type PageMenuPage } from "./PageMenu";
import { PriceSummary } from "./PriceSummary";
import { DeclarationModal, FeedbackModal } from "./SubmitModals";
import { validator, followUpIds, sectionHeadings } from "./validator";
import { chooseWidget, unitFor, workspaceWidgets } from "./widgets";
import "./Workspace.css";

/** The id `handleCancelModal` returns focus to (spec AC: "focus returns to Submit proposal") --
 * simpler and more robust across re-renders than forwarding a ref through `PillButton`, which
 * doesn't itself forward one (Story 3.3). */
const SUBMIT_BUTTON_ID = "workspace-submit-proposal-button";

/** The Product and Payment pages both show the read-only price summary below the question table
 * (epic-2-context.md "Price summary on pages 2 and 3"). Matched by title, not a fixed page
 * number: FORM-222's v2 schema renumbers pages (Product is 1, not 2), so this must hold for
 * either released schema version. */
const PRICE_SUMMARY_TITLES = new Set(["Product", "Payment"]);

/** Every distinct `x-page` the loaded schema's own questions carry, ascending (FORM-222: schema-
 * driven page scaffolding, so v1's 5 pages and v2's 4 both fall out of whichever schema the
 * workspace loaded for this draft -- never a hardcoded page count or list). */
function pageNumbersOf(schema: Schema): number[] {
  const pages = new Set<number>();
  for (const question of Object.values(schema.properties)) {
    const page = question["x-page"];
    if (typeof page === "number") pages.add(page);
  }
  return Array.from(pages).sort((a, b) => a - b);
}

/** Before the draft/schema have loaded, the page menu has nothing schema-driven to show yet --
 * v1's shape is as good a skeleton as any (Story 1.9's original loading state showed exactly
 * this), and it's replaced the instant the real schema arrives. */
const FALLBACK_PAGE_TITLES: Record<number, string> =
  strings.workspace.pagesByVersion[1] ?? {};
const FALLBACK_PAGE_NUMBERS = Object.keys(FALLBACK_PAGE_TITLES)
  .map(Number)
  .sort((a, b) => a - b);

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** "25 Sep 2026", UTC (Story 3.2, matches ProposalsPage's own row-date formatting): a submitted
 * proposal's calendar date must never drift with the viewer's timezone or CI's. */
function formatSubmittedDate(iso: string | null): string {
  if (iso === null) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

type LoadState =
  | { status: "loading" }
  | { status: "not-found" }
  | { status: "error" }
  | { status: "loaded"; draft: Draft; schema: Schema };

/** Drops the default label/description/errors wrapper: `Workspace`'s table renders its own
 * "Question" column, and this story shows neither errors nor provenance on a row. */
function RowFieldTemplate(props: FieldTemplateProps) {
  return <>{props.children}</>;
}

/**
 * Renders only the current page's `active` questions, in schema order, as the Question | Answer
 * table (DESIGN.md Components "Question row"): section headings (Gynaecology) when that section
 * has an active question on this page, and follow-up rows indented and lighter. Reads the
 * workspace's own context (`context.ts`), not RJSF's `formContext`/`registry` -- see that module's
 * docstring for why.
 */
function WorkspaceObjectFieldTemplate(props: ObjectFieldTemplateProps) {
  const { properties, schema } = props;
  const { currentPage, active, followUps, fieldProblems } = useWorkspaceUi();
  const byName = new Map(
    properties.map((property) => [property.name, property]),
  );
  const schemaProperties = (schema.properties ?? {}) as Record<
    string,
    Record<string, unknown>
  >;
  const pageIds = Object.keys(schemaProperties).filter(
    (qid) =>
      active.has(qid) && schemaProperties[qid]?.["x-page"] === currentPage,
  );
  const shownSections = new Set<string>();
  return (
    <div className="ws-tbl" role="table">
      <div className="ws-tbl__row ws-tbl__row--head" role="row">
        <div className="ws-tbl__cell ws-tbl__cell--head" role="columnheader">
          {strings.workspace.questionColumn}
        </div>
        <div className="ws-tbl__cell ws-tbl__cell--head" role="columnheader">
          {strings.workspace.answerColumn}
        </div>
      </div>
      {pageIds.map((qid) => {
        const question = schemaProperties[qid];
        const section = sectionHeadings.find((candidate) =>
          candidate.ids.includes(qid),
        );
        const showHeading =
          Boolean(section) && !shownSections.has(section!.label);
        if (section && showHeading) shownSections.add(section.label);
        const isFollowUp = followUps.has(qid);
        const content = byName.get(qid)?.content;
        const problem = fieldProblems[qid];
        return (
          <Fragment key={qid}>
            {showHeading && (
              <div className="ws-tbl__section" role="row">
                {section!.label}
              </div>
            )}
            <div
              className={
                "ws-tbl__row" + (isFollowUp ? " ws-tbl__row--sub" : "")
              }
              role="row"
            >
              <div className="ws-tbl__cell ws-tbl__cell--question" role="cell">
                {typeof question?.title === "string" ? question.title : qid}
              </div>
              <div
                className={
                  "ws-tbl__cell ws-tbl__cell--answer" +
                  (problem ? " ws-tbl__cell--problem" : "")
                }
                role="cell"
              >
                {content}
                {problem && (
                  <span className="ws-problem__badge" aria-hidden="true">
                    !
                  </span>
                )}
                {problem && (
                  <p className="ws-problem__message">{problem.message}</p>
                )}
              </div>
            </div>
          </Fragment>
        );
      })}
    </div>
  );
}

/** Builds the whole-schema `uiSchema` once from the answer-control mapping (spec assumption). */
function buildUiSchema(schema: Schema): Record<string, unknown> {
  const uiSchema: Record<string, unknown> = {};
  for (const [qid, raw] of Object.entries(schema.properties)) {
    const question = raw as Record<string, unknown>;
    const options: Record<string, unknown> = { label: false };
    if (question["x-labels"]) options.enumNames = question["x-labels"];
    const unit = unitFor(qid);
    if (unit) options.unit = unit;
    if (Array.isArray(question["x-exclusive"])) {
      options.exclusiveValues = question["x-exclusive"];
    }
    const entry: Record<string, unknown> = { "ui:options": options };
    const widget = chooseWidget(qid, question);
    if (widget) entry["ui:widget"] = widget;
    uiSchema[qid] = entry;
  }
  return uiSchema;
}

/** The ids required right now: unconditionally, or a follow-up whose gating question is active
 * (which, since it's active, means its gating condition currently holds -- AD-15). `P1`/`P3` are
 * real, answerable controls since Story 2.3 (`ProductWidget`/`TermWidget`), so -- unlike before --
 * nothing is dropped from the released schema's own `required` list here. */
function requiredNowIds(schema: Schema, active: Set<string>): Set<string> {
  const required = new Set(schema.required);
  for (const id of followUpIds(schema)) {
    if (active.has(id)) required.add(id);
  }
  return required;
}

/**
 * Whether `value` is a valid answer to `questionSchema`, for the progress indicator only
 * (EXPERIENCE.md "Completion check" -- decorative, convenience UI feedback that never gates a
 * write, coding-style.md rule 16). Deliberately hand-written rather than routed through Ajv: Ajv
 * compiles every schema it validates via `new Function` at runtime, which this app's CSP
 * (`script-src 'self'`, security.md rule 24, no `unsafe-eval`) blocks outright. RJSF's own
 * `validator` never hits this, because the form below runs with `liveValidate={false}` and no
 * submit is ever attempted; this function must stay off that path too. It covers exactly the
 * JSON-schema keywords `form-schema/v1.json` actually uses (checked directly): `type`, `enum`,
 * `minLength`/`maxLength`, `minimum`/`maximum`/`exclusiveMinimum`, `format: date`, and an array's
 * `minItems`.
 */
function isAnswered(
  questionSchema: Record<string, unknown>,
  value: unknown,
): boolean {
  if (value === null || value === undefined) return false;
  const type = questionSchema.type;
  const enumValues = questionSchema.enum;
  if (type === "string") {
    if (typeof value !== "string" || value.trim() === "") return false;
    if (Array.isArray(enumValues) && !enumValues.includes(value)) return false;
    if (
      typeof questionSchema.minLength === "number" &&
      value.length < questionSchema.minLength
    ) {
      return false;
    }
    if (
      typeof questionSchema.maxLength === "number" &&
      value.length > questionSchema.maxLength
    ) {
      return false;
    }
    if (
      questionSchema.format === "date" &&
      !/^\d{4}-\d{2}-\d{2}$/.test(value)
    ) {
      return false;
    }
    return true;
  }
  if (type === "number" || type === "integer") {
    if (typeof value !== "number" || Number.isNaN(value)) return false;
    if (type === "integer" && !Number.isInteger(value)) return false;
    if (
      typeof questionSchema.minimum === "number" &&
      value < questionSchema.minimum
    ) {
      return false;
    }
    if (
      typeof questionSchema.maximum === "number" &&
      value > questionSchema.maximum
    ) {
      return false;
    }
    if (
      typeof questionSchema.exclusiveMinimum === "number" &&
      value <= questionSchema.exclusiveMinimum
    ) {
      return false;
    }
    return true;
  }
  if (type === "array") {
    if (!Array.isArray(value)) return false;
    if (
      typeof questionSchema.minItems === "number" &&
      value.length < questionSchema.minItems
    ) {
      return false;
    }
    return true;
  }
  return true;
}

/**
 * A page is done when it has at least one required-and-active question and every one of them has
 * a valid answer (EXPERIENCE.md "Completion check"). Page 2 can complete once `P1`/`P3` (both in
 * the released schema's own `required`) are answered through their real Story 2.3 controls.
 */
function computeDonePages(
  schema: Schema,
  active: Set<string>,
  answers: Record<string, unknown>,
): Set<number> {
  const required = requiredNowIds(schema, active);
  const byPage = new Map<number, string[]>();
  for (const [qid, raw] of Object.entries(schema.properties)) {
    if (!required.has(qid)) continue;
    const page = (raw as Record<string, unknown>)["x-page"];
    if (typeof page !== "number") continue;
    byPage.set(page, [...(byPage.get(page) ?? []), qid]);
  }
  const done = new Set<number>();
  for (const [page, ids] of byPage) {
    const allAnswered = ids.every((qid) =>
      isAnswered(
        schema.properties[qid] as Record<string, unknown>,
        answers[qid],
      ),
    );
    if (ids.length > 0 && allAnswered) done.add(page);
  }
  return done;
}

/** Strips RJSF's `idPrefix` ("root_") from a Form-level `onBlur`'s element id, back to the plain
 * schema question id `commit` expects (Story 1.10). */
function qidFromElementId(id: string): string {
  const prefix = "root_";
  return id.startsWith(prefix) ? id.slice(prefix.length) : id;
}

/** "Saving…" then "Saved ✓", `role="status"` (EXPERIENCE.md "Save status", UX-DR20). Blank until
 * the first edit: there is no Save button and nothing to report before she has changed anything. */
function SaveStatus({ status }: { status: "idle" | "saving" | "saved" }) {
  return (
    <span className="ws-save-status" role="status">
      {status === "saving" && strings.workspace.saving}
      {status === "saved" && (
        <>
          {strings.workspace.saved}{" "}
          <span className="ws-save-status__check" aria-hidden="true">
            ✓
          </span>
        </>
      )}
    </span>
  );
}

/**
 * The lock-elsewhere info note plus its "Edit here instead" button (Story 4.4, DESIGN.md
 * Components "Info note"/"Other-window note", EXPERIENCE.md "Lock elsewhere"). Shown whenever the
 * caller isn't the holder; the button is refused while the AI holds it live (Story 4.5 gives that
 * case its own "AI is filling in answers…" note -- until then both `other_session` and `ai` share
 * this same wording, per spec ASSUMPTION 2).
 */
function LockNote({
  holder,
  onTakeOver,
}: {
  holder: "other_session" | "ai";
  onTakeOver: () => void;
}) {
  const disabled = holder === "ai";
  return (
    <span className="workspace__lock-note">
      <InfoNote>{strings.workspace.lockedElsewhereNote}</InfoNote>
      <PillButton
        variant="secondary"
        onClick={onTakeOver}
        disabled={disabled}
        disabledReason={strings.workspace.editHereInsteadDisabledReason}
      >
        {strings.workspace.editHereInstead}
      </PillButton>
    </span>
  );
}

/** The submitted strip (Story 3.2, DESIGN.md Components "Submitted strip"): a forest-tint pill
 * across the top of the form card once a proposal is submitted -- read-only everywhere, no lock
 * note or save status makes sense to show alongside it any more. */
function SubmittedStrip({
  submittedAt,
  customerNumber,
}: {
  submittedAt: string | null;
  customerNumber: string | null;
}) {
  return (
    <div className="ws-submitted-strip">
      <span className="ws-submitted-strip__check" aria-hidden="true">
        ✓
      </span>
      <span>
        {strings.workspace.submittedOn(formatSubmittedDate(submittedAt))}
      </span>
      {customerNumber && (
        <span className="ws-submitted-strip__customer-number">
          {strings.customerNumberLabel(customerNumber)}
        </span>
      )}
    </div>
  );
}

/** The red system-failure banner, identical for a failed save and a lost connection
 * (EXPERIENCE.md State Patterns), `role="alert"`. */
function ErrorBanner({
  text,
  onRetry,
}: {
  text: string;
  onRetry?: () => void;
}) {
  return (
    <div className="ws-banner" role="alert">
      <span className="ws-banner__icon" aria-hidden="true">
        !
      </span>
      <span>{text}</span>
      {onRetry && (
        <button type="button" className="ws-banner__retry" onClick={onRetry}>
          {strings.workspace.retry}
        </button>
      )}
    </div>
  );
}

function SkeletonRows() {
  return (
    <div className="ws-tbl ws-tbl--skeleton" aria-busy="true">
      {Array.from({ length: 6 }, (_, index) => (
        <div className="ws-tbl__row" key={index}>
          <span className="ws-skeleton-bar ws-skeleton-bar--question" />
          <span className="ws-skeleton-bar ws-skeleton-bar--answer" />
        </div>
      ))}
    </div>
  );
}

/**
 * The proposal workspace (Story 1.9): a page menu and form card on top, a static chat placeholder
 * frame below. Loads the draft and its pinned schema in parallel; a 404 on either sends her back
 * to Drafts (FR13), same as another agent's proposal id.
 */
export function Workspace({ draftId }: { draftId: string }) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [currentPage, setCurrentPage] = useState(1);
  const [collapsed, setCollapsed] = useState(false);
  // Unlike ProposalsPage's two separate routes, React Router does not remount `WorkspacePage`
  // when only the `:id` param changes on this same route, so `draftId` can change under an
  // already-mounted `Workspace`. Reset every bit of this component's own state for the new draft
  // here, during render (React's documented pattern for "adjusting state when a prop changes"),
  // rather than with a setState call in the effect below, which would trigger an extra render.
  const [loadedForId, setLoadedForId] = useState(draftId);
  const [products, setProducts] = useState<Product[] | null>(null);
  // Story 3.1: Submit's own in-flight/failure state, reset alongside everything else above the
  // moment `draftId` changes under this same mounted `Workspace` (same reasoning as `loadedForId`).
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Story 4.5: true from the moment she sends a chat message until that turn's stream ends
  // (cleanly or not) -- ChatPanel's own onTurnActiveChange, so the form goes read-only
  // immediately rather than waiting for the next 20s lock heartbeat (EXPERIENCE.md "AI replying").
  const [chatTurnActive, setChatTurnActive] = useState(false);
  // Bumped by ChatPanel's onDone (AC11: stream ends -> re-fetch draft); the draft-load effect
  // below reruns on either a new draftId or a new reloadKey, refetching in place with no reset of
  // currentPage/collapsed -- the form must stay on screen, never blank or spinning.
  const [reloadKey, setReloadKey] = useState(0);
  // Story 3.3: the declaration -> feedback modal flow, and its own rating/comment/in-flight state
  // -- reset alongside everything else above for the same reason.
  const [submitModal, setSubmitModal] = useState<
    "none" | "declaration" | "feedback"
  >("none");
  const [rating, setRating] = useState<number | null>(null);
  const [comment, setComment] = useState("");
  const [confirming, setConfirming] = useState(false);
  // Story FORM-227: the workspace's own delete-draft button and its shared confirmation modal --
  // reset alongside everything else above for the same reason.
  const [deleteModalOpen, setDeleteModalOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);
  if (draftId !== loadedForId) {
    setLoadedForId(draftId);
    setState({ status: "loading" });
    setCurrentPage(1);
    setCollapsed(false);
    setProducts(null);
    setSubmitting(false);
    setSubmitError(null);
    setChatTurnActive(false);
    setSubmitModal("none");
    setRating(null);
    setComment("");
    setConfirming(false);
    setDeleteModalOpen(false);
    setDeleting(false);
    setDeleteError(null);
  }
  const navigate = useNavigate();

  // The draft `handleSubmitClick`'s continuation should still believe is current: mirrors
  // autosave.ts's `currentDraftIdRef`/`isCurrentDraft()` guard for the exact same race (a
  // `validateDraft` call still in flight for the previous draftId can resolve after she has
  // already navigated to a new one).
  const currentDraftIdRef = useRef(draftId);
  useEffect(() => {
    currentDraftIdRef.current = draftId;
  });

  // FORM-21 bug fix: `formData={state.draft.answers}` (below) makes RJSF's `<Form>` fully
  // controlled -- on *any* change to that prop (even one from an unrelated field's own save),
  // RJSF resyncs its whole internal formData tree from it (`getStateFromProps`), discarding
  // whatever she's still typing into a focused text/number/date field that hasn't been blurred
  // yet (that field's own `commit()`/PATCH, and so `state.draft`, has no idea it's being edited
  // until blur). That unrelated save landing mid-keystroke -- much more likely once a PATCH
  // round-trip takes a beat, e.g. Story 4.3 Part B's row-level security or Story 4.9's
  // `answer_overrides` insert -- used to blank the field she was still editing, and the empty
  // value was then what her next blur committed.
  //
  // `focusedFieldRef` names the one field (if any) currently focused (read/written only from
  // event handlers below, never during render); `liveField` mirrors RJSF's own internal value
  // for it on every keystroke, via the `<Form>`'s own `onChange` (never sent anywhere --
  // `commit()` still only ever fires on blur, exactly as before). The `formData` passed down
  // below overlays that live value onto `state.draft.answers`, so however often an unrelated save
  // replaces the rest of the tree, RJSF's resync always finds this one field already holding what
  // she actually typed, never a stale or blank one. `state.draft` itself keeps updating
  // immediately on every save, exactly as before this fix -- only the `<Form>`'s own `formData`
  // prop gets this one-field overlay -- so `revision` tracking (autosave.ts's own `revisionRef`)
  // is untouched by any of this.
  const focusedFieldRef = useRef<string | null>(null);
  const [liveField, setLiveField] = useState<{
    id: string;
    value: unknown;
  } | null>(null);
  // A new draft: drop whatever this component instance still remembers about the previous one
  // (mirrors autosave.ts's own `[draftId, clearRetryTimer]` reset effect) -- a ref write belongs
  // in an effect, never during render.
  useEffect(() => {
    focusedFieldRef.current = null;
  }, [draftId]);
  // Alongside everything else above, during render (`loadedForId`'s own reasoning) --
  // `loadedForId` itself hasn't advanced to `draftId` yet in this same render.
  if (draftId !== loadedForId) {
    setLiveField(null);
  }
  // She's confirmed (the save came back) or undone (typed back to what's already stored) the
  // field `liveField` overlays: clear it now, during render like `useLocalOverride`'s own reset,
  // so `formData` never holds a stale override past the moment it stops mattering.
  if (
    state.status === "loaded" &&
    liveField !== null &&
    Object.is(state.draft.answers[liveField.id], liveField.value)
  ) {
    setLiveField(null);
  }

  useEffect(() => {
    let current = true;
    Promise.all([getDraft(draftId), getSchema(draftId)]).then(
      ([draft, schema]) => {
        if (current) setState({ status: "loaded", draft, schema });
      },
      (error: unknown) => {
        if (!current) return;
        setState({
          status: error instanceof NotFoundError ? "not-found" : "error",
        });
      },
    );
    return () => {
      current = false;
    };
    // Story 4.5, AC11: reloadKey reruns this same effect in place (no status reset -> no blank
    // flash, no spinner) once a chat turn's stream ends.
  }, [draftId, reloadKey]);

  // Story 2.3: the eligible-and-priced product list for `ProductWidget`/`RiderWidget`/
  // `TermWidget`, refetched once the draft has loaded and again every time its `revision` bumps
  // (a C2 or P1 write can change who's eligible) -- never on every render, so `revision` (a
  // primitive), not the whole `state` object, drives this effect (spec Code Map).
  const revision = state.status === "loaded" ? state.draft.revision : null;
  useEffect(() => {
    if (revision === null) return;
    let current = true;
    getProducts(draftId).then(
      (loaded) => {
        if (current) setProducts(loaded);
      },
      () => {
        // A transient failure here must not discard an already-loaded, still-valid product list
        // (which would revert every P1/P2/P3 control to "not loaded yet"); leave `products` as it
        // is and let the next revision bump retry.
      },
    );
    return () => {
      current = false;
    };
  }, [draftId, revision]);

  const displayName =
    state.status === "loaded" ? state.draft.displayName : null;
  useBreadcrumb(displayName);

  useEffect(() => {
    document.title = strings.documentTitle(
      displayName ?? strings.workspace.title,
    );
  }, [displayName]);

  const active = useMemo(
    () => new Set(state.status === "loaded" ? state.draft.active : []),
    [state],
  );
  const followUps = useMemo(
    () =>
      state.status === "loaded" ? followUpIds(state.schema) : new Set<string>(),
    [state],
  );
  const uiSchema = useMemo(
    () => (state.status === "loaded" ? buildUiSchema(state.schema) : {}),
    [state],
  );
  const donePages = useMemo(
    () =>
      state.status === "loaded"
        ? computeDonePages(state.schema, active, state.draft.answers)
        : new Set<number>(),
    [state, active],
  );

  // Story 4.4: acquires the lock on mount and renews it every 20s, whether or not the draft has
  // loaded yet (hooks can't be conditional) -- the very first PATCH already needs it held.
  const editLock = useEditLock(draftId);

  // Story 1.10: wired even before the draft loads (hooks can't be conditional); commit() has
  // nothing to diff against until then, but nothing calls it that early either.
  const autosave = useAutosave({
    draftId,
    revision: state.status === "loaded" ? state.draft.revision : 0,
    answers: state.status === "loaded" ? state.draft.answers : {},
    onSaved: (draft) => {
      // The response is the new draft wire shape: active/answers/revision/displayName all update
      // from it directly, no extra fetch (spec assumption "Breadcrumb/Drafts-row name"). Applied
      // immediately and unconditionally, exactly as before this fix -- see `focusedFieldRef`'s
      // own comment for why a focused field's in-progress edit still survives this.
      setState((current) =>
        current.status === "loaded" ? { ...current, draft } : current,
      );
    },
    // Story 4.4: a write lost the lock -- re-check right away rather than waiting up to 20s for
    // the next heartbeat, so the read-only switch already knows who holds it now.
    onLockLost: editLock.refresh,
  });

  // Story 3.1: which pages have at least one unresolved Submit problem right now -- a pure
  // function of `fieldProblems`, so a page loses its amber box the moment its last problem
  // clears (the existing per-field clearing in autosave.ts's successful-PATCH path), without
  // another Submit.
  const problemPages = useMemo(() => {
    const found = new Set<number>();
    if (state.status !== "loaded") return found;
    for (const questionId of Object.keys(autosave.fieldProblems)) {
      if (!active.has(questionId)) continue;
      const page = state.schema.properties[questionId]?.["x-page"];
      if (typeof page === "number") found.add(page);
    }
    return found;
  }, [state, active, autosave.fieldProblems]);

  if (state.status === "not-found") {
    return <Navigate to={paths.drafts} replace />;
  }

  const submitReason =
    state.status !== "loaded"
      ? null
      : editLock.lock.holder !== "you" || chatTurnActive
        ? strings.workspace.submitReadOnlyReason
        : autosave.banner === "offline"
          ? strings.workspace.submitOfflineReason
          : autosave.banner === "save-failed"
            ? strings.workspace.submitUnsavedReason
            : null;
  const submitDisabled = state.status !== "loaded" || submitReason !== null;

  async function handleSubmitClick() {
    if (state.status !== "loaded") return;
    // Captured now, not read again later: `currentDraftIdRef` may have moved on to a different
    // draft by the time this call resolves (mirrors autosave.ts's `send()`).
    const requestDraftId = draftId;
    const isCurrentDraft = () => currentDraftIdRef.current === requestDraftId;
    setSubmitting(true);
    setSubmitError(null);
    try {
      const fieldErrors = await validateDraft(draftId);
      if (!isCurrentDraft()) return;
      const problems: Record<string, FieldProblem> = {};
      for (const error of fieldErrors) {
        problems[error.field] = { message: error.message };
      }
      autosave.reportProblems(problems);
      if (fieldErrors.length > 0) {
        const problemPageNumbers = fieldErrors
          .map((error) => state.schema.properties[error.field]?.["x-page"])
          .filter((page): page is number => typeof page === "number");
        if (problemPageNumbers.length > 0) {
          setCurrentPage(Math.min(...problemPageNumbers));
        }
      } else {
        // Story 3.3: a clean result opens the declaration modal (the dead end this button used
        // to reach); "I agree" there moves to the feedback modal, never stacked (spec Boundaries).
        setSubmitModal("declaration");
      }
    } catch {
      if (!isCurrentDraft()) return;
      setSubmitError(strings.workspace.submitCheckFailedMessage);
    } finally {
      if (isCurrentDraft()) setSubmitting(false);
    }
  }

  /** "Cancel" on either modal, or Escape (Story 3.3 spec AC): closes it and returns focus to
   * "Submit proposal", without submitting anything. */
  function handleCancelModal() {
    setSubmitModal("none");
    document.getElementById(SUBMIT_BUTTON_ID)?.focus();
  }

  /** The feedback modal's own "Submit proposal" (Story 3.3): the one call that sets D1, upserts
   * `customer` and records the AI-rating feedback, all in one transaction (AD-8, AD-13). On
   * success, navigates to My proposals › Submitted with the success toast (EXPERIENCE.md); on
   * failure, closes the modals and re-opens the form with problems highlighted, exactly like
   * `handleSubmitClick`'s own validate-check failure path (spec AC). */
  async function handleConfirmSubmit() {
    if (state.status !== "loaded" || rating === null) return;
    const requestDraftId = draftId;
    const isCurrentDraft = () => currentDraftIdRef.current === requestDraftId;
    const trimmedComment = comment.trim();
    setConfirming(true);
    setSubmitError(null);
    try {
      await submitProposal(draftId, state.draft.revision, true, {
        rating,
        comment: trimmedComment === "" ? null : trimmedComment,
      });
      if (!isCurrentDraft()) return;
      navigate(paths.submitted, {
        state: { toast: strings.workspace.submitSuccessToast },
      });
    } catch (error) {
      if (!isCurrentDraft()) return;
      setSubmitModal("none");
      if (error instanceof ApiError && error.fieldErrors) {
        const problems: Record<string, FieldProblem> = {};
        for (const fieldError of error.fieldErrors) {
          problems[fieldError.field] = { message: fieldError.message };
        }
        autosave.reportProblems(problems);
        const problemPageNumbers = error.fieldErrors
          .map(
            (fieldError) =>
              state.schema.properties[fieldError.field]?.["x-page"],
          )
          .filter((page): page is number => typeof page === "number");
        if (problemPageNumbers.length > 0) {
          // A real field problem, on a real schema question (Story 3.1's own shape): jump to it
          // and highlight it, exactly as Story 3.1 does for validateDraft's own errors -- the
          // highlighted problem already explains what went wrong, so this needs no extra banner
          // (spec AC: "re-opens the form with problems highlighted as in Story 3.1").
          setCurrentPage(Math.min(...problemPageNumbers));
          return;
        }
      }
      // Anything else -- a conflict this session can't fix by editing a field (stale_revision,
      // lock_not_held, proposal_submitted) or a network failure -- has no question of its own to
      // highlight, so it gets the generic banner instead.
      setSubmitError(strings.workspace.submitFailedMessage);
    } finally {
      if (isCurrentDraft()) setConfirming(false);
    }
  }

  // FORM-222: schema-driven page scaffolding (v1's 5 pages, v2's 4), never a hardcoded count or
  // page-title map -- the fallback only covers the instant before the draft/schema have loaded.
  const pageNumbers =
    state.status === "loaded"
      ? pageNumbersOf(state.schema)
      : FALLBACK_PAGE_NUMBERS;
  // A schema version with no title map (a future v3+ this build predates) falls back to plain
  // page numbers rather than silently reusing v1's or v2's titles, which would be actively wrong
  // ("Needs" on a page that isn't Needs) -- `pages`/the heading below already turn a missing
  // title into `String(number)`.
  const pageTitles =
    state.status === "loaded"
      ? (strings.workspace.pagesByVersion[state.draft.schemaVersion] ?? {})
      : FALLBACK_PAGE_TITLES;
  // FORM-222: a page picked on the loading skeleton (v1's numbering) may not exist in the schema
  // that actually loaded (v2 has 4 pages, and Health & lifestyle is page 4, not 5). Move to the
  // loaded page with the same title, else the first page, instead of showing an empty page.
  if (state.status === "loaded" && !pageNumbers.includes(currentPage)) {
    const pickedTitle = FALLBACK_PAGE_TITLES[currentPage];
    const sameTitle = pageNumbers.find(
      (number) => pageTitles[number] === pickedTitle,
    );
    setCurrentPage(sameTitle ?? pageNumbers[0] ?? 1);
  }
  const lastPage = pageNumbers[pageNumbers.length - 1];
  const priceSummaryPages = new Set(
    pageNumbers.filter((number) =>
      PRICE_SUMMARY_TITLES.has(pageTitles[number] ?? ""),
    ),
  );

  /** The workspace's own delete button (Story FORM-227, spec Code Map): opens the same shared
   * confirmation modal as a Drafts row's own delete action. On confirm, deletes then navigates to
   * Drafts with the "Draft deleted." toast, reusing ProposalsPage's own location.state.toast read
   * (no new plumbing there); on failure, closes the modal and shows an inline error next to the
   * delete button instead (mirrors handleSubmitClick's own generic-banner fallback) -- the modal's
   * scrim covers the whole page, so an error left to render underneath it would never be seen. */
  async function handleConfirmDelete() {
    const requestDraftId = draftId;
    const isCurrentDraft = () => currentDraftIdRef.current === requestDraftId;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteProposal(draftId);
      if (!isCurrentDraft()) return;
      navigate(paths.drafts, {
        state: { toast: strings.deleteDraftModal.toast },
      });
    } catch (error) {
      if (!isCurrentDraft()) return;
      setDeleteModalOpen(false);
      setDeleteError(deleteFailedMessage(error));
    } finally {
      if (isCurrentDraft()) setDeleting(false);
    }
  }

  const pages: PageMenuPage[] = pageNumbers.map((number) => ({
    number,
    title: pageTitles[number] ?? String(number),
    current: number === currentPage,
    done: donePages.has(number),
    problem: problemPages.has(number),
  }));

  // Story 4.4: read-only whenever another session or the AI holds the lock (AD-16); the page menu
  // and page switching stay live either way (EXPERIENCE.md "Edit lock held elsewhere"). Story 3.2:
  // a submitted proposal is read-only everywhere too, regardless of who (if anyone) holds the
  // lock -- the frozen legal record, AD-8.
  const lockHolder = editLock.lock.holder;
  const submitted =
    state.status === "loaded" && state.draft.status === "submitted";
  // Story 4.5: also read-only for the instant a chat turn is active, even before the next lock
  // heartbeat notices the server already moved the lock to "ai" (EXPERIENCE.md "AI replying").
  const readOnly = submitted || lockHolder !== "you" || chatTurnActive;

  const workspaceUi = {
    currentPage,
    active,
    followUps,
    fieldProblems: autosave.fieldProblems,
    commit: autosave.commit,
    commitMany: autosave.commitMany,
    setFieldProblem: autosave.setFieldProblem,
    products,
    answers: state.status === "loaded" ? state.draft.answers : {},
  };
  const bannerText =
    autosave.banner === "save-failed"
      ? strings.workspace.saveFailedMessage
      : autosave.banner === "offline"
        ? strings.workspace.connectionLostMessage
        : null;

  return (
    <div className="workspace">
      {/* Every other page has exactly one h1 (the breadcrumb and the page-title h2 below already
          carry the visible context, per DESIGN.md/mockups, which don't call for a second visible
          heading here); a screen-reader-only one keeps the page's heading structure consistent and
          gives axe's "page-has-heading-one" a real target. */}
      <h1 className="visually-hidden">
        {displayName ?? strings.workspace.title}
      </h1>
      <div className="workspace__work">
        <PageMenu
          pages={pages}
          collapsed={collapsed}
          onToggleCollapse={() => setCollapsed((value) => !value)}
          onSelectPage={setCurrentPage}
          doneCount={donePages.size}
          totalCount={pageNumbers.length}
        />
        <GlassCard as="section" className="workspace__form">
          <div className="workspace__form-head">
            <h2>
              {strings.workspace.pageHeading(
                currentPage,
                pageTitles[currentPage] ?? String(currentPage),
              )}
            </h2>
            {state.status === "loaded" &&
              (submitted ? (
                <SubmittedStrip
                  submittedAt={state.draft.submittedAt}
                  customerNumber={state.draft.customerNumber}
                />
              ) : chatTurnActive ? (
                <InfoNote dots>{strings.workspace.aiReplyingNote}</InfoNote>
              ) : lockHolder === "other_session" || lockHolder === "ai" ? (
                <LockNote holder={lockHolder} onTakeOver={editLock.takeOver} />
              ) : (
                <SaveStatus status={autosave.saveStatus} />
              ))}
            {/* Story FORM-227: never offered once submitted -- a submitted proposal is the
                frozen legal record (AD-8), same reasoning as the chat panel below. */}
            {state.status === "loaded" && !submitted && (
              <span className="workspace__delete-draft">
                <PillButton
                  variant="destructive"
                  onClick={() => setDeleteModalOpen(true)}
                >
                  {strings.workspace.deleteDraft}
                </PillButton>
                {deleteError && (
                  <span className="pill-button-reason" role="alert">
                    {deleteError}
                  </span>
                )}
              </span>
            )}
          </div>
          {bannerText && (
            <ErrorBanner
              text={bannerText}
              onRetry={
                autosave.banner === "save-failed" ? autosave.retry : undefined
              }
            />
          )}
          {state.status === "loading" && <SkeletonRows />}
          {state.status === "error" && (
            <p className="workspace__error">{strings.workspace.loadError}</p>
          )}
          {state.status === "loaded" && (
            <WorkspaceUiContext.Provider value={workspaceUi}>
              <Form
                schema={state.schema as RJSFSchema}
                uiSchema={uiSchema}
                formData={
                  liveField
                    ? {
                        ...state.draft.answers,
                        [liveField.id]: liveField.value,
                      }
                    : state.draft.answers
                }
                validator={validator}
                templates={{
                  ObjectFieldTemplate: WorkspaceObjectFieldTemplate,
                  FieldTemplate: RowFieldTemplate,
                }}
                widgets={workspaceWidgets}
                liveValidate={false}
                noHtml5Validate
                showErrorList={false}
                readonly={readOnly}
                tagName="div"
                onFocus={(id) => {
                  focusedFieldRef.current = qidFromElementId(id);
                }}
                onChange={(data) => {
                  // Mirrors RJSF's own live value for the focused field only (see
                  // `liveField`'s own comment above) -- never sent anywhere; `commit()` still
                  // only ever runs on blur, exactly as before this fix.
                  const qid = focusedFieldRef.current;
                  if (qid === null) return;
                  const formData = data.formData as
                    Record<string, unknown> | undefined;
                  setLiveField({ id: qid, value: formData?.[qid] });
                }}
                onBlur={(id, value) => {
                  focusedFieldRef.current = null;
                  // `liveField` is left in place here on purpose (cleared above, during render,
                  // once `state.draft.answers` actually confirms or matches it): clearing it
                  // immediately on blur -- before her write round-trips -- would drop `formData`
                  // back to the still-stale stored value and flash the field back to it (and, if
                  // the write is later rejected, UX-DR43 wants her typed value to stay on screen
                  // regardless).
                  autosave.commit(qidFromElementId(id), value);
                }}
                onSubmit={(_data, event) => event.preventDefault()}
              >
                <></>
              </Form>
              {priceSummaryPages.has(currentPage) && (
                <PriceSummary quote={state.draft.quote} />
              )}
            </WorkspaceUiContext.Provider>
          )}
          {state.status === "loaded" &&
            currentPage === lastPage &&
            !submitted && (
              <div className="ws-submit-row">
                <PillButton
                  id={SUBMIT_BUTTON_ID}
                  variant="primary"
                  disabled={submitDisabled || submitting}
                  disabledReason={
                    submitReason ??
                    (submitting ? strings.workspace.submitCheckingReason : "")
                  }
                  onClick={handleSubmitClick}
                >
                  {strings.workspace.submitProposal}
                </PillButton>
                {submitError && (
                  <span className="pill-button-reason" role="alert">
                    {submitError}
                  </span>
                )}
              </div>
            )}
        </GlassCard>
      </div>
      {/* Absent, not just disabled, once submitted (Story 3.2, EXPERIENCE.md): there is nothing
          left to chat about on the frozen legal record. */}
      {!submitted && (
        <GlassCard as="section" className="workspace__chat">
          <ChatPanel
            draftId={draftId}
            canSend={lockHolder === "you"}
            onTurnActiveChange={setChatTurnActive}
            onDone={() => setReloadKey((key) => key + 1)}
          />
        </GlassCard>
      )}
      {submitModal === "declaration" && (
        <DeclarationModal
          onAgree={() => setSubmitModal("feedback")}
          onCancel={handleCancelModal}
        />
      )}
      {submitModal === "feedback" && (
        <FeedbackModal
          rating={rating}
          comment={comment}
          onRatingChange={setRating}
          onCommentChange={setComment}
          onCancel={handleCancelModal}
          onSubmit={handleConfirmSubmit}
          submitting={confirming}
        />
      )}
      {deleteModalOpen && (
        <DeleteConfirmModal
          name={displayName ?? strings.workspace.title}
          onCancel={() => setDeleteModalOpen(false)}
          onConfirm={handleConfirmDelete}
          deleting={deleting}
        />
      )}
    </div>
  );
}
