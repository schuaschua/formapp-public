import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { readWebFile, ruleDeclarations, tokens } from "../tests/css";
import { InfoNote } from "./InfoNote";

describe("4.4 InfoNote", () => {
  const css = readWebFile("src/components/InfoNote.css");
  const t = tokens();

  it("story 4.4: renders its text, with no dots by default", () => {
    render(
      <InfoNote>This proposal is open for editing in another window</InfoNote>,
    );

    expect(
      screen.getByText("This proposal is open for editing in another window"),
    ).toBeInTheDocument();
    expect(document.querySelector(".info-note__dots")).not.toBeInTheDocument();
    expect(document.querySelector(".info-note")).not.toHaveAttribute(
      "aria-live",
    );
  });

  it("story 4.4: dots is announced politely and renders three fading dots", () => {
    render(<InfoNote dots>AI is filling in answers…</InfoNote>);

    expect(document.querySelector(".info-note")).toHaveAttribute(
      "aria-live",
      "polite",
    );
    expect(document.querySelectorAll(".info-note__dots span")).toHaveLength(3);
  });

  it("story 4.4: is the steel-tint pill with steel-blue-dark bold text (DESIGN.md Components)", () => {
    const rule = ruleDeclarations(css, ".info-note");
    expect(rule.get("background")).toBe("var(--info-note-background)");
    expect(rule.get("color")).toBe("var(--info-note-foreground)");
    expect(rule.get("border-radius")).toBe("var(--info-note-radius)");
    expect(t.get("--info-note-background")).toBe(
      "var(--color-steel-tint-note)",
    );
    expect(t.get("--info-note-foreground")).toBe(
      "var(--color-steel-blue-dark)",
    );
    expect(t.get("--info-note-radius")).toBe("var(--rounded-full)");
    expect(rule.get("font")).toBe("var(--font-caption)");
    expect(t.get("--font-caption")).toMatch(/^700 /); // bold
  });
});
