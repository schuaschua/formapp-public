import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import { PREVIEW_SECURITY_HEADERS } from "../../security-headers";
import { repoRoot } from "./css";

// Story 1.4: `vite preview` sends the api's security headers, so the Playwright check only proves
// anything while the two sets are the same.
const MIDDLEWARE = "api/adapters/rest/middleware.py";

function between(source: string, start: string, end: string): string {
  const from = source.indexOf(start);
  if (from < 0)
    throw new Error(
      `${MIDDLEWARE}: marker ${JSON.stringify(start)} not found.`,
    );
  const to = source.indexOf(end, from + start.length);
  if (to < 0)
    throw new Error(`${MIDDLEWARE}: no ${JSON.stringify(end)} after ${start}.`);
  return source.slice(from + start.length, to);
}

function quoted(block: string): string[] {
  return [...block.matchAll(/"([^"]+)"/g)].map((m) => m[1] ?? "");
}

function bytesHeader(source: string, name: string): string {
  const match = new RegExp(`\\(b"${name}", b"([^"]+)"\\)`).exec(source);
  if (!match) throw new Error(`${MIDDLEWARE}: header ${name} not found.`);
  return match[1] ?? "";
}

function apiHeaders(): Record<string, string> {
  const source = readFileSync(repoRoot + MIDDLEWARE, "utf8").replace(
    /\r\n/g,
    "\n",
  );
  const csp = quoted(between(source, "_CSP_DIRECTIVES = (", "\n)"));
  const features = quoted(
    between(source, "for feature in (", "\n            )"),
  );
  return {
    "Content-Security-Policy": csp.join("; "),
    "Permissions-Policy": [
      ...features.map((f) => `${f}=()`),
      "microphone=(self)",
    ].join(", "),
    "X-Content-Type-Options": bytesHeader(source, "x-content-type-options"),
    "Referrer-Policy": bytesHeader(source, "referrer-policy"),
  };
}

describe("1.4 security headers", () => {
  it("story 1.4: vite preview sends the same security headers as the api", () => {
    const api = apiHeaders();

    expect(api["Content-Security-Policy"]).toContain("script-src 'self'");
    expect(api["Content-Security-Policy"]).toContain("frame-ancestors 'none'");
    expect(api["Permissions-Policy"]).toContain("camera=()");
    // Story 6.2: the mic is allowed to this origin only; a bare microphone=() blocks it.
    expect(api["Permissions-Policy"]).toContain("microphone=(self)");
    expect(api["Permissions-Policy"]).not.toContain("microphone=()");
    expect(PREVIEW_SECURITY_HEADERS).toEqual(api);
  });

  it("story 1.4: a missing marker is a clear error", () => {
    expect(() => between("nothing here", "_CSP_DIRECTIVES = (", ")")).toThrow(
      /marker "_CSP_DIRECTIVES = \(" not found/,
    );
  });
});
