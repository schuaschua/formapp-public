import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { strings } from "../strings";
import { SIGN_IN_URL, WelcomePage } from "./WelcomePage";

const FOCUSABLE =
  "a[href], button, input, select, textarea, [tabindex], [contenteditable]";

describe("1.6 Welcome page", () => {
  it("story 1.6: shows the wordmark, the tagline and one Sign in with Microsoft button", () => {
    render(<WelcomePage />);

    expect(
      screen.getByRole("heading", { level: 1, name: strings.welcome.title }),
    ).toBeInTheDocument();
    expect(screen.getByText(strings.welcome.tagline)).toBeInTheDocument();
    expect(strings.welcome.tagline).toBe(
      "Tell the AI about your customer. It fills in the proposal for you to check.",
    );
    const signIn = screen.getByRole("link", { name: "Sign in with Microsoft" });
    expect(signIn).toHaveAttribute("href", SIGN_IN_URL);
    expect(SIGN_IN_URL).toBe(
      "/.auth/login/aad?post_login_redirect_uri=/proposals",
    );
    expect(signIn).toHaveClass("pill-button--primary", "welcome-sign-in");
    expect(signIn.querySelector(".microsoft-glyph")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(signIn.querySelectorAll(".microsoft-glyph > span")).toHaveLength(4);
  });

  it("story 1.6: the button is the only control on the page", () => {
    const { container } = render(<WelcomePage />);

    const focusable = container.querySelectorAll(FOCUSABLE);
    expect(focusable).toHaveLength(1);
    expect(focusable[0]).toHaveTextContent(strings.welcome.signIn);
  });

  it("story 1.6: the floating chips are decoration, hidden from screen readers", () => {
    render(<WelcomePage />);

    const chips = screen.getByTestId("welcome-chips");
    expect(chips).toHaveAttribute("aria-hidden", "true");
    expect(chips.querySelectorAll(FOCUSABLE)).toHaveLength(0);
    expect(chips).toHaveTextContent(strings.welcome.chipProposalName);
    expect(chips).toHaveTextContent(strings.welcome.chipChat);
    expect(
      screen.queryByText(strings.welcome.chipProduct, {
        ignore: "[aria-hidden] *",
      }),
    ).toBeNull();
  });

  it("story 1.6: the photo slot is a clearly labelled placeholder", () => {
    render(<WelcomePage />);

    expect(
      within(screen.getByTestId("welcome-photo")).getByText(
        "Photo placeholder",
      ),
    ).toBeVisible();
  });

  it("story 1.6: sits in one split flat card on the canvas, in the main landmark", () => {
    render(<WelcomePage />);

    const main = screen.getByRole("main");
    const card = within(main).getByRole("region", {
      name: strings.welcome.title,
    });
    expect(card).toHaveClass("glass-card", "welcome-card");
    expect(screen.getByTestId("glow-canvas")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(document.title).toBe("formapp");
  });
});
