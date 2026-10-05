import {
  useEffect,
  useId,
  useRef,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { PillButton } from "../../components/PillButton";
import { strings } from "../../strings";
import "./SubmitModals.css";

const FOCUSABLE_SELECTOR =
  'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * The shared modal shell for the declaration and feedback modals (Story 3.3, EXPERIENCE.md "Submit
 * modals", DESIGN.md Components "Modal"): a scrim, `role="dialog"`/`aria-modal`/`aria-labelledby`,
 * and a hand-rolled focus trap -- `web/package.json` has no a11y/focus library, and the spec's Code
 * Map calls for one written here rather than adding one. Focus lands on the dialog's first
 * focusable control as soon as it opens; Escape and Tab-cycling both stay inside it. The caller
 * owns returning focus to "Submit proposal" once `onCancel` fires (spec AC).
 *
 * Exported (Story FORM-227) so `DeleteConfirmModal` reuses this same shell rather than duplicating
 * its focus-trap/`role="dialog"` behaviour.
 */
export function ModalShell({
  titleId,
  title,
  onCancel,
  children,
}: {
  titleId: string;
  title: string;
  onCancel: () => void;
  children: ReactNode;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Mount-only: each modal is a fresh mount (declaration and feedback are two different
    // components, never the same one re-rendering), so there is no "reopened" case to react to.
    const node = dialogRef.current;
    const first = node?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    (first ?? node)?.focus();
  }, []);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
      return;
    }
    if (event.key !== "Tab") return;
    const node = dialogRef.current;
    if (!node) return;
    const focusables = Array.from(
      node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
    );
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  return (
    <div className="submit-modal__scrim">
      <div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="submit-modal"
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        <h2 id={titleId} className="submit-modal__title">
          {title}
        </h2>
        {children}
      </div>
    </div>
  );
}

/** The declaration modal (Story 3.3): opens only after validation passes. "I agree" moves straight
 * to the feedback modal -- it never itself calls the api, since D1 is only ever set as part of the
 * one submit call the feedback modal's own "Submit proposal" makes. */
export function DeclarationModal({
  onAgree,
  onCancel,
}: {
  onAgree: () => void;
  onCancel: () => void;
}) {
  return (
    <ModalShell
      titleId="declaration-modal-title"
      title={strings.workspace.declarationTitle}
      onCancel={onCancel}
    >
      <p className="submit-modal__declaration-box">
        {strings.workspace.declarationText}
      </p>
      <div className="submit-modal__actions">
        <PillButton variant="cancel" size="modal" onClick={onCancel}>
          {strings.workspace.cancel}
        </PillButton>
        <PillButton variant="primary" size="modal" onClick={onAgree}>
          {strings.workspace.iAgree}
        </PillButton>
      </div>
    </ModalShell>
  );
}

const RATINGS = [1, 2, 3, 4, 5];

/** Five star tiles, one per rating (DESIGN.md "Rating tiles"): a `role="radiogroup"` of `role="radio"`
 * buttons, each labelled by its own number so a screen reader hears "1 star" .. "5 stars" rather
 * than a bare digit. Stars up to the picked value read as filled; only the exact picked tile gets
 * the extra selected treatment (border/tint) that `.rating-tile--selected` carries. */
function RatingTiles({
  value,
  onChange,
}: {
  value: number | null;
  onChange: (rating: number) => void;
}) {
  return (
    <div
      className="rating-tiles"
      role="radiogroup"
      aria-label={strings.workspace.ratingLabel}
    >
      {RATINGS.map((rating) => {
        const selected = value === rating;
        const filled = value !== null && rating <= value;
        return (
          <button
            key={rating}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={strings.workspace.ratingStarLabel(rating)}
            className={
              "rating-tile" + (selected ? " rating-tile--selected" : "")
            }
            onClick={() => onChange(rating)}
          >
            <span
              className={
                "rating-tile__star" +
                (filled ? " rating-tile__star--filled" : "")
              }
              aria-hidden="true"
            >
              ★
            </span>
            <span className="rating-tile__number">{rating}</span>
          </button>
        );
      })}
    </div>
  );
}

/** The feedback modal (Story 3.3): rating 1-5 required, comment optional. "Submit proposal" stays
 * disabled until a rating is picked, with the reason shown beside it (`PillButton`'s own
 * `disabledReason`, EXPERIENCE.md's "hint beside it"). "Cancel" and Escape both leave without
 * submitting. */
export function FeedbackModal({
  rating,
  comment,
  onRatingChange,
  onCommentChange,
  onCancel,
  onSubmit,
  submitting,
}: {
  rating: number | null;
  comment: string;
  onRatingChange: (rating: number) => void;
  onCommentChange: (comment: string) => void;
  onCancel: () => void;
  onSubmit: () => void;
  submitting: boolean;
}) {
  const commentId = useId();
  const disabled = rating === null || submitting;
  const disabledReason =
    rating === null
      ? strings.workspace.feedbackHint
      : strings.workspace.submitInProgressReason;
  return (
    <ModalShell
      titleId="feedback-modal-title"
      title={strings.workspace.feedbackTitle}
      onCancel={onCancel}
    >
      <div className="submit-modal__field">
        <span className="submit-modal__label">
          {strings.workspace.ratingLabel}
        </span>
        <RatingTiles value={rating} onChange={onRatingChange} />
      </div>
      <div className="submit-modal__field">
        <label htmlFor={commentId} className="submit-modal__label">
          {strings.workspace.commentLabel}
        </label>
        <textarea
          id={commentId}
          className="submit-modal__comment"
          value={comment}
          onChange={(event) => onCommentChange(event.target.value)}
        />
      </div>
      <div className="submit-modal__actions">
        <PillButton variant="cancel" size="modal" onClick={onCancel}>
          {strings.workspace.cancel}
        </PillButton>
        <PillButton
          variant="primary"
          size="modal"
          disabled={disabled}
          disabledReason={disabledReason}
          onClick={onSubmit}
        >
          {strings.workspace.submitProposal}
        </PillButton>
      </div>
    </ModalShell>
  );
}
