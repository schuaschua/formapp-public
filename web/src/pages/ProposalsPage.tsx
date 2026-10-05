import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router";
import {
  createProposal,
  deleteProposal,
  listProposals,
  type ProposalStatusValue,
  type ProposalSummary,
} from "../api/client";
import { paths, proposalPath } from "../app/paths";
import {
  DeleteConfirmModal,
  deleteFailedMessage,
} from "../components/DeleteConfirmModal";
import { GlassCard } from "../components/GlassCard";
import { PillButton } from "../components/PillButton";
import { strings } from "../strings";
import { Toast } from "./workspace/Toast";
import "./ProposalsPage.css";

const SKELETON_ROW_COUNT = 3;
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
// The server names an unnamed draft Untitled_Proposal_NNN (FR11); matching it here only decides
// which font to render it in (UX-DR12), never a value the domain computes.
const UNTITLED_NAME = /^Untitled_Proposal_\d{3,}$/;

type ListState =
  | { status: "loading" }
  | { status: "loaded"; proposals: ProposalSummary[] }
  | { status: "error" };

function formatDate(iso: string): string {
  // UTC, not local: `created_at` is a UTC instant, and the calendar date must never drift with the
  // viewer's timezone or CI's, matching the mockup's "Created 25 Sep 2026" style exactly.
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${date.getUTCDate()} ${MONTHS[date.getUTCMonth()]} ${date.getUTCFullYear()}`;
}

function StatusChip({ status }: { status: ProposalStatusValue }) {
  const label =
    status === "draft"
      ? strings.proposals.statusDraft
      : strings.proposals.statusSubmitted;
  return <span className={`status-chip status-chip--${status}`}>{label}</span>;
}

function SkeletonRows() {
  return (
    <div className="proposals-rows" aria-busy="true">
      {Array.from({ length: SKELETON_ROW_COUNT }, (_, index) => (
        <div
          key={index}
          className="proposals-row__link proposals-row--skeleton"
          data-testid="skeleton-row"
        >
          <span className="proposals-skeleton-bar proposals-skeleton-bar--name" />
          <span className="proposals-skeleton-bar proposals-skeleton-bar--chip" />
          <span className="proposals-skeleton-bar proposals-skeleton-bar--date" />
          <span />
        </div>
      ))}
    </div>
  );
}

function EmptyState({
  status,
  creating,
  onCreate,
}: {
  status: ProposalStatusValue;
  creating: boolean;
  onCreate: () => void;
}) {
  const text =
    status === "draft"
      ? strings.proposals.emptyDrafts
      : strings.proposals.emptySubmitted;
  return (
    <div className="proposals-empty">
      <div className="proposals-empty__icon" aria-hidden="true" />
      <h2>{text}</h2>
      {/* EXPERIENCE.md: "Drafts offers + New proposal, Submitted offers nothing" (UX-DR11). */}
      {status === "draft" && (
        <PillButton
          variant="primary"
          onClick={onCreate}
          disabled={creating}
          disabledReason={strings.proposals.creating}
        >
          {strings.proposals.newProposal}
        </PillButton>
      )}
    </div>
  );
}

function RowsList({
  proposals,
  status,
  onDeleteRequest,
}: {
  proposals: ProposalSummary[];
  status: ProposalStatusValue;
  /** Opens the shared delete-confirm modal for this row (Story FORM-227): drafts only -- a
   * submitted proposal never offers delete (spec Intent). */
  onDeleteRequest: (proposal: ProposalSummary) => void;
}) {
  const prefix =
    status === "draft"
      ? strings.proposals.createdPrefix
      : strings.proposals.submittedPrefix;
  return (
    <ul className="proposals-rows">
      {proposals.map((proposal) => {
        // The Submitted tab formats submittedAt, not createdAt (Story 3.2, FR9): the two can
        // differ, since a draft can sit unsubmitted for a while before she submits it.
        const date =
          status === "submitted"
            ? (proposal.submittedAt ?? "")
            : proposal.createdAt;
        return (
          <li key={proposal.id} className="proposals-row">
            <Link
              to={proposalPath(proposal.id)}
              className="proposals-row__link"
            >
              <span
                className={
                  "proposals-row__name" +
                  (UNTITLED_NAME.test(proposal.displayName)
                    ? " proposals-row__name--untitled"
                    : "")
                }
              >
                {proposal.displayName}
              </span>
              <StatusChip status={proposal.status} />
              <span className="proposals-row__date">
                {prefix} {formatDate(date)}
                {status === "submitted" && proposal.customerNumber && (
                  <>
                    {" · "}
                    {strings.customerNumberLabel(proposal.customerNumber)}
                  </>
                )}
              </span>
              <span className="proposals-row__chevron" aria-hidden="true">
                &#x203A;
              </span>
            </Link>
            {status === "draft" && (
              <button
                type="button"
                className="proposals-row__delete"
                aria-label={strings.proposals.deleteRowLabel(
                  proposal.displayName,
                )}
                onClick={() => onDeleteRequest(proposal)}
              >
                &#x2715;
              </button>
            )}
          </li>
        );
      })}
    </ul>
  );
}

/**
 * My proposals: Drafts and Submitted (Story 1.8, UX-DR9, UX-DR10, UX-DR11). One flat card holds
 * the title, tabs and "+ New proposal" on one line, then the list: skeleton rows while loading,
 * a centred empty tile, or the rows themselves, each one link that opens the workspace.
 */
export function ProposalsPage({ status }: { status: ProposalStatusValue }) {
  const [state, setState] = useState<ListState>({ status: "loading" });
  const [creating, setCreating] = useState(false);
  // A ref, not just the `creating` state: two clicks dispatched before React re-renders must still
  // see each other synchronously, so only the first one ever starts a request (UX-DR: one draft).
  const creatingRef = useRef(false);
  const navigate = useNavigate();
  const location = useLocation();
  const tabLabel =
    status === "draft" ? strings.proposals.drafts : strings.proposals.submitted;

  useEffect(() => {
    document.title = strings.documentTitle(tabLabel);
  }, [tabLabel]);

  // Story 3.3: the success toast a submit's own navigate() carries in location.state (EXPERIENCE.md
  // "After submit ... shows the toast"). The lazy initializer reads it once, at mount, straight from
  // the location this component first rendered with -- not an effect, since it's deriving initial
  // state rather than synchronizing with an external system (react.dev "You Might Not Need an
  // Effect"). Clearing it from history (replace, state: null) *is* a real side effect on that
  // external system, so that alone runs in an effect, guarded the same way so it fires once.
  const [toast, setToast] = useState<string | null>(
    () => (location.state as { toast?: string } | null)?.toast ?? null,
  );
  useEffect(() => {
    if ((location.state as { toast?: string } | null)?.toast) {
      navigate(location.pathname, { replace: true, state: null });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const dismissToast = useCallback(() => setToast(null), []);

  // Story FORM-227: the shared delete-confirm modal's own state -- the row it's open for (null:
  // closed), whether the delete call is in flight, and its own failure message (kept separate from
  // `toast`, which is only ever the success case).
  const [deleteTarget, setDeleteTarget] = useState<ProposalSummary | null>(
    null,
  );
  const [deleting, setDeleting] = useState(false);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function handleDeleteRequest(proposal: ProposalSummary) {
    setDeleteError(null);
    setDeleteTarget(proposal);
  }

  function handleCancelDelete() {
    setDeleteTarget(null);
    setDeleteError(null);
  }

  async function handleConfirmDelete() {
    if (deleteTarget === null) return;
    setDeleting(true);
    setDeleteError(null);
    try {
      await deleteProposal(deleteTarget.id);
      setState((current) =>
        current.status === "loaded"
          ? {
              status: "loaded",
              proposals: current.proposals.filter(
                (proposal) => proposal.id !== deleteTarget.id,
              ),
            }
          : current,
      );
      setDeleteTarget(null);
      setToast(strings.deleteDraftModal.toast);
    } catch (error) {
      // Closed here too (mirrors Workspace's own delete-button failure path): the modal's scrim
      // covers the whole page, so an error left to render underneath it would never be seen.
      setDeleteTarget(null);
      setDeleteError(deleteFailedMessage(error));
    } finally {
      setDeleting(false);
    }
  }

  useEffect(() => {
    // `status` never actually changes on a mounted ProposalsPage: Drafts and Submitted are two
    // routes, each mounting its own instance, so the initial "loading" state below is the only one
    // this effect ever needs to set for it (no synchronous reset here, which a plain re-fetch on
    // prop change would need).
    let current = true;
    listProposals(status).then(
      (proposals) => {
        if (current) setState({ status: "loaded", proposals });
      },
      () => {
        if (current) setState({ status: "error" });
      },
    );
    return () => {
      current = false;
    };
  }, [status]);

  async function handleCreate() {
    if (creatingRef.current) return;
    creatingRef.current = true;
    setCreating(true);
    try {
      const draft = await createProposal();
      navigate(proposalPath(draft.id), {
        state: { displayName: draft.displayName },
      });
    } catch {
      creatingRef.current = false;
      setCreating(false);
    }
  }

  // The header row drops its own "+ New proposal" once the Drafts list is confirmed empty: the
  // empty tile below offers the one, centred copy instead (mockups/key-proposals.html, section C).
  const hideHeaderButton =
    status === "draft" &&
    state.status === "loaded" &&
    state.proposals.length === 0;

  return (
    <GlassCard
      as="section"
      className="proposals-page"
      aria-labelledby="proposals-title"
    >
      <div className="proposals-page__head">
        <h1 id="proposals-title">{strings.proposals.title}</h1>
        <nav className="proposals-tabs" aria-label={strings.proposals.title}>
          <Link
            to={paths.drafts}
            aria-current={status === "draft" ? "page" : undefined}
            className={
              "proposals-tab" +
              (status === "draft" ? " proposals-tab--selected" : "")
            }
          >
            {strings.proposals.drafts}
          </Link>
          <Link
            to={paths.submitted}
            aria-current={status === "submitted" ? "page" : undefined}
            className={
              "proposals-tab" +
              (status === "submitted" ? " proposals-tab--selected" : "")
            }
          >
            {strings.proposals.submitted}
          </Link>
        </nav>
        {!hideHeaderButton && (
          <div className="proposals-page__actions">
            <PillButton
              variant="primary"
              onClick={handleCreate}
              disabled={creating}
              disabledReason={strings.proposals.creating}
            >
              {strings.proposals.newProposal}
            </PillButton>
          </div>
        )}
      </div>
      {state.status === "loading" && <SkeletonRows />}
      {state.status === "error" && (
        <p className="proposals-error">{strings.proposals.loadError}</p>
      )}
      {state.status === "loaded" && state.proposals.length === 0 && (
        <EmptyState
          status={status}
          creating={creating}
          onCreate={handleCreate}
        />
      )}
      {state.status === "loaded" && state.proposals.length > 0 && (
        <RowsList
          proposals={state.proposals}
          status={status}
          onDeleteRequest={handleDeleteRequest}
        />
      )}
      {toast && <Toast message={toast} onDismiss={dismissToast} />}
      {deleteTarget && (
        <DeleteConfirmModal
          name={deleteTarget.displayName}
          onCancel={handleCancelDelete}
          onConfirm={handleConfirmDelete}
          deleting={deleting}
        />
      )}
      {deleteError && (
        <p className="proposals-error" role="alert">
          {deleteError}
        </p>
      )}
    </GlassCard>
  );
}
