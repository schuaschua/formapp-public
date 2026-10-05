import type { MouseEvent, ReactNode } from "react";
import { Link } from "react-router";
import { GlassCard } from "../components/GlassCard";
import { strings } from "../strings";
import { paths } from "./paths";
import "./App.css";

const MAIN_ID = "main";

type AppShellProps = {
  /** The breadcrumb area: later stories put "Drafts / name" here. */
  header?: ReactNode;
  /** The right of the header: the signed-in user's avatar and name (Story 1.6). */
  user?: ReactNode;
  children: ReactNode;
};

/** A house outline for the logo tile: the logo links home to the drafts list. */
function HomeIcon() {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d="M3 10.5 12 3l9 7.5" />
      <path d="M5 9.5V20h5v-6h4v6h5V9.5" />
    </svg>
  );
}

/** The canvas backdrop, the header bar and the main area that every page after Welcome renders in. */
export function AppShell({ header, user, children }: AppShellProps) {
  // Focus main directly rather than follow #main, which would put a hash in the router's URL.
  function skipToMain(event: MouseEvent<HTMLAnchorElement>) {
    event.preventDefault();
    document.getElementById(MAIN_ID)?.focus();
  }

  return (
    <>
      <div
        className="glow-canvas"
        aria-hidden="true"
        data-testid="glow-canvas"
      />
      <div className="app-shell">
        <a href={`#${MAIN_ID}`} className="skip-link" onClick={skipToMain}>
          {strings.skipToMain}
        </a>
        <GlassCard as="header" className="app-header">
          <Link to={paths.drafts} className="app-logo">
            <span className="app-logo__tile" aria-hidden="true">
              <HomeIcon />
            </span>
            <span>{strings.appName}</span>
          </Link>
          <div className="app-header__slot">{header}</div>
          {user}
        </GlassCard>
        <main id={MAIN_ID} className="app-main" tabIndex={-1}>
          {children}
        </main>
      </div>
    </>
  );
}
