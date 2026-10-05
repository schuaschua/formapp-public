import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import realSchema from "../../../../form-schema/v1.json";
import realSchemaV2 from "../../../../form-schema/v2.json";
import { BreadcrumbProvider, useBreadcrumbLabel } from "../../app/breadcrumb";
import { paths, proposalPath } from "../../app/paths";
import { SessionProvider, useSession } from "../../app/session";
import { readWebFile } from "../../tests/css";
import { strings } from "../../strings";
import { Workspace } from "./Workspace";
import {
  FIXTURE_422,
  FIXTURE_DRAFT,
  FIXTURE_DRAFT_G1_NO,
  FIXTURE_DRAFT_SUBMITTED,
  FIXTURE_DRAFT_SUBMITTED_WITH_CUSTOMER_NUMBER,
  FIXTURE_DRAFT_WITH_QUOTE,
  FIXTURE_PRODUCTS,
  FIXTURE_SCHEMA,
} from "./workspace.fixtures";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const PRODUCTS_URL = `/api/products?proposal_id=${FIXTURE_DRAFT.id}`;
const LOCK_URL = `/api/proposals/${FIXTURE_DRAFT.id}/lock`;

/** The default `POST .../lock` response every helper below wires in: free, so the caller always
 * holds it (Story 4.4) -- every pre-4.4 test keeps behaving exactly as it did before this lock
 * existed, unless a test overrides `lock` itself. */
const LOCK_YOU = { holder: "you", expires_at: null };

/** Matches the lock-elsewhere info note only, not any other text on the page. */
const LOCK_NOTE = { selector: ".info-note__text" };

function mockApi({
  draft = FIXTURE_DRAFT,
  schema = FIXTURE_SCHEMA,
  status = 200,
  products = FIXTURE_PRODUCTS,
  lock = LOCK_YOU,
}: {
  draft?: unknown;
  schema?: unknown;
  status?: number;
  products?: unknown;
  lock?: unknown;
} = {}) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === LOCK_URL && init?.method === "POST") {
      return jsonResponse(lock);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
      return jsonResponse(draft, status);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
      return jsonResponse(schema, status);
    }
    if (url === PRODUCTS_URL) {
      return jsonResponse(products);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
      return jsonResponse({ messages: [] });
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

const ANSWERS_URL = `/api/proposals/${FIXTURE_DRAFT.id}/answers`;

/** Every `PATCH .../answers` body sent so far, parsed (Story 1.10). */
function patchBodies(): {
  revision: number;
  answers: Record<string, unknown>;
}[] {
  return fetchMock.mock.calls
    .filter(
      ([input, init]) =>
        String(input) === ANSWERS_URL && init?.method === "PATCH",
    )
    .map(([, init]) => JSON.parse(String(init?.body)));
}

/** Every `POST .../lock` body sent so far, parsed (Story 4.4). */
function lockBodies(): { take_over: boolean }[] {
  return fetchMock.mock.calls
    .filter(
      ([input, init]) => String(input) === LOCK_URL && init?.method === "POST",
    )
    .map(([, init]) => JSON.parse(String(init?.body)));
}

/** Wires `PATCH .../answers` to `respond`, on top of `mockApi`'s draft/schema/lock handling. */
function mockPatch(
  respond: (body: {
    revision: number;
    answers: Record<string, unknown>;
  }) => Response | Promise<Response>,
  { lock = LOCK_YOU }: { lock?: unknown } = {},
) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === ANSWERS_URL && init?.method === "PATCH") {
      return respond(JSON.parse(String(init.body)));
    }
    if (url === LOCK_URL && init?.method === "POST") {
      return jsonResponse(lock);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
      return jsonResponse(FIXTURE_DRAFT);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
      return jsonResponse(FIXTURE_SCHEMA);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
      return jsonResponse({ messages: [] });
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

/** Wires `POST .../lock` to `respond`, on top of `mockApi`'s draft/schema handling -- for tests
 * that need the lock response to change from one call to the next (renew, take-over). */
function mockLock(
  respond: (body: { take_over: boolean }) => Response | Promise<Response>,
) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === LOCK_URL && init?.method === "POST") {
      return respond(JSON.parse(String(init.body)));
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
      return jsonResponse(FIXTURE_DRAFT);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
      return jsonResponse(FIXTURE_SCHEMA);
    }
    if (url === PRODUCTS_URL) {
      return jsonResponse(FIXTURE_PRODUCTS);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
      return jsonResponse({ messages: [] });
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

const VALIDATE_URL = `/api/proposals/${FIXTURE_DRAFT.id}/validate`;

/**
 * Wires `POST .../validate` to `respond`, and `PATCH .../answers` to `patchRespond` (default: the
 * happy-path draft), on top of the usual draft/schema handling (Story 3.1). `POST .../lock` answers
 * with `lock` (Story 4.4; default: held by the caller).
 */
function mockValidate(
  respond: () => Response | Promise<Response>,
  patchRespond: (body: {
    revision: number;
    answers: Record<string, unknown>;
  }) => Response | Promise<Response> = () => jsonResponse(FIXTURE_DRAFT),
  lock: unknown = LOCK_YOU,
) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === LOCK_URL && init?.method === "POST") {
      return jsonResponse(lock);
    }
    if (url === VALIDATE_URL && init?.method === "POST") {
      return respond();
    }
    if (url === ANSWERS_URL && init?.method === "PATCH") {
      return patchRespond(JSON.parse(String(init.body)));
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
      return jsonResponse(FIXTURE_DRAFT);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
      return jsonResponse(FIXTURE_SCHEMA);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
      return jsonResponse({ messages: [] });
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

function renderWorkspace() {
  return render(
    <MemoryRouter>
      <BreadcrumbProvider>
        <Workspace draftId={FIXTURE_DRAFT.id} />
      </BreadcrumbProvider>
    </MemoryRouter>,
  );
}

const SUBMIT_URL = `/api/proposals/${FIXTURE_DRAFT.id}/submit`;

/** Every `POST .../submit` body sent so far, parsed (Story 3.3). */
function submitBodies(): {
  revision: number;
  declaration_agreed: boolean;
  feedback: { rating: number | null; comment: string | null };
}[] {
  return fetchMock.mock.calls
    .filter(
      ([input, init]) =>
        String(input) === SUBMIT_URL && init?.method === "POST",
    )
    .map(([, init]) => JSON.parse(String(init?.body)));
}

/**
 * Wires `POST .../validate` to a clean result and `POST .../submit` to `respond` (default: the
 * happy-path submitted draft), on top of the usual draft/schema/lock handling (Story 3.3).
 */
function mockSubmit(
  respond: (body: {
    revision: number;
    declaration_agreed: boolean;
    feedback: { rating: number | null; comment: string | null };
  }) => Response | Promise<Response> = () =>
    jsonResponse({
      ...FIXTURE_DRAFT,
      status: "submitted",
      revision: FIXTURE_DRAFT.revision + 1,
      submitted_at: "2026-09-27T09:00:00Z",
    }),
) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === LOCK_URL && init?.method === "POST") {
      return jsonResponse(LOCK_YOU);
    }
    if (url === VALIDATE_URL && init?.method === "POST") {
      return jsonResponse({ errors: [] });
    }
    if (url === SUBMIT_URL && init?.method === "POST") {
      return respond(JSON.parse(String(init.body)));
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
      return jsonResponse(FIXTURE_DRAFT);
    }
    if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
      return jsonResponse(FIXTURE_SCHEMA);
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

const DELETE_URL = `/api/proposals/${FIXTURE_DRAFT.id}`;

/**
 * Wires `DELETE .../` to `respond` (default: a clean 204), on top of the usual draft/schema/lock
 * handling (Story FORM-227).
 */
function mockDelete(
  respond: () => Response | Promise<Response> = () =>
    new Response(null, { status: 204 }),
) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === DELETE_URL && init?.method === "DELETE") {
      return respond();
    }
    if (url === LOCK_URL && init?.method === "POST") {
      return jsonResponse(LOCK_YOU);
    }
    if (url === DELETE_URL) {
      return jsonResponse(FIXTURE_DRAFT);
    }
    if (url === `${DELETE_URL}/schema`) {
      return jsonResponse(FIXTURE_SCHEMA);
    }
    if (url === PRODUCTS_URL) {
      return jsonResponse(FIXTURE_PRODUCTS);
    }
    if (url === `${DELETE_URL}/chat`) {
      return jsonResponse({ messages: [] });
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

/** Reads the app's current location (Story 3.3): `navigate(paths.submitted, {state})`'s target and
 * its `toast` carry-through, next to a rendered `Workspace` (mirrors ProposalsPage.test.tsx's own
 * `CurrentPath`). */
function CurrentLocation() {
  const location = useLocation();
  const toast = (location.state as { toast?: string } | null)?.toast ?? "";
  return (
    <output data-testid="location">
      {location.pathname}|{toast}
    </output>
  );
}

function renderWorkspaceWithLocation() {
  return render(
    <MemoryRouter initialEntries={[proposalPath(FIXTURE_DRAFT.id)]}>
      <BreadcrumbProvider>
        <Workspace draftId={FIXTURE_DRAFT.id} />
      </BreadcrumbProvider>
      <CurrentLocation />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  mockApi();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("1.9 Workspace", () => {
  it("story 1.9: shows the menu and chat frame at once, with skeleton rows until it loads", async () => {
    let resolveDraft: (() => void) | undefined;
    fetchMock.mockImplementation(async (input) => {
      const url = String(input);
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
        await new Promise<void>((resolve) => (resolveDraft = resolve));
        return jsonResponse(FIXTURE_DRAFT);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
        return jsonResponse(FIXTURE_SCHEMA);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
        return jsonResponse({ messages: [] });
      }
      return jsonResponse({ errors: [] }, 404);
    });
    renderWorkspace();

    expect(screen.getByText(strings.workspace.pagesLabel)).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
    ).toBeInTheDocument();
    expect(
      document.querySelectorAll(".ws-skeleton-bar").length,
    ).toBeGreaterThan(0);

    resolveDraft?.();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    expect(document.querySelectorAll(".ws-skeleton-bar")).toHaveLength(0);
  });

  it("story 1.9: page 1 shows only its active questions, each with a control", async () => {
    renderWorkspace();

    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    expect(
      screen.getByText(strings.workspace.questionColumn),
    ).toBeInTheDocument();
    expect(
      screen.getByText(strings.workspace.answerColumn),
    ).toBeInTheDocument();
    expect(
      screen.getByText("What type of product are you looking for?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Should the policy cover your dependents?"),
    ).toBeInTheDocument();
    // A yes/no answer renders as a segmented pill, with the saved value selected.
    const dependentsRow = screen
      .getByText("Should the policy cover your dependents?")
      .closest(".ws-tbl__row") as HTMLElement;
    expect(within(dependentsRow).getByText("Yes")).toHaveClass(
      "ws-seg__option--on",
    );
    // Nothing on the page names who set an answer.
    expect(document.body.textContent).not.toMatch(/\bhuman\b|\bdefault\b/);
  });

  it("story 1.9: N4 is a follow-up of N3, indented and lighter", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    const row = screen
      .getByText("How many dependents?")
      .closest(".ws-tbl__row") as HTMLElement;
    expect(row).toHaveClass("ws-tbl__row--sub");
  });

  it("story 2.3: page 2 shows real product options from the priced product list, unanswered", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(screen.getByRole("button", { name: /Product/ }));
    await screen.findByRole("heading", { level: 2, name: "2 · Product" });
    const productRow = screen
      .getByText("Selected product")
      .closest(".ws-tbl__row") as HTMLElement;
    const productSelect = await within(productRow).findByRole("combobox");
    expect(
      within(productSelect).getByText("FamilyShield Life & Health"),
    ).toBeInTheDocument();
    expect(
      within(productSelect).getByText("SecureLife Term"),
    ).toBeInTheDocument();
    // P1/P3 aren't in this fixture schema's own `required` (unlike the real one, below).
    expect(screen.getByText("2 of 5 pages done")).toBeInTheDocument();
    expect(
      screen
        .getByRole("button", { name: /Product/ })
        .querySelector(".page-menu__check"),
    ).toBeNull();
  });

  it("story 2.3: P1/P3 answered through their real controls completes page 2 (released schema)", async () => {
    // The released form-schema/v1.json (unlike FIXTURE_SCHEMA) lists P1 and P3 in `required`;
    // both are real, answerable controls now (ProductWidget/TermWidget), unlike the old
    // NoOptionsWidget that could never complete page 2 at all.
    const schema = realSchema as unknown as typeof FIXTURE_SCHEMA;
    mockApi({
      draft: {
        ...FIXTURE_DRAFT,
        active: ["P1", "P3"],
        answers: { P1: "FSH", P3: "20_yrs" },
      },
      schema,
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(screen.getByRole("button", { name: /Product/ }));
    await screen.findByRole("heading", { level: 2, name: "2 · Product" });

    expect(screen.getByText("1 of 5 pages done")).toBeInTheDocument();
    expect(
      screen
        .getByRole("button", { name: /Product/ })
        .querySelector(".page-menu__check"),
    ).not.toBeNull();
  });

  it("story 1.9: clicking a page menu item shows that page", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(
      screen.getByRole("button", { name: /Health & lifestyle/ }),
    );

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "5 · Health & lifestyle",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("Height (cm)")).toBeInTheDocument();
    // A unit-mapped number shows its unit inside the field.
    const heightRow = screen
      .getByText("Height (cm)")
      .closest(".ws-tbl__row") as HTMLElement;
    expect(within(heightRow).getByText("cm")).toBeInTheDocument();
    // FORM-213: a plain text input (digit-only gate), not a native number spinner.
    expect(within(heightRow).getByRole("textbox")).toHaveValue("165");
  });

  it("story 1.9: the Gynaecology heading and G2 follow-up show only when G1 is active", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(
      screen.getByRole("button", { name: /Health & lifestyle/ }),
    );
    await screen.findByRole("heading", {
      level: 2,
      name: "5 · Health & lifestyle",
    });

    expect(screen.getByText(strings.workspace.gynaecology)).toBeInTheDocument();
    const g2Row = screen
      .getByText("Outcome of previous pregnancies")
      .closest(".ws-tbl__row") as HTMLElement;
    expect(g2Row).toHaveClass("ws-tbl__row--sub");
    // The checklist honours x-exclusive by rendering H4's pill options, "None" among them.
    const hazardRow = screen
      .getByText("Do you take part in any hazardous activities?")
      .closest(".ws-tbl__row") as HTMLElement;
    expect(within(hazardRow).getByText("None")).toBeInTheDocument();
  });

  it("story 1.9: page 4's select shows the 4-option marital status with labels", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });

    const row = screen
      .getByText("Marital status")
      .closest(".ws-tbl__row") as HTMLElement;
    const select = within(row).getByRole("combobox");
    expect(within(select).getByText("Married")).toBeInTheDocument();
    expect(within(select).getByText("Single")).toBeInTheDocument();
  });

  it("story 1.9: the progress bar reads 2 of 5 pages done for this draft", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(screen.getByText("2 of 5 pages done")).toBeInTheDocument();
    expect(
      screen
        .getByRole("button", { name: /Needs/ })
        .querySelector(".page-menu__check"),
    ).not.toBeNull();
    expect(
      screen
        .getByRole("button", { name: /Payment/ })
        .querySelector(".page-menu__check"),
    ).not.toBeNull();
    expect(
      screen
        .getByRole("button", { name: /Particulars/ })
        .querySelector(".page-menu__check"),
    ).toBeNull();
  });

  it("story 1.9: collapsing the menu shows the 64px rail", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.collapseMenu }),
    );
    expect(
      screen.getByRole("button", { name: strings.workspace.expandMenu }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(strings.workspace.pagesLabel),
    ).not.toBeInTheDocument();
  });

  it("story 1.9 fix: switching draftId on an already-mounted Workspace resets the page and menu", async () => {
    // React Router keeps `WorkspacePage` mounted across a same-route `:id`-only change (unlike
    // ProposalsPage's two separate routes), so `Workspace` itself must reset `currentPage` and
    // `collapsed` when `draftId` changes, not rely on remounting.
    const OTHER_ID = "55555555-5555-4555-8555-555555555555";
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === ANSWERS_URL && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as {
          revision: number;
          answers: Record<string, unknown>;
        };
        // N3 always 422s (dirties fieldProblems); anything else succeeds (dirties saveStatus).
        if ("N3" in body.answers) {
          return jsonResponse(
            {
              errors: [
                {
                  field: "N3",
                  code: "invalid_value",
                  message: "Enter a valid answer.",
                },
              ],
            },
            422,
          );
        }
        return jsonResponse({
          ...FIXTURE_DRAFT,
          revision: FIXTURE_DRAFT.revision + 1,
          answers: { ...FIXTURE_DRAFT.answers, ...body.answers },
        });
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
        return jsonResponse(FIXTURE_DRAFT);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
        return jsonResponse(FIXTURE_SCHEMA);
      }
      if (url === `/api/proposals/${OTHER_ID}`) {
        return jsonResponse({ ...FIXTURE_DRAFT, id: OTHER_ID });
      }
      if (url === `/api/proposals/${OTHER_ID}/schema`) {
        return jsonResponse(FIXTURE_SCHEMA);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
        return jsonResponse({ messages: [] });
      }
      return jsonResponse({ errors: [] }, 404);
    });
    const { rerender } = render(
      <MemoryRouter>
        <BreadcrumbProvider>
          <Workspace draftId={FIXTURE_DRAFT.id} />
        </BreadcrumbProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    // Dirty all three of autosave's own bits of state before switching drafts: a 422 on N3 sets
    // `fieldProblems`; a successful save on N1 right after sets `saveStatus` (and leaves N3's
    // fieldProblems in place -- success only clears the qids in its own snapshot); "offline"
    // then sets `banner` without touching either of the other two.
    const dependentsRow = screen
      .getByText("Should the policy cover your dependents?")
      .closest(".ws-tbl__row") as HTMLElement;
    await userEvent.click(
      within(dependentsRow).getByRole("button", { name: "No" }),
    );
    await screen.findByText("Enter a valid answer.");
    const coverRow = screen
      .getByText("What type of product are you looking for?")
      .closest(".ws-tbl__row") as HTMLElement;
    await userEvent.click(
      within(coverRow).getByRole("button", { name: "Health" }),
    );
    await screen.findByText(strings.workspace.saved);
    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    window.dispatchEvent(new Event("offline"));
    await screen.findByRole("alert");
    expect(screen.getByText("Enter a valid answer.")).toBeInTheDocument(); // still dirty

    await userEvent.click(screen.getByRole("button", { name: /Product/ }));
    await screen.findByRole("heading", { level: 2, name: "2 · Product" });
    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.collapseMenu }),
    );
    expect(
      screen.getByRole("button", { name: strings.workspace.expandMenu }),
    ).toBeInTheDocument();

    rerender(
      <MemoryRouter>
        <BreadcrumbProvider>
          <Workspace draftId={OTHER_ID} />
        </BreadcrumbProvider>
      </MemoryRouter>,
    );

    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    expect(
      screen.getByRole("button", { name: strings.workspace.collapseMenu }),
    ).toBeInTheDocument();
    // autosave's saveStatus/banner/fieldProblems all reset for the new draft too.
    expect(screen.queryByText(strings.workspace.saved)).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByText("Enter a valid answer.")).not.toBeInTheDocument();
  });

  it("story 1.9: another agent's draft id sends the caller back (not-found bubbles up)", async () => {
    mockApi({ status: 404 });
    render(
      <MemoryRouter>
        <BreadcrumbProvider>
          <Workspace draftId={FIXTURE_DRAFT.id} />
        </BreadcrumbProvider>
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(
        screen.queryByText(strings.workspace.pagesLabel),
      ).not.toBeInTheDocument(),
    );
  });

  it("story 1.9: a load failure shows an error message, not a blank page", async () => {
    mockApi({ status: 500 });
    renderWorkspace();

    expect(
      await screen.findByText(strings.workspace.loadError),
    ).toBeInTheDocument();
  });

  it("story 1.9: renders every page of the real released form-schema/v1.json without error", async () => {
    const schema = realSchema as unknown as typeof FIXTURE_SCHEMA;
    // Every question active except D1 (never active, AD-7), so every page and control type in the
    // released schema gets exercised at least once, with no answers to keep this a pure rendering
    // smoke test.
    const active = Object.keys(schema.properties).filter((qid) => qid !== "D1");
    mockApi({
      draft: { ...FIXTURE_DRAFT, active, answers: {} },
      schema,
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    for (const page of [1, 2, 3, 4, 5]) {
      const name = strings.workspace.pagesByVersion[1]?.[page] ?? String(page);
      await userEvent.click(
        screen.getByRole("button", { name: new RegExp(name) }),
      );
      await screen.findByRole("heading", {
        level: 2,
        name: strings.workspace.pageHeading(page, name),
      });
    }
    expect(screen.getByText(strings.workspace.gynaecology)).toBeInTheDocument();
  });

  it("FORM-222: renders every page of the real released form-schema/v2.json without error", async () => {
    const schema = realSchemaV2 as unknown as typeof FIXTURE_SCHEMA;
    // Same smoke test as v1's above, against the new 4-page released schema: proves the page
    // menu/heading/price-summary placement are schema-driven, not the old hardcoded 5-page shape.
    const active = Object.keys(schema.properties).filter((qid) => qid !== "D1");
    mockApi({
      draft: { ...FIXTURE_DRAFT, schema_version: 2, active, answers: {} },
      schema,
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Product" });

    for (const page of [1, 2, 3, 4]) {
      const name = strings.workspace.pagesByVersion[2]?.[page] ?? String(page);
      await userEvent.click(
        screen.getByRole("button", { name: new RegExp(name) }),
      );
      await screen.findByRole("heading", {
        level: 2,
        name: strings.workspace.pageHeading(page, name),
      });
    }
    expect(screen.getByText(strings.workspace.gynaecology)).toBeInTheDocument();
  });

  it("story 1.9: at the 200% zoom breakpoint each question stacks above its answer", () => {
    const css = readWebFile("src/pages/workspace/Workspace.css");
    const mediaBlock = /@media \(max-width: 900px\)\s*\{([\s\S]*)\}\s*$/.exec(
      css,
    )?.[1];
    expect(mediaBlock).toContain("grid-template-columns: 1fr;");
  });
});

describe("1.10 Workspace autosave", () => {
  function findRow(labelText: string): HTMLElement {
    return screen.getByText(labelText).closest(".ws-tbl__row") as HTMLElement;
  }

  it("story 1.10: leaving a text field unchanged sends nothing", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });

    await userEvent.click(within(findRow("First name")).getByRole("textbox"));
    await userEvent.tab(); // blur without changing "Ally"

    expect(patchBodies()).toEqual([]);
  });

  it("story 1.10: editing a text field on blur sends only that field, then shows Saving.../Saved", async () => {
    mockPatch(() =>
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 4,
        answers: { ...FIXTURE_DRAFT.answers, C1: "Bea" },
      }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    const input = within(findRow("First name")).getByRole("textbox");

    await userEvent.clear(input);
    await userEvent.type(input, "Bea");
    await userEvent.tab();

    await screen.findByText(strings.workspace.saved);
    expect(patchBodies()).toEqual([{ revision: 3, answers: { C1: "Bea" } }]);
  });

  it("story FORM-21 fix: a field still being typed survives an unrelated field's save landing before it's blurred", async () => {
    // Regression (journey2.spec.ts, FORM-21): `<Form formData={state.draft.answers}>` (below in
    // Workspace.tsx) is fully controlled, so replacing `state.draft` from ANY field's `onSaved`
    // used to resync RJSF's whole formData tree -- including a different, not-yet-blurred text
    // field's own in-progress keystrokes, which live only in RJSF's internal state until blur --
    // and blank it out. Story 4.3 Part B's row-level security and Story 4.9's `answer_overrides`
    // insert both add a little per-PATCH latency, which is what turned this into a real,
    // reproducible data-loss bug rather than a once-in-a-blue-moon race: see `focusedFieldRef`'s
    // own comment in Workspace.tsx for the fix.
    let releaseMaritalPatch!: (response: Response) => void;
    const maritalPatchResponse = new Promise<Response>((resolve) => {
      releaseMaritalPatch = resolve;
    });
    let patchCount = 0;
    mockPatch((body) => {
      patchCount += 1;
      if (patchCount === 1) return maritalPatchResponse; // held back until released below
      return jsonResponse({
        ...FIXTURE_DRAFT,
        revision: FIXTURE_DRAFT.revision + patchCount,
        answers: { ...FIXTURE_DRAFT.answers, ...body.answers },
      });
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });

    // Marital status commits at once (no blur needed); its PATCH is the one held back.
    await userEvent.selectOptions(
      within(findRow("Marital status")).getByRole("combobox"),
      "Divorced",
    );

    // She moves on to "First name" and starts typing, without blurring it yet.
    const firstName = within(findRow("First name")).getByRole("textbox");
    await userEvent.click(firstName);
    await userEvent.clear(firstName);
    await userEvent.type(firstName, "Bea");
    expect(firstName).toHaveValue("Bea");

    // The held-back marital-status write now lands while "First name" is still focused and
    // unsaved.
    releaseMaritalPatch(
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: FIXTURE_DRAFT.revision + 1,
        answers: { ...FIXTURE_DRAFT.answers, C11: "divorced" },
      }),
    );
    await waitFor(() => expect(patchBodies()).toHaveLength(1));

    // The still-focused field's typed value must survive that unrelated save landing.
    expect(firstName).toHaveValue("Bea");

    await userEvent.tab(); // blur "First name": now it commits, with the real typed value
    await waitFor(() => expect(patchBodies()).toHaveLength(2));
    expect(patchBodies()[1]).toEqual({
      revision: FIXTURE_DRAFT.revision + 1,
      answers: { C1: "Bea" },
    });
  });

  it("story 1.10: clicking a Yes/No pill commits it at once, with no blur needed", async () => {
    mockPatch(() =>
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 4,
        answers: { ...FIXTURE_DRAFT.answers, N3: "No" },
      }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const row = findRow("Should the policy cover your dependents?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    expect(patchBodies()).toEqual([{ revision: 3, answers: { N3: "No" } }]);
    await screen.findByText(strings.workspace.saved);
  });

  it("story 1.10: clicking checklist pills commits the array at once, honouring x-exclusive", async () => {
    // H4 starts unanswered: also exercises the "Too many re-renders" crash fix (an unanswered
    // checklist question must render without looping).
    mockPatch((body) =>
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: FIXTURE_DRAFT.revision + 1,
        answers: { ...FIXTURE_DRAFT.answers, ...body.answers },
      }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(
      screen.getByRole("button", { name: /Health & lifestyle/ }),
    );
    await screen.findByRole("heading", {
      level: 2,
      name: "5 · Health & lifestyle",
    });
    const row = findRow("Do you take part in any hazardous activities?");

    // A non-exclusive pill selects it.
    await userEvent.click(
      within(row).getByRole("button", { name: "Scuba diving" }),
    );
    await screen.findByText(strings.workspace.saved);
    expect(patchBodies().at(-1)).toEqual({
      revision: 3,
      answers: { H4: ["scuba_diving"] },
    });
    expect(
      within(row).getByRole("button", { name: "Scuba diving" }),
    ).toHaveClass("ws-checklist__option--on");

    // The exclusive pill ("None") clears every other selection.
    await userEvent.click(within(row).getByRole("button", { name: "None" }));
    await waitFor(() =>
      expect(patchBodies().at(-1)).toEqual({
        revision: 4,
        answers: { H4: ["none"] },
      }),
    );
    expect(within(row).getByRole("button", { name: "None" })).toHaveClass(
      "ws-checklist__option--on",
    );
    expect(
      within(row).getByRole("button", { name: "Scuba diving" }),
    ).not.toHaveClass("ws-checklist__option--on");
  });

  it("story 1.10: a rejected value gets the amber highlight and its message, and never Saved ✓", async () => {
    mockPatch(() => jsonResponse(FIXTURE_422, 422));
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    const input = within(findRow("First name")).getByRole("textbox");

    await userEvent.clear(input);
    await userEvent.type(input, "Zz");
    await userEvent.tab();

    const message = await screen.findByText("Enter a valid answer.");
    expect(message.closest(".ws-tbl__cell")).toHaveClass(
      "ws-tbl__cell--problem",
    );
    expect(screen.queryByText(strings.workspace.saved)).not.toBeInTheDocument();
    // The typed (rejected) value stays on screen.
    expect(input).toHaveValue("Zz");
  });

  it("story 1.10: a stale revision silently refetches and resends once, with no banner", async () => {
    let firstAttempt = true;
    mockPatch((body) => {
      if (firstAttempt) {
        firstAttempt = false;
        return jsonResponse(
          {
            errors: [
              {
                field: "revision",
                code: "stale_revision",
                message: "Reload the draft.",
              },
            ],
          },
          409,
        );
      }
      return jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 5,
        answers: { ...FIXTURE_DRAFT.answers, ...body.answers },
      });
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const row = findRow("Should the policy cover your dependents?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    await screen.findByText(strings.workspace.saved);
    expect(patchBodies()).toEqual([
      { revision: 3, answers: { N3: "No" } },
      { revision: 3, answers: { N3: "No" } },
    ]);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("story 1.10: a save failure shows the red retry banner, and Retry saves again", async () => {
    let attempts = 0;
    mockPatch(() => {
      attempts += 1;
      if (attempts === 1) return jsonResponse({ detail: "boom" }, 502);
      return jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 4,
        answers: { ...FIXTURE_DRAFT.answers, N3: "No" },
      });
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const row = findRow("Should the policy cover your dependents?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(strings.workspace.saveFailedMessage);
    // The rejected-but-not-yet-retried value stays on screen.
    expect(within(row).getByRole("button", { name: "No" })).toHaveClass(
      "ws-seg__option--on",
    );

    await userEvent.click(
      within(banner).getByRole("button", { name: "Retry" }),
    );

    await screen.findByText(strings.workspace.saved);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(attempts).toBe(2);
  });

  it("story 1.10: the connection-lost banner shows offline and clears once back online", async () => {
    mockPatch(() =>
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 4,
        answers: { ...FIXTURE_DRAFT.answers, N3: "No" },
      }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    window.dispatchEvent(new Event("offline"));
    const row = findRow("Should the policy cover your dependents?");
    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    const banner = await screen.findByRole("alert");
    expect(banner).toHaveTextContent(strings.workspace.connectionLostMessage);
    expect(patchBodies()).toEqual([]); // queued, not sent, while offline

    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(true);
    window.dispatchEvent(new Event("online"));

    await screen.findByText(strings.workspace.saved);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(patchBodies()).toEqual([{ revision: 3, answers: { N3: "No" } }]);
  });

  it("story 1.10: a save's returned active list reveals and hides follow-up rows at once", async () => {
    mockPatch(() => jsonResponse(FIXTURE_DRAFT_G1_NO));
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(
      screen.getByRole("button", { name: /Health & lifestyle/ }),
    );
    await screen.findByRole("heading", {
      level: 2,
      name: "5 · Health & lifestyle",
    });
    expect(
      screen.getByText("Outcome of previous pregnancies"),
    ).toBeInTheDocument();
    const row = findRow("Have you ever been pregnant?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    await waitFor(() =>
      expect(
        screen.queryByText("Outcome of previous pregnancies"),
      ).not.toBeInTheDocument(),
    );
  });

  it("story 1.10: the breadcrumb updates from the save response's display_name", async () => {
    mockPatch(() =>
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 4,
        answers: { ...FIXTURE_DRAFT.answers, N3: "No" },
        display_name: "Bea_Macbeal_Proposal_001",
      }),
    );
    function BreadcrumbProbe() {
      return <p data-testid="breadcrumb">{useBreadcrumbLabel()}</p>;
    }
    render(
      <MemoryRouter>
        <BreadcrumbProvider>
          <BreadcrumbProbe />
          <Workspace draftId={FIXTURE_DRAFT.id} />
        </BreadcrumbProvider>
      </MemoryRouter>,
    );
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await waitFor(() =>
      expect(screen.getByTestId("breadcrumb")).toHaveTextContent(
        FIXTURE_DRAFT.display_name,
      ),
    );
    const row = findRow("Should the policy cover your dependents?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    await waitFor(() =>
      expect(screen.getByTestId("breadcrumb")).toHaveTextContent(
        "Bea_Macbeal_Proposal_001",
      ),
    );
  });

  it("story 1.10: no element, class or text on the page ever names an answer's source", async () => {
    mockPatch(() =>
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 4,
        answers: { ...FIXTURE_DRAFT.answers, N3: "No" },
      }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const row = findRow("Should the policy cover your dependents?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));
    await screen.findByText(strings.workspace.saved);

    expect(document.body.textContent).not.toMatch(/\bhuman\b|\bdefault\b/);
    expect(document.body.innerHTML).not.toMatch(/provenance/);
  });

  it("story 1.10: a 401 from an autosave PATCH (not just /api/me) pushes the session to signed-out at once", async () => {
    // Closes the Story 1.6 TODO this story's own spec cites: a failed autosave call must not wait
    // for a route change before the app notices the session is gone.
    function SessionProbe() {
      return (
        <output data-testid="session-status">{useSession().status}</output>
      );
    }
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/me") {
        return jsonResponse({ name: "Alice Synthetic", first_name: "Alice" });
      }
      if (url === ANSWERS_URL && init?.method === "PATCH") {
        return jsonResponse({ errors: [] }, 401);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
        return jsonResponse(FIXTURE_DRAFT);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
        return jsonResponse(FIXTURE_SCHEMA);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
        return jsonResponse({ messages: [] });
      }
      return jsonResponse({ errors: [] }, 404);
    });
    render(
      <MemoryRouter>
        <SessionProvider>
          <SessionProbe />
          <BreadcrumbProvider>
            <Workspace draftId={FIXTURE_DRAFT.id} />
          </BreadcrumbProvider>
        </SessionProvider>
      </MemoryRouter>,
    );
    await waitFor(() =>
      expect(screen.getByTestId("session-status")).toHaveTextContent(
        "signed-in",
      ),
    );
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const row = findRow("Should the policy cover your dependents?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    await waitFor(() =>
      expect(screen.getByTestId("session-status")).toHaveTextContent(
        "signed-out",
      ),
    );
  });
});

describe("2.3 Workspace product, riders and price summary", () => {
  async function goToProductPage() {
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Product/ }));
    await screen.findByRole("heading", { level: 2, name: "2 · Product" });
  }

  /** Like `mockPatch`, but the draft `GET`/PATCH response both start from `initialDraft` rather
   * than the plain `FIXTURE_DRAFT` -- these tests need P1 already answered before they render. */
  function mockApiAndPatch(
    initialDraft: Omit<typeof FIXTURE_DRAFT, "answers"> & {
      answers: Record<string, unknown>;
    },
  ) {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === ANSWERS_URL && init?.method === "PATCH") {
        const body = JSON.parse(String(init.body)) as {
          revision: number;
          answers: Record<string, unknown>;
        };
        return jsonResponse({
          ...initialDraft,
          revision: initialDraft.revision + 1,
          answers: { ...initialDraft.answers, ...body.answers },
        });
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
        return jsonResponse(initialDraft);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
        return jsonResponse(FIXTURE_SCHEMA);
      }
      if (url === PRODUCTS_URL) {
        return jsonResponse(FIXTURE_PRODUCTS);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
        return jsonResponse({ messages: [] });
      }
      return jsonResponse({ errors: [] }, 404);
    });
  }

  it("story 2.3: choosing a product commits {P1, P2} in one PATCH, dropping a foreign rider", async () => {
    // R01 (Critical illness) belongs to LT20, not FSH: choosing FSH must drop it.
    mockApiAndPatch({
      ...FIXTURE_DRAFT,
      answers: { ...FIXTURE_DRAFT.answers, P2: ["R01"] },
    });
    renderWorkspace();
    await goToProductPage();
    const productRow = screen
      .getByText("Selected product")
      .closest(".ws-tbl__row") as HTMLElement;
    const select = await within(productRow).findByRole("combobox");

    await userEvent.selectOptions(select, "FSH");

    await waitFor(() =>
      expect(patchBodies().at(-1)).toEqual({
        revision: FIXTURE_DRAFT.revision,
        answers: { P1: "FSH", P2: [] },
      }),
    );
  });

  it("story 2.3: the rider control asks to choose a product first, until P1 is set", async () => {
    mockApi();
    renderWorkspace();
    await goToProductPage();

    const riderRow = screen
      .getByText("Optional riders")
      .closest(".ws-tbl__row") as HTMLElement;
    expect(
      within(riderRow).getByText(strings.workspace.chooseProductFirst),
    ).toBeInTheDocument();
  });

  it("story 2.3: with a product chosen, a rider pill commits P2 alone", async () => {
    mockApiAndPatch({
      ...FIXTURE_DRAFT,
      answers: { ...FIXTURE_DRAFT.answers, P1: "FSH" },
    });
    renderWorkspace();
    await goToProductPage();
    const riderRow = screen
      .getByText("Optional riders")
      .closest(".ws-tbl__row") as HTMLElement;
    const pill = await within(riderRow).findByRole("button", {
      name: "Maternity & newborn",
    });

    await userEvent.click(pill);

    await waitFor(() =>
      expect(patchBodies().at(-1)).toEqual({
        revision: FIXTURE_DRAFT.revision,
        answers: { P2: ["R07"] },
      }),
    );
    expect(pill).toHaveClass("ws-checklist__option--on");
  });

  it("story 2.3: with a product chosen, the term control offers only its terms and commits P3 alone", async () => {
    mockApiAndPatch({
      ...FIXTURE_DRAFT,
      answers: { ...FIXTURE_DRAFT.answers, P1: "FSH" },
    });
    renderWorkspace();
    await goToProductPage();
    const termRow = screen
      .getByText("Policy term")
      .closest(".ws-tbl__row") as HTMLElement;
    const select = await within(termRow).findByRole("combobox");
    expect(within(select).getByText("20 yrs")).toBeInTheDocument();
    expect(within(select).getByText("30 yrs")).toBeInTheDocument();

    await userEvent.selectOptions(select, "20_yrs");

    await waitFor(() =>
      expect(patchBodies().at(-1)).toEqual({
        revision: FIXTURE_DRAFT.revision,
        answers: { P3: "20_yrs" },
      }),
    );
  });

  it("story 2.3: the price summary shows the placeholder until a product and DOB are set", async () => {
    renderWorkspace();
    await goToProductPage();

    expect(
      screen.getByText(strings.priceSummary.placeholder),
    ).toBeInTheDocument();
  });

  it("story 2.3: the price summary shows the product/rider lines and total from quote", async () => {
    mockApi({ draft: FIXTURE_DRAFT_WITH_QUOTE });
    renderWorkspace();
    await goToProductPage();

    expect(
      screen.getByText(
        "FamilyShield Life & Health: RM185.22 monthly, RM2,111.51 yearly",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Maternity & newborn: RM34.73 monthly, RM395.91 yearly"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Total: RM219.95 monthly, RM2,507.42 yearly (paying yearly saves 5%)",
      ),
    ).toBeInTheDocument();
  });

  it("story 2.3: the price summary also shows on page 3 (Payment)", async () => {
    mockApi({ draft: FIXTURE_DRAFT_WITH_QUOTE });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Payment/ }));
    await screen.findByRole("heading", { level: 2, name: "3 · Payment" });

    expect(screen.getByText(/Total: RM219\.95 monthly/)).toBeInTheDocument();
  });

  it("story 2.3: the price summary does not show on page 1 (Needs)", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(
      screen.queryByText(strings.priceSummary.placeholder),
    ).not.toBeInTheDocument();
  });
});

/** FORM-213: "Submit proposal" only shows on page 5 -- every Story 3.1 test below reaches it from
 * page 1 (the default) with this, before clicking or looking for Submit itself. */
async function goToLastPage() {
  await userEvent.click(
    screen.getByRole("button", { name: /Health & lifestyle/ }),
  );
  await screen.findByRole("heading", {
    level: 2,
    name: "5 · Health & lifestyle",
  });
}

describe("3.1 Workspace Submit", () => {
  it("story 3.1: Submit with errors jumps to the first problem page and boxes every problem page, with no banner or modal", async () => {
    // C11 (page 4) and H4 (page 5): the lower page number is first.
    mockValidate(() =>
      jsonResponse({
        errors: [
          { field: "H4", code: "required", message: "Answer required" },
          { field: "C11", code: "required", message: "Answer required" },
        ],
      }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.submitProposal }),
    );

    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    expect(screen.getByRole("button", { name: /Particulars/ })).toHaveClass(
      "page-menu__item--problem",
    );
    expect(
      screen.getByRole("button", { name: /Health & lifestyle/ }),
    ).toHaveClass("page-menu__item--problem");
    expect(screen.getByRole("button", { name: /Needs/ })).not.toHaveClass(
      "page-menu__item--problem",
    );
    // The open page's own C11 row gets the amber highlight, badge and message.
    const message = await screen.findByText("Answer required");
    expect(message.closest(".ws-tbl__cell")).toHaveClass(
      "ws-tbl__cell--problem",
    );
    expect(
      message.closest(".ws-tbl__cell")?.querySelector(".ws-problem__badge"),
    ).not.toBeNull();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("story 3.1: fixing and saving a flagged answer clears its highlight and the page's box at once, with no second Submit", async () => {
    mockValidate(
      () =>
        jsonResponse({
          errors: [
            { field: "C11", code: "required", message: "Answer required" },
          ],
        }),
      () =>
        jsonResponse({
          ...FIXTURE_DRAFT,
          revision: 4,
          answers: { ...FIXTURE_DRAFT.answers, C11: "single" },
        }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.submitProposal }),
    );
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    await screen.findByText("Answer required");
    expect(screen.getByRole("button", { name: /Particulars/ })).toHaveClass(
      "page-menu__item--problem",
    );

    const row = screen
      .getByText("Marital status")
      .closest(".ws-tbl__row") as HTMLElement;
    const select = within(row).getByRole("combobox");
    await userEvent.selectOptions(select, "single");

    await waitFor(() =>
      expect(screen.queryByText("Answer required")).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("button", { name: /Particulars/ })).not.toHaveClass(
      "page-menu__item--problem",
    );
    // No second Submit call: only the one from the click above.
    expect(
      fetchMock.mock.calls.filter(
        ([input, init]) =>
          String(input) === VALIDATE_URL && init?.method === "POST",
      ),
    ).toHaveLength(1);
  });

  it("story 3.1: Submit with a clean result clears any existing highlight and opens the declaration modal (Story 3.3)", async () => {
    mockValidate(
      () => jsonResponse({ errors: [] }),
      () => jsonResponse(FIXTURE_422, 422),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    const input = within(
      screen.getByText("First name").closest(".ws-tbl__row") as HTMLElement,
    ).getByRole("textbox");
    await userEvent.clear(input);
    await userEvent.type(input, "Zz");
    await userEvent.tab();
    await screen.findByText("Enter a valid answer.");
    await goToLastPage();

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.submitProposal }),
    );

    await waitFor(() =>
      expect(
        screen.queryByText("Enter a valid answer."),
      ).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.getByRole("dialog", { name: strings.workspace.declarationTitle }),
    ).toBeInTheDocument();
  });

  it("story 3.1: Submit is disabled while offline, with a short reason beside it", async () => {
    mockValidate(() => jsonResponse({ errors: [] }));
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();

    vi.spyOn(window.navigator, "onLine", "get").mockReturnValue(false);
    window.dispatchEvent(new Event("offline"));

    const button = await screen.findByRole("button", {
      name: strings.workspace.submitProposal,
    });
    await waitFor(() =>
      expect(button).toHaveAttribute("aria-disabled", "true"),
    );
    expect(
      screen.getByText(strings.workspace.submitOfflineReason),
    ).toBeInTheDocument();
  });

  it("story 3.1: Submit is disabled and explained while the form is read-only", async () => {
    mockValidate(
      () => jsonResponse({ errors: [] }),
      () => jsonResponse(FIXTURE_DRAFT),
      { holder: "other_session", expires_at: "2026-09-27T09:05:00Z" },
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();

    const button = screen.getByRole("button", {
      name: strings.workspace.submitProposal,
    });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(
      strings.workspace.submitReadOnlyReason,
    );
  });

  it("FORM-213: Submit proposal shows only on page 5, not pages 1-4", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    expect(
      screen.queryByRole("button", { name: strings.workspace.submitProposal }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Product/ }));
    await screen.findByRole("heading", { level: 2, name: "2 · Product" });
    expect(
      screen.queryByRole("button", { name: strings.workspace.submitProposal }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Payment/ }));
    await screen.findByRole("heading", { level: 2, name: "3 · Payment" });
    expect(
      screen.queryByRole("button", { name: strings.workspace.submitProposal }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    expect(
      screen.queryByRole("button", { name: strings.workspace.submitProposal }),
    ).not.toBeInTheDocument();

    await goToLastPage();
    expect(
      screen.getByRole("button", { name: strings.workspace.submitProposal }),
    ).toBeInTheDocument();
  });
});

describe("3.3 Workspace submit flow", () => {
  async function openDeclarationModal() {
    mockSubmit();
    renderWorkspaceWithLocation();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();
    const submitButton = screen.getByRole("button", {
      name: strings.workspace.submitProposal,
    });
    await userEvent.click(submitButton);
    await screen.findByRole("dialog", {
      name: strings.workspace.declarationTitle,
    });
    return submitButton;
  }

  async function openFeedbackModal() {
    const submitButton = await openDeclarationModal();
    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.iAgree }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: strings.workspace.feedbackTitle,
    });
    return { submitButton, dialog };
  }

  it("I agree replaces the declaration modal with the feedback modal, never stacked", async () => {
    await openFeedbackModal();

    expect(screen.getAllByRole("dialog")).toHaveLength(1);
    expect(
      screen.queryByRole("dialog", {
        name: strings.workspace.declarationTitle,
      }),
    ).not.toBeInTheDocument();
  });

  it("Cancel on the declaration modal closes it, returns focus to Submit proposal, and submits nothing", async () => {
    const submitButton = await openDeclarationModal();

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.cancel }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(submitButton).toHaveFocus();
    expect(submitBodies()).toHaveLength(0);
  });

  it("Cancel on the feedback modal closes it, returns focus to Submit proposal, and submits nothing", async () => {
    const { submitButton } = await openFeedbackModal();

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.cancel }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(submitButton).toHaveFocus();
    expect(submitBodies()).toHaveLength(0);
  });

  it("the feedback modal's own Submit proposal stays disabled until a rating is picked", async () => {
    const { dialog } = await openFeedbackModal();

    const dialogSubmit = within(dialog).getByRole("button", {
      name: strings.workspace.submitProposal,
    });
    expect(dialogSubmit).toHaveAttribute("aria-disabled", "true");

    await userEvent.click(
      within(dialog).getByRole("radio", {
        name: strings.workspace.ratingStarLabel(4),
      }),
    );

    expect(dialogSubmit).not.toHaveAttribute("aria-disabled");
  });

  it("submits the declaration and feedback, then navigates to Submitted with the success toast", async () => {
    const { dialog } = await openFeedbackModal();

    await userEvent.click(
      within(dialog).getByRole("radio", {
        name: strings.workspace.ratingStarLabel(4),
      }),
    );
    await userEvent.type(
      within(dialog).getByLabelText(strings.workspace.commentLabel),
      "Helpful",
    );
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.workspace.submitProposal,
      }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `${paths.submitted}|${strings.workspace.submitSuccessToast}`,
      ),
    );
    expect(submitBodies()).toEqual([
      {
        revision: FIXTURE_DRAFT.revision,
        declaration_agreed: true,
        feedback: { rating: 4, comment: "Helpful" },
      },
    ]);
  });

  it("an empty comment is sent as null, never an empty string", async () => {
    const { dialog } = await openFeedbackModal();

    await userEvent.click(
      within(dialog).getByRole("radio", {
        name: strings.workspace.ratingStarLabel(5),
      }),
    );
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.workspace.submitProposal,
      }),
    );

    await waitFor(() => expect(submitBodies()).toHaveLength(1));
    expect(submitBodies()[0]?.feedback).toEqual({ rating: 5, comment: null });
  });

  it("a failed submit with a field problem closes the modals and re-opens the form with it highlighted, exactly like Story 3.1's own validate errors", async () => {
    mockSubmit(() =>
      jsonResponse(
        {
          errors: [
            { field: "C11", code: "required", message: "Answer required" },
          ],
        },
        422,
      ),
    );
    renderWorkspaceWithLocation();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();
    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.submitProposal }),
    );
    await screen.findByRole("dialog", {
      name: strings.workspace.declarationTitle,
    });
    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.iAgree }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: strings.workspace.feedbackTitle,
    });
    await userEvent.click(
      within(dialog).getByRole("radio", {
        name: strings.workspace.ratingStarLabel(4),
      }),
    );

    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.workspace.submitProposal,
      }),
    );

    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByText("Answer required")).toBeInTheDocument();
    // No separate banner: the highlighted problem already says what went wrong (spec AC).
    expect(
      screen.queryByText(strings.workspace.submitFailedMessage),
    ).not.toBeInTheDocument();
    // Never navigated away: the failure keeps her on the workspace, not Submitted.
    expect(screen.getByTestId("location")).toHaveTextContent(
      `${proposalPath(FIXTURE_DRAFT.id)}|`,
    );
  });

  it("a failed submit with a conflict (no field of its own on this page) closes the modals and shows a generic error, staying put", async () => {
    mockSubmit(() =>
      jsonResponse(
        {
          errors: [
            {
              field: "revision",
              code: "stale_revision",
              message: "Reload the draft.",
            },
          ],
        },
        409,
      ),
    );
    renderWorkspaceWithLocation();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();
    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.submitProposal }),
    );
    await screen.findByRole("dialog", {
      name: strings.workspace.declarationTitle,
    });
    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.iAgree }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: strings.workspace.feedbackTitle,
    });
    await userEvent.click(
      within(dialog).getByRole("radio", {
        name: strings.workspace.ratingStarLabel(4),
      }),
    );

    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.workspace.submitProposal,
      }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      await screen.findByText(strings.workspace.submitFailedMessage),
    ).toBeInTheDocument();
    // Stays on page 5 (LAST_PAGE): "revision" has no schema field/page to jump to.
    expect(
      screen.getByRole("heading", {
        level: 2,
        name: "5 · Health & lifestyle",
      }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(
      `${proposalPath(FIXTURE_DRAFT.id)}|`,
    );
  });
});

describe("FORM-213 numeric fields", () => {
  it("rejects letters typed into an integer field (N4), keeping only its digits", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const row = screen
      .getByText("How many dependents?")
      .closest(".ws-tbl__row") as HTMLElement;
    const input = within(row).getByRole("textbox");

    await userEvent.clear(input);
    await userEvent.type(input, "5a3b");

    expect(input).toHaveValue("53");
    expect(
      screen.queryByText(strings.workspace.numberFieldInvalidMessage),
    ).not.toBeInTheDocument();
  });

  it("rejects letters typed into a unit-mapped number field (H1, height)", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();
    const row = screen
      .getByText("Height (cm)")
      .closest(".ws-tbl__row") as HTMLElement;
    const input = within(row).getByRole("textbox");

    await userEvent.clear(input);
    await userEvent.type(input, "abc");

    expect(input).toHaveValue("");
  });

  it("a pasted non-number shows the inline amber error and sends no PATCH", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();
    const row = screen
      .getByText("Height (cm)")
      .closest(".ws-tbl__row") as HTMLElement;
    const input = within(row).getByRole("textbox");

    await userEvent.clear(input);
    await userEvent.click(input);
    await userEvent.paste("abc");

    const message = await screen.findByText(
      strings.workspace.numberFieldInvalidMessage,
    );
    expect(message.closest(".ws-tbl__cell")).toHaveClass(
      "ws-tbl__cell--problem",
    );
    expect(
      message.closest(".ws-tbl__cell")?.querySelector(".ws-problem__badge"),
    ).not.toBeNull();
    expect(input).toHaveValue("abc");

    await userEvent.tab(); // blur: still invalid, must not commit

    expect(patchBodies()).toHaveLength(0);
  });

  it("fixing a pasted non-number clears the error and commits normally on blur", async () => {
    mockPatch(() =>
      jsonResponse({
        ...FIXTURE_DRAFT,
        revision: 4,
        answers: { ...FIXTURE_DRAFT.answers, H1: 170 },
      }),
    );
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await goToLastPage();
    const row = screen
      .getByText("Height (cm)")
      .closest(".ws-tbl__row") as HTMLElement;
    const input = within(row).getByRole("textbox");

    await userEvent.clear(input);
    await userEvent.click(input);
    await userEvent.paste("abc");
    await screen.findByText(strings.workspace.numberFieldInvalidMessage);

    await userEvent.clear(input);
    await userEvent.type(input, "170");
    await waitFor(() =>
      expect(
        screen.queryByText(strings.workspace.numberFieldInvalidMessage),
      ).not.toBeInTheDocument(),
    );
    await userEvent.tab();

    expect(patchBodies()).toEqual([{ revision: 3, answers: { H1: 170 } }]);
  });
});

describe("4.4 Workspace edit lock", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  function findRow(labelText: string): HTMLElement {
    return screen.getByText(labelText).closest(".ws-tbl__row") as HTMLElement;
  }

  it("story 4.4: acquires the lock on mount, with no take-over", async () => {
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(lockBodies()).toEqual([{ take_over: false }]);
    expect(
      screen.queryByText(strings.workspace.lockedElsewhereNote, LOCK_NOTE),
    ).not.toBeInTheDocument();
  });

  it("story 4.4: another session's live lock makes every answer read-only, with the note", async () => {
    mockApi({
      lock: { holder: "other_session", expires_at: "2026-09-27T09:01:00Z" },
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(
      screen.getByText(strings.workspace.lockedElsewhereNote, LOCK_NOTE),
    ).toBeInTheDocument();
    // A segmented pill (Yes/No) goes disabled.
    const dependentsRow = findRow("Should the policy cover your dependents?");
    expect(
      within(dependentsRow).getByRole("button", { name: "Yes" }),
    ).toBeDisabled();
    // A plain text input goes readOnly, not disabled (it still needs to show its value).
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    expect(within(findRow("First name")).getByRole("textbox")).toHaveAttribute(
      "readonly",
    );
    // The page menu itself still works while read-only (EXPERIENCE.md "Edit lock held elsewhere").
    await userEvent.click(screen.getByRole("button", { name: /Needs/ }));
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
  });

  it("story 4.4: Edit here instead takes over the lock and the form becomes editable", async () => {
    let lockCall = 0;
    mockLock(() => {
      lockCall += 1;
      return jsonResponse(
        lockCall === 1
          ? { holder: "other_session", expires_at: "2026-09-27T09:01:00Z" }
          : { holder: "you", expires_at: "2026-09-27T09:02:00Z" },
      );
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const button = screen.getByRole("button", {
      name: strings.workspace.editHereInstead,
    });
    expect(button).not.toHaveAttribute("aria-disabled");

    await userEvent.click(button);

    await waitFor(() =>
      expect(
        screen.queryByText(strings.workspace.lockedElsewhereNote, LOCK_NOTE),
      ).not.toBeInTheDocument(),
    );
    expect(lockBodies()).toEqual([{ take_over: false }, { take_over: true }]);
    const dependentsRow = findRow("Should the policy cover your dependents?");
    expect(
      within(dependentsRow).getByRole("button", { name: "Yes" }),
    ).not.toBeDisabled();
  });

  it("story 4.4: Edit here instead is disabled and explained while the AI holds the lock", async () => {
    mockApi({ lock: { holder: "ai", expires_at: "2026-09-27T09:05:00Z" } });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    const button = screen.getByRole("button", {
      name: strings.workspace.editHereInstead,
    });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleDescription(
      strings.workspace.editHereInsteadDisabledReason,
    );

    await userEvent.click(button);
    expect(lockBodies()).toEqual([{ take_over: false }]); // the click did nothing
  });

  it("story 4.4: renews the lock every 20s, well inside its 60s expiry", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    expect(lockBodies()).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(20_000);
    expect(lockBodies()).toHaveLength(2);

    await vi.advanceTimersByTimeAsync(20_000);
    expect(lockBodies()).toHaveLength(3);
    expect(lockBodies()).toEqual([
      { take_over: false },
      { take_over: false },
      { take_over: false },
    ]);
  });

  it("story 4.4: losing the lock mid-edit keeps the unsaved value with a not-saved note, never Saved, and goes read-only", async () => {
    let lockCall = 0;
    const NOT_HELD_MESSAGE =
      "This proposal is being edited in another window. Reload to take over.";
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === LOCK_URL && init?.method === "POST") {
        lockCall += 1;
        return jsonResponse(
          lockCall === 1
            ? LOCK_YOU
            : { holder: "other_session", expires_at: "2026-09-27T09:01:00Z" },
        );
      }
      if (url === ANSWERS_URL && init?.method === "PATCH") {
        return jsonResponse(
          {
            errors: [
              {
                field: "lock",
                code: "lock_not_held",
                message: NOT_HELD_MESSAGE,
              },
            ],
          },
          409,
        );
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}`) {
        return jsonResponse(FIXTURE_DRAFT);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/schema`) {
        return jsonResponse(FIXTURE_SCHEMA);
      }
      if (url === `/api/proposals/${FIXTURE_DRAFT.id}/chat`) {
        return jsonResponse({ messages: [] });
      }
      return jsonResponse({ errors: [] }, 404);
    });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    const row = findRow("Should the policy cover your dependents?");

    await userEvent.click(within(row).getByRole("button", { name: "No" }));

    const message = await screen.findByText(NOT_HELD_MESSAGE);
    expect(message.closest(".ws-tbl__cell")).toHaveClass(
      "ws-tbl__cell--problem",
    );
    expect(screen.queryByText(strings.workspace.saved)).not.toBeInTheDocument();
    // The typed (unsaved) value stays on screen.
    expect(within(row).getByRole("button", { name: "No" })).toHaveClass(
      "ws-seg__option--on",
    );
    // The lock refresh this triggered reports the true holder, and the form goes read-only.
    await screen.findByText(strings.workspace.lockedElsewhereNote, LOCK_NOTE);
    expect(within(row).getByRole("button", { name: "No" })).toBeDisabled();
  });
});

describe("3.2 Workspace submitted", () => {
  function findRow(labelText: string): HTMLElement {
    return screen.getByText(labelText).closest(".ws-tbl__row") as HTMLElement;
  }

  it("story 3.2: shows the submitted strip with its date, and hides Submit and chat", async () => {
    mockApi({ draft: FIXTURE_DRAFT_SUBMITTED });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(
      screen.getByText(strings.workspace.submittedOn("25 Sep 2026")),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: strings.workspace.submitProposal }),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".chat-panel")).not.toBeInTheDocument();
    expect(
      screen.queryByText(strings.workspace.lockedElsewhereNote, LOCK_NOTE),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(strings.workspace.saved)).not.toBeInTheDocument();
  });

  it("FORM-218: shows the customer number in the submitted strip when the draft carries one", async () => {
    mockApi({ draft: FIXTURE_DRAFT_SUBMITTED_WITH_CUSTOMER_NUMBER });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(
      screen.getByText(strings.workspace.submittedOn("25 Sep 2026")),
    ).toBeInTheDocument();
    expect(
      screen.getByText(strings.customerNumberLabel("CUS-10023")),
    ).toBeInTheDocument();
  });

  it("FORM-218: shows no customer number in the submitted strip when the draft has none", async () => {
    mockApi({ draft: FIXTURE_DRAFT_SUBMITTED });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(screen.queryByText(/^Customer /)).not.toBeInTheDocument();
  });

  it("story 3.2: every page is read-only, whoever (if anyone) holds the edit lock", async () => {
    mockApi({ draft: FIXTURE_DRAFT_SUBMITTED, lock: LOCK_YOU });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    // A segmented pill (Yes/No) goes disabled, even though this tab's own session holds the lock.
    const dependentsRow = findRow("Should the policy cover your dependents?");
    expect(
      within(dependentsRow).getByRole("button", { name: "Yes" }),
    ).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    expect(within(findRow("First name")).getByRole("textbox")).toHaveAttribute(
      "readonly",
    );
  });

  it("story 3.2: the page menu still switches pages on a submitted proposal", async () => {
    mockApi({ draft: FIXTURE_DRAFT_SUBMITTED });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });
    await userEvent.click(screen.getByRole("button", { name: /Needs/ }));
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
  });

  it("story 3.2: a blur on a submitted proposal never patches", async () => {
    mockApi({ draft: FIXTURE_DRAFT_SUBMITTED });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });
    await userEvent.click(screen.getByRole("button", { name: /Particulars/ }));
    await screen.findByRole("heading", { level: 2, name: "4 · Particulars" });

    await userEvent.click(within(findRow("First name")).getByRole("textbox"));
    await userEvent.tab();

    expect(patchBodies()).toEqual([]);
  });
});

// Story FORM-227: the workspace's own delete-draft button and shared confirmation modal.
describe("FORM-227 Workspace delete draft", () => {
  it("shows a delete button, hidden once submitted", async () => {
    mockApi({ draft: FIXTURE_DRAFT });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(
      screen.getByRole("button", { name: strings.workspace.deleteDraft }),
    ).toBeInTheDocument();
  });

  it("hides the delete button once the proposal is submitted", async () => {
    mockApi({ draft: FIXTURE_DRAFT_SUBMITTED });
    renderWorkspace();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    expect(
      screen.queryByRole("button", { name: strings.workspace.deleteDraft }),
    ).not.toBeInTheDocument();
  });

  it("opens the confirm modal naming the draft; Cancel leaves everything unchanged", async () => {
    mockDelete();
    renderWorkspaceWithLocation();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.deleteDraft }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: strings.deleteDraftModal.title(FIXTURE_DRAFT.display_name),
    });
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.deleteDraftModal.cancel,
      }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(
      `${proposalPath(FIXTURE_DRAFT.id)}|`,
    );
    const deletes = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input) === DELETE_URL && init?.method === "DELETE",
    );
    expect(deletes).toHaveLength(0);
  });

  it("deletes the draft on confirm, then navigates to Drafts with the toast", async () => {
    mockDelete();
    renderWorkspaceWithLocation();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.deleteDraft }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.deleteDraftModal.confirm,
      }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent(
        `${paths.drafts}|${strings.deleteDraftModal.toast}`,
      ),
    );
    const deletes = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input) === DELETE_URL && init?.method === "DELETE",
    );
    expect(deletes).toHaveLength(1);
  });

  it("keeps her on the workspace with an error if the delete fails", async () => {
    mockDelete(() => jsonResponse({ errors: [] }, 500));
    renderWorkspaceWithLocation();
    await screen.findByRole("heading", { level: 2, name: "1 · Needs" });

    await userEvent.click(
      screen.getByRole("button", { name: strings.workspace.deleteDraft }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.deleteDraftModal.confirm,
      }),
    );

    expect(
      await screen.findByText(strings.deleteDraftModal.failedMessage),
    ).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByTestId("location")).toHaveTextContent(
      `${proposalPath(FIXTURE_DRAFT.id)}|`,
    );
  });
});
