import { expect, test, type Page } from "@playwright/test";

// FORM-225/FORM-223 (DESIGN.md Layout & Spacing "Proposal workspace", mockups/key-workspace.html):
// at laptop sizes, the workspace fills the viewport under the header and the document itself
// never scrolls -- the top 3/4 (page menu + form card) and the bottom 1/4 (chat card) each scroll
// on their own instead. This file is self-contained (mocked GET /api/me, the draft, its schema,
// the edit lock, the product list and the chat history) like shell.spec.ts's own workspace tests,
// so it never depends on real seed data or another lane's database state.

const ALICE = { name: "Alice Synthetic", first_name: "Alice" };

// Enough rows on one page to be taller than any laptop-height form card, so
// `.workspace__form`'s own `overflow: auto` is actually exercised (Story 1.9's
// WorkspaceObjectFieldTemplate only renders a question when its id is both `active` and on the
// current page). H1/H2 keep the real answer-control mapping's unit suffixes (widgets.tsx
// UNIT_BY_QID): this is what FORM-223 ("cm"/"kg" stacked on their input) is about.
const FILLER_COUNT = 18;
const FILLER_IDS = Array.from({ length: FILLER_COUNT }, (_, i) => `F${i + 1}`);

function buildSchema() {
  const properties: Record<string, Record<string, unknown>> = {
    H1: { title: "Height", type: "number", "x-page": 1 },
    H2: { title: "Weight", type: "number", "x-page": 1 },
  };
  for (const id of FILLER_IDS) {
    properties[id] = {
      title: `Synthetic filler question ${id}`,
      type: "number",
      "x-page": 1,
    };
  }
  return {
    $id: "urn:formapp:form-schema:v1",
    properties,
    required: [] as string[],
    allOf: [] as unknown[],
  };
}

function buildDraft() {
  const answers: Record<string, unknown> = { H1: 170, H2: 65 };
  return {
    id: "42",
    status: "draft",
    schema_version: 1,
    revision: 0,
    lock: { holder: "you", expires_at: null },
    active: ["H1", "H2", ...FILLER_IDS],
    answers,
    provenance: {},
    quote: null,
    display_name: "Ally_Macbeal_Proposal_001",
  };
}

// Enough chat turns to be taller than any laptop-height chat card, so
// `.chat-panel__messages`'s own `overflow-y: auto` is actually exercised.
const CHAT_HISTORY = Array.from({ length: 24 }, (_, i) => ({
  role: i % 2 === 0 ? "user" : "assistant",
  text: `Synthetic chat turn number ${i + 1} for the workspace layout check.`,
}));

async function mockWorkspaceRoutes(page: Page) {
  await page.route("**/api/me", (route) =>
    route.fulfill({ status: 200, json: ALICE }),
  );
  await page.route("**/api/proposals/42", (route) =>
    route.fulfill({ status: 200, json: buildDraft() }),
  );
  await page.route("**/api/proposals/42/schema", (route) =>
    route.fulfill({ status: 200, json: buildSchema() }),
  );
  await page.route(/\/api\/products(\?.*)?$/, (route) =>
    route.fulfill({ status: 200, json: [] }),
  );
  await page.route("**/api/proposals/42/lock", (route) =>
    route.fulfill({ status: 200, json: { holder: "you", expires_at: null } }),
  );
  await page.route("**/api/proposals/42/chat", (route) =>
    route.fulfill({ status: 200, json: { messages: CHAT_HISTORY } }),
  );
}

/** The workspace's own layout boxes, read once the panel has real content in it. */
async function readLayout(page: Page) {
  await expect(page.locator(".workspace__work")).toBeVisible();
  await expect(page.locator(".workspace__chat")).toBeVisible();
  // The chat history mock resolves asynchronously; give the message list a moment to render
  // before measuring its scrollability.
  await expect(
    page.locator(".chat-panel__messages .chat-bubble").first(),
  ).toBeVisible();

  return page.evaluate(() => {
    const doc = document.documentElement;
    const workspace = document
      .querySelector(".workspace")!
      .getBoundingClientRect();
    const chat = document
      .querySelector(".workspace__chat")!
      .getBoundingClientRect();
    const form = document.querySelector(".workspace__form")!;
    const messages = document.querySelector(".chat-panel__messages")!;
    return {
      documentScrollHeight: doc.scrollHeight,
      windowInnerHeight: window.innerHeight,
      workspaceTop: workspace.top,
      workspaceHeight: workspace.height,
      chatTop: chat.top,
      formScrollHeight: form.scrollHeight,
      formClientHeight: form.clientHeight,
      messagesScrollHeight: messages.scrollHeight,
      messagesClientHeight: messages.clientHeight,
    };
  });
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
]) {
  test.describe(`FORM-225 workspace layout at ${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test("FORM-225: the document never scrolls, and the form card and message list do", async ({
      page,
    }) => {
      await mockWorkspaceRoutes(page);
      await page.goto("/proposals/42");
      const layout = await readLayout(page);

      // "the page itself never scrolls" (FORM-225).
      expect(layout.documentScrollHeight).toBeLessThanOrEqual(
        layout.windowInnerHeight + 1,
      );

      // "the chat card ... fixed, full width" at "about 75% of the space under the header": the
      // page menu/form card block above it takes roughly the top 3/4 of the workspace's own
      // height (DESIGN.md "split 3:1 vertically").
      const splitRatio =
        (layout.chatTop - layout.workspaceTop) / layout.workspaceHeight;
      expect(splitRatio).toBeGreaterThan(0.68);
      expect(splitRatio).toBeLessThan(0.82);

      // The form card scrolls on its own (18 filler rows + H1/H2 is taller than any laptop's 3/4
      // split).
      expect(layout.formScrollHeight).toBeGreaterThan(layout.formClientHeight);

      // The chat message list scrolls on its own (24 synthetic turns is taller than any laptop's
      // 1/4 split).
      expect(layout.messagesScrollHeight).toBeGreaterThan(
        layout.messagesClientHeight,
      );
    });

    test("FORM-223: H1/H2 unit labels sit beside their own inputs, not stacked on them", async ({
      page,
    }) => {
      await mockWorkspaceRoutes(page);
      await page.goto("/proposals/42");
      await expect(page.locator("#root_H1")).toBeVisible();

      for (const [id, unit] of [
        ["H1", "cm"],
        ["H2", "kg"],
      ] as const) {
        const input = page.locator(`#root_${id}`);
        const unitLabel = page.locator(`#root_${id} + .ws-unit-input__unit`);
        await expect(unitLabel).toHaveText(unit);

        const inputBox = await input.boundingBox();
        const unitBox = await unitLabel.boundingBox();
        expect(inputBox, `${id} input box`).not.toBeNull();
        expect(unitBox, `${id} unit box`).not.toBeNull();
        if (!inputBox || !unitBox) continue;

        // Beside, not overlapping: the unit starts at or after the input's own right edge.
        expect(unitBox.x).toBeGreaterThanOrEqual(
          inputBox.x + inputBox.width - 1,
        );
        // On the same line: vertical centres line up, not stacked above/below one another.
        const inputCenterY = inputBox.y + inputBox.height / 2;
        const unitCenterY = unitBox.y + unitBox.height / 2;
        expect(Math.abs(inputCenterY - unitCenterY)).toBeLessThan(4);
      }
    });
  });
}
