import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { readWebFile, ruleDeclarations, tokens } from "../tests/css";
import { GlassCard } from "./GlassCard";

describe("1.4 GlassCard", () => {
  const css = readWebFile("src/components/GlassCard.css");
  const t = tokens();

  it("story 1.4: the card variant renders its content on the flat card surface", () => {
    render(<GlassCard data-testid="card">Drafts</GlassCard>);

    const card = screen.getByTestId("card");
    expect(card).toHaveTextContent("Drafts");
    expect(card).toHaveClass("glass-card");
    expect(card).not.toHaveClass("glass-card--menu");
    expect(card.tagName).toBe("DIV");
  });

  it("story 1.4: the menu variant and landmark elements", () => {
    render(
      <GlassCard variant="menu" as="nav" aria-label="Pages" className="extra">
        Pages
      </GlassCard>,
    );

    const menu = screen.getByRole("navigation", { name: "Pages" });
    expect(menu).toHaveClass("glass-card", "glass-card--menu", "extra");
  });

  it("story 1.4: the card is a flat white card, no border, no blur, one soft shadow", () => {
    const card = ruleDeclarations(css, ".glass-card");
    expect(card.get("background")).toBe("var(--flat-card-background)");
    expect(t.get("--flat-card-background")).toBe("var(--color-card)");
    expect(t.get("--color-card")?.toUpperCase()).toBe(
      t.get("--color-white")?.toUpperCase(),
    );
    expect(card.get("border")).toBe("var(--flat-card-border)");
    expect(t.get("--flat-card-border")).toBe("none");
    expect(card.get("box-shadow")).toBe("var(--flat-card-shadow)");
    // One soft shadow, ink-heading tinted, no glass highlight (Theme E has no glass).
    const shadow = t.get("--flat-card-shadow") ?? "";
    expect(shadow.split(/,(?![^(]*\))/)).toHaveLength(2);
    expect(card.get("backdrop-filter")).toBeUndefined();
  });

  it("story 1.4: the menu variant is the same flat card colour as the base card", () => {
    const menu = ruleDeclarations(css, ".glass-card--menu");
    expect(menu.get("background")).toBe("var(--page-menu-background)");
    expect(t.get("--page-menu-background")).toBe("var(--color-card)");
  });
});
