import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
} from "react";
import type { Me } from "../api/client";
import { strings } from "../strings";
import "./AvatarMenu.css";

/** Container Apps sign-out: ends the session, then lands on the Welcome page (Story 1.6). */
export const SIGN_OUT_URL = "/.auth/logout?post_logout_redirect_uri=/";

function initialOf(me: Me): string {
  const [first = ""] = Array.from((me.firstName || me.name).trim());
  return first.toUpperCase();
}

/**
 * The avatar and name on the right of the header (DESIGN.md App header, UX-DR8). Click, Enter or
 * Space opens a small menu holding "Sign out"; Escape closes it and puts focus back on the avatar.
 */
export function AvatarMenu({ me }: { me: Me }) {
  const [open, setOpen] = useState(false);
  const menuId = useId();
  const buttonRef = useRef<HTMLButtonElement>(null);
  const itemRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    if (open) itemRef.current?.focus();
  }, [open]);

  function handleKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape" && open) {
      event.preventDefault();
      setOpen(false);
      buttonRef.current?.focus();
    }
  }

  // Focus leaving the avatar and its menu (Tab away, a click elsewhere) closes the menu.
  function handleBlur(event: FocusEvent<HTMLDivElement>) {
    if (!event.currentTarget.contains(event.relatedTarget)) setOpen(false);
  }

  const firstName = me.firstName || me.name;
  return (
    <div className="avatar-menu" onKeyDown={handleKeyDown} onBlur={handleBlur}>
      <button
        ref={buttonRef}
        type="button"
        className="avatar-menu__button"
        aria-label={strings.account.buttonLabel(firstName)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? menuId : undefined}
        // Keep focus where it is on pointer-down: in Safari a click doesn't focus the button, so
        // the menu item's blur would close the menu and the click reopen it. The click alone toggles.
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => setOpen((value) => !value)}
      >
        <span className="avatar" aria-hidden="true">
          {initialOf(me)}
        </span>
        <span className="avatar-menu__name">{firstName}</span>
      </button>
      {open && (
        <div
          id={menuId}
          role="menu"
          aria-label={strings.account.menuLabel}
          className="avatar-menu__list"
        >
          <a
            ref={itemRef}
            role="menuitem"
            href={SIGN_OUT_URL}
            className="avatar-menu__item"
          >
            {strings.account.signOut}
          </a>
        </div>
      )}
    </div>
  );
}
