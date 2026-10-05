import { useEffect } from "react";
import { GlassCard } from "../components/GlassCard";
import { MicrosoftGlyph } from "../components/MicrosoftGlyph";
import { strings } from "../strings";
import "../components/PillButton.css";
import "./WelcomePage.css";

/** Container Apps sign-in with Entra, returning to My proposals › Drafts (Story 1.6, AD-4). */
export const SIGN_IN_URL =
  "/.auth/login/aad?post_login_redirect_uri=/proposals";

/**
 * The signed-out Welcome page (DESIGN.md Welcome card, UX-DR6): one split flat card on the canvas
 * with the wordmark, the tagline and one "Sign in with Microsoft" button, the only control on the
 * page. The photo slot holds a labelled placeholder until the real photo lands (deferred-work.md);
 * its floating chips are decoration, hidden from screen readers and never focusable.
 */
export function WelcomePage() {
  useEffect(() => {
    document.title = strings.welcome.documentTitle;
  }, []);

  return (
    <>
      <div
        className="glow-canvas"
        aria-hidden="true"
        data-testid="glow-canvas"
      />
      <main className="welcome">
        <GlassCard
          as="section"
          className="welcome-card"
          aria-labelledby="welcome-title"
        >
          <div className="welcome-card__panel">
            <div className="welcome-card__hero">
              <h1 id="welcome-title" className="welcome-wordmark">
                <span className="welcome-wordmark__tile" aria-hidden="true">
                  {strings.logoInitial}
                </span>
                <span>{strings.welcome.title}</span>
              </h1>
              <p className="welcome-card__tagline">{strings.welcome.tagline}</p>
              <a
                href={SIGN_IN_URL}
                className="pill-button pill-button--primary welcome-sign-in"
              >
                <MicrosoftGlyph />
                {strings.welcome.signIn}
              </a>
            </div>
          </div>
          <div className="welcome-photo" data-testid="welcome-photo">
            <p className="welcome-photo__label">
              {strings.welcome.photoPlaceholder}
            </p>
            <div
              className="welcome-chips"
              aria-hidden="true"
              data-testid="welcome-chips"
            >
              <GlassCard className="welcome-chip welcome-chip--proposal">
                <span className="welcome-chip__label">
                  {strings.welcome.chipProposalLabel}
                </span>
                <span className="welcome-chip__name">
                  {strings.welcome.chipProposalName}
                </span>
                <span className="welcome-chip__row">
                  <span className="welcome-chip__ai">
                    {strings.welcome.chipFilledByChat}
                  </span>
                  {strings.welcome.chipProduct}
                </span>
                <span className="welcome-chip__bar" />
              </GlassCard>
              <GlassCard className="welcome-chip welcome-chip--chat">
                <span className="welcome-chip__bubble">
                  {strings.welcome.chipChat}
                </span>
              </GlassCard>
            </div>
          </div>
        </GlassCard>
      </main>
    </>
  );
}
