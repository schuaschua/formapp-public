import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { parse } from "yaml";
import {
  mirroredTokens,
  readWebFile,
  repoRoot,
  ruleDeclarations,
  tokens,
} from "./css";

// Story 1.4 (UX-DR1, UX-DR2, UX-DR5, NFR10): every DESIGN.md token is a CSS custom property in
// tokens.css, with the same value.
const DESIGN_MD =
  "_bmad-output/planning-artifacts/ux-designs/ux-formapp-2026-09-25/DESIGN.md";

type Typography = {
  fontFamily: string;
  fontSize: string;
  fontWeight: string;
  lineHeight?: string;
  letterSpacing?: string;
};

type DesignFrontmatter = {
  colors: Record<string, string>;
  typography: Record<string, Typography>;
  rounded: Record<string, string>;
  spacing: Record<string, string>;
  components: Record<string, Record<string, string>>;
};

function design(): DesignFrontmatter {
  const text = readFileSync(repoRoot + DESIGN_MD, "utf8").replace(
    /\r\n/g,
    "\n",
  );
  const match = /^---\n([\s\S]*?)\n---(?:\n|$)/.exec(text);
  if (!match) {
    throw new Error(`${DESIGN_MD} has no YAML frontmatter between --- lines.`);
  }
  const spec = parse(match[1] ?? "") as Partial<DesignFrontmatter> | null;
  for (const group of [
    "colors",
    "typography",
    "rounded",
    "spacing",
    "components",
  ] as const) {
    if (!spec?.[group]) {
      throw new Error(`${DESIGN_MD} frontmatter has no ${group} group.`);
    }
  }
  return spec as DesignFrontmatter;
}

/** Every custom property the DESIGN.md frontmatter implies, by name. */
function expectedNames(spec: DesignFrontmatter): Set<string> {
  const names = new Set<string>();
  for (const name of Object.keys(spec.colors)) names.add(`--color-${name}`);
  for (const name of Object.keys(spec.typography)) {
    names.add(`--font-${name}`);
    names.add(`--font-${name}-size`);
    names.add(`--font-${name}-letter-spacing`);
  }
  for (const name of Object.keys(spec.rounded)) names.add(`--rounded-${name}`);
  for (const name of Object.keys(spec.spacing)) names.add(`--spacing-${name}`);
  for (const [component, props] of Object.entries(spec.components)) {
    for (const prop of Object.keys(props)) names.add(`--${component}-${prop}`);
  }
  return names;
}

const GROUP_PREFIX: Record<string, string> = {
  colors: "color",
  rounded: "rounded",
  spacing: "spacing",
  typography: "font",
};

/** `1px solid {colors.border-field}` -> `1px solid var(--color-border-field)`. */
function asCss(value: string): string {
  return value.replace(
    /\{(colors|rounded|spacing|typography)\.([\w-]+)\}/g,
    (_, group: string, name: string) => `var(--${GROUP_PREFIX[group]}-${name})`,
  );
}

const px = (value: string | undefined) => Number.parseFloat(value ?? "NaN");

describe("1.4 design tokens", () => {
  const spec = design();
  const css = tokens();

  it("story 1.4: the mirrored block of tokens.css has exactly the DESIGN.md tokens", () => {
    const expected = expectedNames(spec);
    const actual = new Set(mirroredTokens().keys());

    const missing = [...expected].filter((name) => !actual.has(name));
    const extra = [...actual].filter((name) => !expected.has(name));
    expect(missing, "in DESIGN.md but not tokens.css").toEqual([]);
    expect(
      extra,
      "in tokens.css but not DESIGN.md (move prose values below the marker)",
    ).toEqual([]);
  });

  it("story 1.4: every DESIGN.md colour is a custom property with the same value", () => {
    for (const [name, value] of Object.entries(spec.colors)) {
      expect(css.get(`--color-${name}`)?.toUpperCase(), name).toBe(
        value.toUpperCase(),
      );
    }
  });

  it("story 1.4: every rounded and spacing token is a custom property with the same value", () => {
    for (const [name, value] of Object.entries(spec.rounded)) {
      expect(css.get(`--rounded-${name}`), name).toBe(value);
    }
    for (const [name, value] of Object.entries(spec.spacing)) {
      expect(css.get(`--spacing-${name}`), name).toBe(value);
    }
  });

  it("story 1.4: every typography token is a font shorthand in the system stack", () => {
    for (const [name, t] of Object.entries(spec.typography)) {
      const family =
        t.fontFamily === "ui-monospace"
          ? "var(--font-family-mono)"
          : "var(--font-family-system)";
      const lineHeight = t.lineHeight ? `/${t.lineHeight}` : "";
      expect(css.get(`--font-${name}`), name).toBe(
        `${t.fontWeight} ${t.fontSize}${lineHeight} ${family}`,
      );
      expect(css.get(`--font-${name}-size`), name).toBe(t.fontSize);
      expect(css.get(`--font-${name}-letter-spacing`), name).toBe(
        t.letterSpacing ?? "normal",
      );
    }
  });

  it("story 1.4: every component token is a custom property built from the tokens", () => {
    for (const [component, props] of Object.entries(spec.components)) {
      for (const [prop, value] of Object.entries(props)) {
        expect(css.get(`--${component}-${prop}`), `${component}.${prop}`).toBe(
          asCss(String(value)),
        );
      }
    }
  });

  it("story 1.4: body, answers, questions and chat are at least 16px, labels at least 14px", () => {
    for (const [name, t] of Object.entries(spec.typography)) {
      expect(px(t.fontSize), name).toBeGreaterThanOrEqual(14);
    }
    for (const name of ["body", "answer", "question", "chat"]) {
      expect(px(css.get(`--font-${name}-size`)), name).toBeGreaterThanOrEqual(
        16,
      );
    }
    for (const [name, value] of css) {
      if (name.endsWith("-size") && name.startsWith("--font-")) {
        expect(px(value), name).toBeGreaterThanOrEqual(14);
      }
    }
  });

  it("story 1.4: text uses the system font stack and no web fonts are requested", () => {
    expect(css.get("--font-family-system")).toBe(
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
    );
    const html = ruleDeclarations(readWebFile("src/styles/global.css"), "html");
    expect(html.get("font")).toBe("var(--font-body)");

    const sources = [
      readWebFile("index.html"),
      readWebFile("src/styles/global.css"),
      readWebFile("src/styles/tokens.css"),
    ].join("\n");
    expect(sources).not.toMatch(
      /@font-face|fonts\.googleapis|fonts\.gstatic|\.woff2?\b/,
    );
  });

  it("story 1.4: dates use tabular numerals and untitled names use monospace", () => {
    const global = readWebFile("src/styles/global.css");
    expect(
      ruleDeclarations(global, ".text-date").get("font-variant-numeric"),
    ).toBe("tabular-nums");
    expect(ruleDeclarations(global, ".text-untitled").get("font")).toBe(
      "var(--font-untitled-name)",
    );
    expect(css.get("--font-untitled-name")).toContain(
      "var(--font-family-mono)",
    );
  });

  it("story 1.4: every focusable element gets the 2px forest-accent ring with a 2px offset", () => {
    const focus = ruleDeclarations(
      readWebFile("src/styles/global.css"),
      ":focus-visible",
    );
    expect(focus.get("outline")).toBe(
      "var(--focus-ring-width) solid var(--focus-ring-color)",
    );
    expect(focus.get("outline-offset")).toBe("var(--focus-ring-offset)");
    expect(css.get("--focus-ring-width")).toBe("2px");
    expect(css.get("--focus-ring-offset")).toBe("2px");
    expect(css.get("--focus-ring-color")).toBe("var(--color-forest-accent)");
  });

  // Theme E "Forest" retires Theme D's blurred glow canvas (DESIGN.md Elevation & Depth): the
  // canvas is a flat colour and the backdrop layer paints nothing.
  it("story 1.4: the canvas is flat, with no glow gradient or blur behind it", () => {
    for (const name of css.keys()) {
      expect(name, name).not.toMatch(/^--glow-canvas-/);
    }

    const global = readWebFile("src/styles/global.css");
    expect(ruleDeclarations(global, "html").get("background")).toBe(
      "var(--color-canvas)",
    );
    expect(ruleDeclarations(global, "body").get("background")).toBe(
      "var(--color-canvas)",
    );
    const layer = ruleDeclarations(global, ".glow-canvas");
    expect(layer.get("position")).toBe("fixed");
    expect(layer.get("pointer-events")).toBe("none");
    expect(global).not.toMatch(/\.glow-canvas::before/);
  });
});
