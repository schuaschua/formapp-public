import { useEffect } from "react";
import "./Toast.css";

/** How long the success toast stays up before it dismisses itself (Story 3.3): long enough to
 * read, short enough not to linger over the Submitted list she's landed on. */
const TOAST_DURATION_MS = 5000;

/**
 * The success toast after a submit (Story 3.3, DESIGN.md Components "Toast (success)"): shown on
 * My proposals › Submitted once the app navigates there. `role="status"` (EXPERIENCE.md "Live
 * regions"), so it's announced without stealing focus, and it dismisses itself -- `onDismiss` lets
 * the caller drop it from state rather than this component owning any of that state itself.
 */
export function Toast({
  message,
  onDismiss,
}: {
  message: string;
  onDismiss: () => void;
}) {
  useEffect(() => {
    const timer = window.setTimeout(onDismiss, TOAST_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [onDismiss]);

  return (
    <div className="toast-success" role="status">
      <span className="toast-success__icon" aria-hidden="true">
        ✓
      </span>
      <span>{message}</span>
    </div>
  );
}
