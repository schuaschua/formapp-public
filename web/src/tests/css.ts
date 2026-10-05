// Test helpers: read files from web/ and pick declarations out of the app's CSS.
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// import.meta.dirname, not new URL(): jsdom replaces the URL class in the test environment.
export const webRoot = resolve(import.meta.dirname, "../..") + "/";
export const repoRoot = resolve(import.meta.dirname, "../../..") + "/";

export function readWebFile(relativePath: string): string {
  return readFileSync(webRoot + relativePath, "utf8").replace(/\r\n/g, "\n");
}

function stripComments(css: string): string {
  return css.replace(/\/\*[\s\S]*?\*\//g, "");
}

/** The declarations of the first rule whose selector list is exactly `selector`. */
export function ruleDeclarations(
  css: string,
  selector: string,
): Map<string, string> {
  const source = stripComments(css);
  const rulePattern = /([^{}]+)\{([^{}]*)\}/g;
  for (const match of source.matchAll(rulePattern)) {
    const selectors = (match[1] ?? "").trim().replace(/\s+/g, " ");
    if (selectors === selector) {
      return parseDeclarations(match[2] ?? "");
    }
  }
  throw new Error(`No CSS rule for ${selector}`);
}

// Prettier wraps long values over several lines; compare them as one line.
function normalise(value: string): string {
  return value
    .trim()
    .replace(/\s+/g, " ")
    .replace(/\( /g, "(")
    .replace(/ \)/g, ")");
}

function parseDeclarations(body: string): Map<string, string> {
  const declarations = new Map<string, string>();
  for (const part of body.split(";")) {
    const colon = part.indexOf(":");
    if (colon > 0) {
      declarations.set(
        part.slice(0, colon).trim(),
        normalise(part.slice(colon + 1)),
      );
    }
  }
  return declarations;
}

/** The comment in tokens.css that ends the block mirroring the DESIGN.md frontmatter. */
export const PROSE_MARKER = "/* From the DESIGN.md prose */";

/** The custom properties above PROSE_MARKER, which mirror the DESIGN.md frontmatter. */
export function mirroredTokens(): Map<string, string> {
  const css = readWebFile("src/styles/tokens.css");
  const end = css.indexOf(PROSE_MARKER);
  if (end < 0) {
    throw new Error(`tokens.css has no ${PROSE_MARKER} marker.`);
  }
  return ruleDeclarations(css.slice(0, end) + "}", ":root");
}

/** Every custom property defined in tokens.css, by name (with the leading --). */
export function tokens(): Map<string, string> {
  return ruleDeclarations(readWebFile("src/styles/tokens.css"), ":root");
}
