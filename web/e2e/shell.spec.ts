import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { CONTENT_SECURITY_POLICY } from "../security-headers";

// Story 1.4 in Chromium against the production build: axe, the focus ring and targets, the flat
// canvas, no web fonts, no CSP violations, and 1280x800 at 100% and 200% zoom. GET /api/me is
// mocked: signed in everywhere, except signed out on the Welcome page (/). /proposals/42 (Story
// 1.9: a real workspace, not a placeholder) also needs its draft and schema mocked -- the id
// itself is never validated by anything in this browser-only test. Story 1.10 gave this job a real
// proxied api behind `vite preview` (for journey1.spec.ts); the Drafts/Submitted list call is
// mocked here too so these otherwise-self-contained tests never reach it unauthenticated (which
// would 401 and, via the new 401 hook, sign the mocked-in agent straight back out).
const ROUTES = ["/", "/proposals", "/proposals/submitted", "/proposals/42"];

// A synthetic signed-in agent (security.md rule 1).
const ALICE = { name: "Alice Synthetic", first_name: "Alice" };

// A minimal, valid draft + pinned schema for /proposals/42 (Story 1.9), covering one question on
// each of pages 1 and 5 so the page menu shows a real "N of 5 pages done" and page 1 renders a row.
const WORKSPACE_DRAFT = {
  id: "42",
  status: "draft",
  schema_version: 1,
  revision: 0,
  lock: { holder: "you", expires_at: null },
  active: ["N1"],
  answers: { N1: "life" },
  provenance: {},
  quote: null,
  display_name: "Ally_Macbeal_Proposal_001",
};
const WORKSPACE_SCHEMA = {
  $id: "urn:formapp:form-schema:v1",
  properties: {
    N1: {
      title: "What type of product are you looking for?",
      type: "string",
      enum: ["life", "life_health", "health"],
      "x-labels": {
        life: "Life",
        life_health: "Life + Health",
        health: "Health",
      },
      "x-page": 1,
      "x-fill": "ask",
    },
  },
  required: ["N1"],
  allOf: [],
};

/** Answer GET /api/me as signed in (200) or signed out (401); the latest call wins. */
async function mockMe(page: Page, signedIn: boolean) {
  await page.route("**/api/me", (route) =>
    route.fulfill(
      signedIn
        ? { status: 200, json: ALICE }
        : {
            status: 401,
            json: {
              errors: [
                {
                  field: "principal",
                  code: "required",
                  message: "Sign in with Microsoft to continue.",
                },
              ],
            },
          },
    ),
  );
}

/** Answer /proposals/42's draft, schema and edit-lock fetches (Story 1.9; Story 4.4's lock, called
 * on mount, needs its own mock too -- otherwise it falls through to the real proxied api
 * unauthenticated, 401s, and that spuriously signs the mocked-in agent back out, same as the
 * Drafts/Submitted list call `mockProposalsList` guards against below). */
async function mockWorkspace(page: Page) {
  await page.route("**/api/proposals/42", (route) =>
    route.fulfill({ status: 200, json: WORKSPACE_DRAFT }),
  );
  await page.route("**/api/proposals/42/schema", (route) =>
    route.fulfill({ status: 200, json: WORKSPACE_SCHEMA }),
  );
  // Story 2.3's product list fetch: unmocked, it reaches the real proxied api unauthenticated,
  // and the 401 signs the shell out mid-test.
  await page.route(/\/api\/products(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, json: [] }),
  );
  await page.route("**/api/proposals/42/lock", (route) =>
    route.fulfill({ status: 200, json: { holder: "you", expires_at: null } }),
  );
  // Story 4.5: the chat panel's own history fetch, called on mount, same reasoning as the lock
  // mock just above.
  await page.route("**/api/proposals/42/chat", (route) =>
    route.fulfill({ status: 200, json: { messages: [] } }),
  );
}

/** Answer the Drafts/Submitted list fetch (`GET /api/proposals?status=...`) with an empty list --
 * this file never checks list contents, only that the shell around it renders (Story 1.10: without
 * this, the call falls through to the real proxied api unauthenticated and 401s). */
async function mockProposalsList(page: Page) {
  await page.route(/\/api\/proposals(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, json: [] }),
  );
}

declare global {
  interface Window {
    cspViolations: string[];
    focusSeen: WeakSet<Element>;
  }
}

test.beforeEach(async ({ page }) => {
  await mockMe(page, true);
  await mockWorkspace(page);
  await mockProposalsList(page);
  await page.addInitScript(() => {
    window.cspViolations = [];
    document.addEventListener("securitypolicyviolation", (event) => {
      window.cspViolations.push(
        `${event.violatedDirective} ${event.blockedURI}`,
      );
    });
  });
});

async function open(page: Page, route: string) {
  await mockMe(page, route !== "/");
  const response = await page.goto(route);
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  return response;
}

/** A token's computed value for a CSS property, read through a probe element. */
async function computedToken(page: Page, property: string, token: string) {
  return page.evaluate(
    ([prop, name]) => {
      const probe = document.createElement("div");
      probe.style.setProperty(prop, `var(${name})`);
      document.body.append(probe);
      const value = getComputedStyle(probe).getPropertyValue(prop);
      probe.remove();
      return value;
    },
    [property, token] as const,
  );
}

/** Horizontal overflow and anything in the shell pushed or cut off at the sides. */
async function layoutProblems(page: Page) {
  return page.evaluate(() => {
    const problems: string[] = [];
    const width = document.documentElement.clientWidth;
    if (document.documentElement.scrollWidth > width) {
      problems.push(
        `page scrolls sideways (${document.documentElement.scrollWidth} > ${width})`,
      );
    }
    const shell = document.querySelectorAll(
      ".app-shell, .app-shell header, .app-shell main, .app-shell h1, .app-shell p, .app-shell a, .glass-card",
    );
    for (const element of shell) {
      const box = element.getBoundingClientRect();
      const name = `${element.tagName.toLowerCase()}.${element.className}`;
      if (box.left < 0 || box.right > width + 0.5) {
        problems.push(
          `${name} outside the viewport (${box.left}..${box.right} of ${width})`,
        );
      }
      const style = getComputedStyle(element);
      // A `.visually-hidden` element (Story 1.9's own workspace h1, and any future one) clips its
      // content by design, for screen readers only -- that is the technique, not a layout bug.
      const clips =
        !element.classList.contains("visually-hidden") &&
        (style.overflowX !== "visible" || style.overflowY !== "visible");
      if (
        clips &&
        (element.scrollWidth > element.clientWidth + 1 ||
          element.scrollHeight > element.clientHeight + 1)
      ) {
        problems.push(`${name} cuts off its content`);
      }
    }
    return problems;
  });
}

test.describe("1.4 app shell", () => {
  for (const route of ROUTES) {
    test(`story 1.4: ${route} has no axe violations`, async ({ page }) => {
      await open(page, route);

      const results = await new AxeBuilder({ page })
        .withTags([
          "wcag2a",
          "wcag2aa",
          "wcag21a",
          "wcag21aa",
          "wcag22aa",
          "best-practice",
        ])
        .analyze();
      const violations = results.violations.map(
        (v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`,
      );
      expect(violations, `axe on ${route}`).toEqual([]);
    });

    test(`story 1.4: ${route} sits on the flat canvas with system fonts and no CSP violations`, async ({
      page,
    }) => {
      const fontRequests: string[] = [];
      page.on("request", (request) => {
        if (request.resourceType() === "font") fontRequests.push(request.url());
      });
      const response = await open(page, route);
      // The same policy as the api (src/tests/security-headers.test.ts), so "no violations" below
      // can't pass because no policy was sent.
      expect(
        response?.headers()["content-security-policy"],
        `CSP header on ${route}`,
      ).toBe(CONTENT_SECURITY_POLICY);

      // Theme E "Forest" retires Theme D's blurred glow canvas: `.glow-canvas` is kept as an inert,
      // full-viewport backdrop layer, but it no longer paints a blur or any gradients.
      const canvas = await page.evaluate(() => {
        const canvas = document.querySelector(".glow-canvas");
        if (!canvas) return null;
        const layer = getComputedStyle(canvas, "::before");
        return {
          position: getComputedStyle(canvas).position,
          filter: layer.filter,
          gradients:
            layer.backgroundImage.match(/radial-gradient\(/g)?.length ?? 0,
          body: getComputedStyle(document.body).backgroundColor,
          font: getComputedStyle(document.body).fontFamily,
        };
      });
      expect(canvas, `canvas backdrop on ${route}`).not.toBeNull();
      expect(canvas?.position).toBe("fixed");
      expect(canvas?.filter).toBe("none");
      expect(canvas?.gradients).toBe(0);
      expect(canvas?.body).toBe(
        await computedToken(page, "background-color", "--color-canvas"),
      );
      expect(canvas?.font).toContain("-apple-system");
      expect(fontRequests, `font requests on ${route}`).toEqual([]);
      expect(
        await page.evaluate(() => window.cspViolations),
        `CSP on ${route}`,
      ).toEqual([]);
    });

    test(`story 1.4: ${route} shows the focus ring on every focusable element, with 40px targets`, async ({
      page,
    }) => {
      await open(page, route);
      const ring = await computedToken(
        page,
        "outline-color",
        "--focus-ring-color",
      );

      await page.evaluate(() => {
        window.focusSeen = new WeakSet();
      });
      let count = 0;
      for (let step = 0; step < 30; step += 1) {
        await page.keyboard.press("Tab");
        const focused = await page.evaluate(() => {
          const element = document.activeElement;
          if (!element || element === document.body) return null;
          // Identity, not markup: a WeakSet notices when Tab comes back round to the same element.
          if (window.focusSeen.has(element)) return null;
          window.focusSeen.add(element);
          const style = getComputedStyle(element);
          const box = element.getBoundingClientRect();
          return {
            name: `${element.tagName.toLowerCase()} "${element.textContent?.trim() ?? ""}"`,
            outline: `${style.outlineStyle} ${style.outlineWidth}`,
            color: style.outlineColor,
            offset: style.outlineOffset,
            width: box.width,
            height: box.height,
          };
        });
        if (!focused) break;
        count += 1;
        expect(focused.outline, focused.name).toBe("solid 2px");
        expect(focused.color, focused.name).toBe(ring);
        expect(focused.offset, focused.name).toBe("2px");
        expect(focused.width, focused.name).toBeGreaterThanOrEqual(40);
        expect(focused.height, focused.name).toBeGreaterThanOrEqual(40);
      }
      expect(count, `focusable elements on ${route}`).toBeGreaterThan(0);
    });

    test(`story 1.4: ${route} fits 1280x800 at 100%`, async ({ page }) => {
      await open(page, route);
      expect(
        await layoutProblems(page),
        `1280x800 at 100% on ${route}`,
      ).toEqual([]);
    });
  }

  test.describe("at 200% zoom", () => {
    // 200% browser zoom on a 1280x800 window lays the page out in 640x400 CSS pixels at 2x density.
    test.use({ viewport: { width: 640, height: 400 }, deviceScaleFactor: 2 });

    for (const route of ROUTES) {
      test(`story 1.4: ${route} has nothing cut off and no sideways scroll`, async ({
        page,
      }) => {
        await open(page, route);
        expect(
          await layoutProblems(page),
          `1280x800 at 200% on ${route}`,
        ).toEqual([]);
      });
    }
  });

  for (const [route, title] of [
    ["/", "formapp"],
    ["/proposals", "Drafts - formapp"],
    ["/proposals/submitted", "Submitted - formapp"],
    ["/proposals/42", "Ally_Macbeal_Proposal_001 - formapp"],
  ] as const) {
    test(`story 1.4: ${route} sets the tab title`, async ({ page }) => {
      await open(page, route);
      await expect(page).toHaveTitle(title);
    });
  }

  test("story 1.4: the skip link is the first Tab stop and moves focus to main", async ({
    page,
  }) => {
    await open(page, "/proposals");

    await page.keyboard.press("Tab");
    const skip = page.getByRole("link", { name: "Skip to main content" });
    await expect(skip).toBeFocused();
    await expect(skip).toBeInViewport();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("main")).toBeFocused();
    await expect(page).toHaveURL(/\/proposals$/);
  });

  test("story 1.9: a direct load of a proposal shows the real workspace", async ({
    page,
  }) => {
    await page.goto("/proposals/42");
    await expect(page.getByRole("heading", { level: 2 })).toHaveText(
      "1 · Needs",
    );
    await expect(page.getByRole("banner")).toContainText(
      "Drafts / Ally_Macbeal_Proposal_001",
    );
    await page.reload();
    await expect(page.getByRole("heading", { level: 2 })).toHaveText(
      "1 · Needs",
    );
  });

  test("story 1.4: an unknown path shows Drafts", async ({ page }) => {
    await page.goto("/nope");
    await expect(page).toHaveURL(/\/proposals$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "My proposals",
    );
  });
});

test.describe("1.6 Welcome page and sign-in", () => {
  test("story 1.6: Welcome shows one split flat card whose only control is the sign-in button", async ({
    page,
  }) => {
    await open(page, "/");

    await expect(
      page.getByRole("heading", { level: 1, name: "formapp" }),
    ).toBeVisible();
    await expect(
      page.getByText(
        "Tell the AI about your customer. It fills in the proposal for you to check.",
      ),
    ).toBeVisible();
    await expect(page.getByText("Photo placeholder")).toBeVisible();
    await expect(page.getByRole("banner")).toHaveCount(0);
    const signIn = page.getByRole("link", { name: "Sign in with Microsoft" });
    await expect(signIn).toHaveAttribute(
      "href",
      "/.auth/login/aad?post_login_redirect_uri=/proposals",
    );
    const box = await signIn.boundingBox();
    expect(box?.height).toBeGreaterThanOrEqual(52);
    expect(box?.width).toBeLessThanOrEqual(380);

    // Tab visits the button and nothing else: the chips are never focusable.
    const stops = new Set<string>();
    for (let step = 0; step < 5; step += 1) {
      await page.keyboard.press("Tab");
      stops.add(
        await page.evaluate(() => {
          const element = document.activeElement;
          // Tab past the last stop leaves focus on the page itself, which isn't a control.
          if (!element || element === document.body) return "";
          return element.textContent?.trim() ?? "";
        }),
      );
    }
    stops.delete("");
    expect([...stops]).toEqual(["Sign in with Microsoft"]);
    await expect(page.locator(".welcome-chips")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  for (const route of ["/proposals", "/proposals/42"]) {
    test(`story 1.6: a signed-out visitor at ${route} lands on Welcome`, async ({
      page,
    }) => {
      await mockMe(page, false);
      await page.goto(route);

      await expect(
        page.getByRole("link", { name: "Sign in with Microsoft" }),
      ).toBeVisible();
      await expect(page).toHaveURL(/\/$/);
    });
  }

  test("story 1.6: a signed-in user at / goes to My proposals › Drafts", async ({
    page,
  }) => {
    await page.goto("/");

    await expect(page).toHaveURL(/\/proposals$/);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      "My proposals",
    );
  });

  test("story 1.6: the avatar menu opens by keyboard, Escape returns focus, and Sign out lands on Welcome", async ({
    page,
  }) => {
    await open(page, "/proposals");
    const banner = page.getByRole("banner");
    await expect(banner).toContainText("formapp");
    const avatar = banner.getByRole("button", { name: "Alice, account menu" });
    await expect(avatar).toContainText("Alice");

    await avatar.focus();
    await page.keyboard.press("Enter");
    const signOut = page.getByRole("menuitem", { name: "Sign out" });
    await expect(signOut).toBeFocused();
    await page.keyboard.press("Escape");
    await expect(signOut).toHaveCount(0);
    await expect(avatar).toBeFocused();

    await page.keyboard.press("Space");
    await expect(signOut).toBeFocused();
    const results = await new AxeBuilder({ page })
      .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
      .analyze();
    expect(results.violations.map((v) => v.id)).toEqual([]);

    // Container Apps ends the session and sends her to /; from then on /api/me answers 401.
    await page.route("**/.auth/logout**", async (route) => {
      await mockMe(page, false);
      await route.fulfill({ status: 302, headers: { location: "/" } });
    });
    await signOut.click();

    await expect(
      page.getByRole("link", { name: "Sign in with Microsoft" }),
    ).toBeVisible();
    await expect(page).toHaveURL(/\/$/);
  });
});
