import {
  useId,
  type ComponentPropsWithoutRef,
  type MouseEvent,
  type ReactNode,
} from "react";
import "./PillButton.css";

type BaseProps = {
  variant: "primary" | "secondary" | "cancel" | "destructive";
  /** `modal` is the 52px button used in modals; `default` is 40px. */
  size?: "default" | "modal";
  children: ReactNode;
} & Omit<
  ComponentPropsWithoutRef<"button">,
  "disabled" | "children" | "className" | "style"
>;

// A disabled button must say why, next to it (EXPERIENCE.md: "Disabled always explained"), so the
// explanation is required by the type whenever `disabled` may be true.
type EnabledProps = { disabled?: false; disabledReason?: string };
type MaybeDisabledProps = { disabled: boolean; disabledReason: string };

export type PillButtonProps = BaseProps & (EnabledProps | MaybeDisabledProps);

/** Pill button in the primary, secondary, cancel or destructive style (DESIGN.md Components,
 * UX-DR4). ``destructive`` is a new solid-red variant added by Story FORM-227 for the delete-draft
 * confirmation only -- DESIGN.md's own Do/Don't table doesn't have this variant yet (it currently
 * reserves red for the system-failure banner); flagged as a design-system gap in the PR, to be
 * formalized later via `bmad-ux`, the same deferral pattern AD-17 already used for Story 4.9. */
export function PillButton({
  variant,
  size = "default",
  type = "button",
  disabled = false,
  disabledReason,
  onClick,
  children,
  ...rest
}: PillButtonProps) {
  const reasonId = useId();
  const reason = disabledReason?.trim() ?? "";
  if (disabled && !reason && import.meta.env.DEV) {
    throw new Error(
      "PillButton: a disabled button needs a non-empty disabledReason.",
    );
  }
  const showReason = disabled && reason !== "";
  const describedBy =
    [rest["aria-describedby"], showReason && reasonId]
      .filter(Boolean)
      .join(" ") || undefined;
  const classes = [
    "pill-button",
    `pill-button--${variant}`,
    size === "modal" && "pill-button--modal",
  ]
    .filter(Boolean)
    .join(" ");

  // aria-disabled instead of the native attribute: the button stays focusable, so keyboard and
  // screen-reader users reach it and hear why it is disabled. Enter and Space fire click, so
  // suppressing click covers every activation (and stops a submit button submitting).
  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    if (disabled) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  }

  // The same structure either way, so toggling disabled never remounts the button.
  return (
    <span className="pill-button-group">
      <button
        {...rest}
        type={type}
        className={classes}
        aria-disabled={disabled ? "true" : undefined}
        aria-describedby={describedBy}
        onClick={handleClick}
      >
        {children}
      </button>
      {showReason && (
        <span id={reasonId} className="pill-button-reason">
          {reason}
        </span>
      )}
    </span>
  );
}
