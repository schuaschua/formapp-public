import type React from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { readWebFile, ruleDeclarations, tokens } from "../tests/css";
import { PillButton } from "./PillButton";

describe("1.4 PillButton", () => {
  const css = readWebFile("src/components/PillButton.css");
  const t = tokens();

  it.each(["primary", "secondary", "cancel"] as const)(
    "story 1.4: renders the %s style and handles clicks",
    async (variant) => {
      const onClick = vi.fn();
      render(
        <PillButton variant={variant} onClick={onClick}>
          Submit proposal
        </PillButton>,
      );

      const button = screen.getByRole("button", { name: "Submit proposal" });
      expect(button).toHaveClass("pill-button", `pill-button--${variant}`);
      expect(button).toHaveAttribute("type", "button");
      await userEvent.click(button);
      expect(onClick).toHaveBeenCalledOnce();
    },
  );

  it("story 1.4: buttons are 40px high, 52px in the modal size", () => {
    render(
      <PillButton variant="primary" size="modal">
        I agree
      </PillButton>,
    );
    expect(screen.getByRole("button", { name: "I agree" })).toHaveClass(
      "pill-button--modal",
    );

    expect(ruleDeclarations(css, ".pill-button").get("min-height")).toBe(
      "var(--button-primary-height)",
    );
    expect(t.get("--button-primary-height")).toBe(
      "var(--spacing-button-height)",
    );
    expect(t.get("--spacing-button-height")).toBe("40px");
    expect(ruleDeclarations(css, ".pill-button--modal").get("min-height")).toBe(
      "var(--spacing-modal-button-height)",
    );
    expect(t.get("--spacing-modal-button-height")).toBe("52px");
  });

  it("story 1.4: primary is the forest gradient with the forest lift", () => {
    const primary = ruleDeclarations(css, ".pill-button--primary");
    expect(primary.get("background")).toBe("var(--button-primary-background)");
    expect(t.get("--button-primary-background")).toBe(
      "linear-gradient(145deg, var(--color-forest), var(--color-forest-dark))",
    );
    expect(primary.get("box-shadow")).toBe("var(--forest-lift-shadow)");
    expect(t.get("--forest-lift-shadow")).toMatch(/^0 6px 14px /);
  });

  it("story 1.4: secondary has a forest outline and cancel a grey-mid outline", () => {
    expect(ruleDeclarations(css, ".pill-button--secondary").get("border")).toBe(
      "var(--button-secondary-border)",
    );
    expect(t.get("--button-secondary-border")).toBe(
      "1.5px solid var(--color-forest)",
    );
    expect(ruleDeclarations(css, ".pill-button--cancel").get("border")).toBe(
      "var(--button-cancel-border)",
    );
    expect(t.get("--button-cancel-border")).toBe(
      "1.5px solid var(--color-grey-mid)",
    );
  });

  it("story 1.4: disabled is 42% opacity with no shadow and shows its explanation", async () => {
    const onClick = vi.fn();
    render(
      <PillButton
        variant="primary"
        disabled
        disabledReason="A rating is required to submit."
        onClick={onClick}
      >
        Submit proposal
      </PillButton>,
    );

    const button = screen.getByRole("button", { name: "Submit proposal" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toHaveAttribute("disabled");
    expect(button).toHaveAccessibleDescription(
      "A rating is required to submit.",
    );
    expect(screen.getByText("A rating is required to submit.")).toBeVisible();
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();

    const disabled = ruleDeclarations(
      css,
      '.pill-button[aria-disabled="true"]',
    );
    expect(disabled.get("opacity")).toBe("var(--button-disabled-opacity)");
    expect(t.get("--button-disabled-opacity")).toBe("0.42");
    expect(disabled.get("box-shadow")).toBe("var(--button-disabled-shadow)");
    expect(t.get("--button-disabled-shadow")).toBe("none");
  });

  it("story 1.4: a disabled button stays focusable but Enter and Space do nothing", async () => {
    const onClick = vi.fn();
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <PillButton
          variant="primary"
          type="submit"
          disabled
          disabledReason="Wait 6s"
          onClick={onClick}
        >
          Send
        </PillButton>
      </form>,
    );

    await userEvent.tab();
    const button = screen.getByRole("button", { name: "Send" });
    expect(button).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("story 1.4: toggling disabled keeps the same button and its focus", async () => {
    const { rerender } = render(
      <PillButton variant="primary" disabled={false} disabledReason="Wait 6s">
        Send
      </PillButton>,
    );
    const button = screen.getByRole("button", { name: "Send" });
    button.focus();

    rerender(
      <PillButton variant="primary" disabled={true} disabledReason="Wait 6s">
        Send
      </PillButton>,
    );
    expect(screen.getByRole("button", { name: "Send" })).toBe(button);
    expect(button).toHaveFocus();
    expect(screen.getByText("Wait 6s")).toBeVisible();

    rerender(
      <PillButton variant="primary" disabled={false} disabledReason="Wait 6s">
        Send
      </PillButton>,
    );
    expect(screen.getByRole("button", { name: "Send" })).toBe(button);
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(screen.queryByText("Wait 6s")).not.toBeInTheDocument();
  });

  it("story 1.4: a disabled button without an explanation is a type error", () => {
    const maybe: boolean = document.hidden;
    // tsc --noEmit fails if the missing explanation stops being an error.
    const literal = (
      // @ts-expect-error disabledReason is required when disabled is true
      <PillButton variant="primary" disabled>
        Submit proposal
      </PillButton>
    );
    const boolean = (
      // @ts-expect-error disabledReason is required when disabled may be true
      <PillButton variant="primary" disabled={maybe}>
        Submit proposal
      </PillButton>
    );
    // A boolean with a reason compiles.
    const withReason = (
      <PillButton variant="primary" disabled={maybe} disabledReason="Wait 6s">
        Submit proposal
      </PillButton>
    );
    expect([literal, boolean, withReason]).toHaveLength(3);
  });

  it.each(["", "   "])(
    "story 1.4: an empty explanation %j is an error in development",
    (reason) => {
      vi.spyOn(console, "error").mockImplementation(() => undefined);
      expect(() =>
        render(
          <PillButton variant="primary" disabled disabledReason={reason}>
            Send
          </PillButton>,
        ),
      ).toThrow(/non-empty disabledReason/);
    },
  );

  it("story 1.4: a disabled button joins its explanation to a caller's description", () => {
    render(
      <>
        <span id="hint">Opens the declaration</span>
        <PillButton
          variant="primary"
          aria-describedby="hint"
          disabled
          disabledReason="A rating is required to submit."
        >
          Submit proposal
        </PillButton>
      </>,
    );
    expect(
      screen.getByRole("button", { name: "Submit proposal" }),
    ).toHaveAccessibleDescription(
      "Opens the declaration A rating is required to submit.",
    );
  });

  it("story 1.4: an enabled button keeps a caller's description", () => {
    render(
      <>
        <span id="hint">Opens the declaration</span>
        <PillButton variant="secondary" aria-describedby="hint">
          Retry
        </PillButton>
      </>,
    );
    expect(
      screen.getByRole("button", { name: "Retry" }),
    ).toHaveAccessibleDescription("Opens the declaration");
  });
});
