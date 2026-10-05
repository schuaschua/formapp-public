import { ApiError } from "../api/client";
import { ModalShell } from "../pages/workspace/SubmitModals";
import { strings } from "../strings";
import { PillButton } from "./PillButton";

/**
 * The shared destructive confirmation modal for hard-deleting a draft (Story FORM-227, spec
 * Intent): opened from both the Drafts row's own delete action and the workspace's own delete
 * button, one component reused by both call sites (spec Boundaries). Reuses `SubmitModals`'
 * `ModalShell` (focus trap, `role="dialog"`, Escape-to-cancel) rather than duplicating it; Cancel
 * and Escape both leave everything unchanged.
 */
export function DeleteConfirmModal({
  name,
  onCancel,
  onConfirm,
  deleting,
}: {
  /** The draft's display name, named in the modal's own title (spec Code Map). */
  name: string;
  onCancel: () => void;
  onConfirm: () => void;
  deleting: boolean;
}) {
  return (
    <ModalShell
      titleId="delete-draft-modal-title"
      title={strings.deleteDraftModal.title(name)}
      onCancel={onCancel}
    >
      <p className="submit-modal__declaration-box">
        {strings.deleteDraftModal.body}
      </p>
      <div className="submit-modal__actions">
        <PillButton variant="cancel" size="modal" onClick={onCancel}>
          {strings.deleteDraftModal.cancel}
        </PillButton>
        <PillButton
          variant="destructive"
          size="modal"
          disabled={deleting}
          disabledReason={deleting ? strings.deleteDraftModal.deleting : ""}
          onClick={onConfirm}
        >
          {deleting
            ? strings.deleteDraftModal.deleting
            : strings.deleteDraftModal.confirm}
        </PillButton>
      </div>
    </ModalShell>
  );
}

/** FORM-232: the message for a failed delete, from either call site. A reload starts a new tab
 * session, so her own old tab's live lock (AD-16) or a running AI turn refuses the delete for a
 * while; say which, rather than a bare "try again". */
export function deleteFailedMessage(error: unknown): string {
  const codes =
    error instanceof ApiError
      ? (error.fieldErrors ?? []).map((fieldError) => fieldError.code)
      : [];
  if (codes.includes("lock_not_held"))
    return strings.deleteDraftModal.lockedMessage;
  if (codes.includes("turn_in_progress"))
    return strings.deleteDraftModal.aiBusyMessage;
  return strings.deleteDraftModal.failedMessage;
}
