import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { strings } from "../strings";
import { NEW_DRAFT } from "./proposals.fixtures";
import { ProposalsPage } from "./ProposalsPage";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

const DRAFT_ROW = {
  id: "11111111-1111-4111-8111-111111111111",
  display_name: "Untitled_Proposal_001",
  status: "draft",
  created_at: "2026-09-20T09:00:00Z",
  submitted_at: null,
};

const NAMED_ROW = {
  id: "22222222-2222-4222-8222-222222222222",
  display_name: "Ally_Macbeal_Proposal_002",
  status: "draft",
  created_at: "2026-09-25T09:00:00Z",
  submitted_at: null,
};

/** Answers `GET /api/proposals?status=...` with `rows` and `POST /api/proposals` with a new draft. */
function mockApi(rows: unknown[]) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === "/api/proposals" && init?.method === "POST") {
      return jsonResponse(NEW_DRAFT, 201);
    }
    if (url.startsWith("/api/proposals?status=")) {
      return jsonResponse(rows);
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

/** Answers `GET /api/proposals?status=...` with `rows` and `DELETE /api/proposals/:id` with
 * `respond` (default: a clean 204) -- for the FORM-227 delete tests below. */
function mockApiWithDelete(
  rows: unknown[],
  respond: (id: string) => Response | Promise<Response> = () =>
    new Response(null, { status: 204 }),
) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url.startsWith("/api/proposals/") && init?.method === "DELETE") {
      return respond(url.slice("/api/proposals/".length));
    }
    if (url.startsWith("/api/proposals?status=")) {
      return jsonResponse(rows);
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

function CurrentPath() {
  return <output data-testid="path">{useLocation().pathname}</output>;
}

function renderPage(status: "draft" | "submitted" = "draft") {
  return render(
    <MemoryRouter initialEntries={["/proposals"]}>
      <ProposalsPage status={status} />
      <CurrentPath />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  mockApi([]);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("1.8 ProposalsPage", () => {
  it("shows skeleton rows while loading, with the title, tabs and button at once", async () => {
    fetchMock.mockImplementation(() => new Promise<Response>(() => {}));
    renderPage("draft");

    expect(
      screen.getByRole("heading", { level: 1, name: strings.proposals.title }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: strings.proposals.drafts }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: strings.proposals.newProposal }),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("skeleton-row")).toHaveLength(3);
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("lists the rows given, each with its name, status chip, date and chevron", async () => {
    mockApi([NAMED_ROW, DRAFT_ROW]);
    renderPage("draft");

    const rows = await screen.findAllByRole("link", {
      name: /Macbeal|Untitled/,
    });
    expect(rows).toHaveLength(2);
    const [namedRow, untitledRow] = rows as [HTMLElement, HTMLElement];
    expect(namedRow).toHaveTextContent("Ally_Macbeal_Proposal_002");
    expect(namedRow).toHaveTextContent(strings.proposals.statusDraft);
    expect(namedRow).toHaveTextContent("Created 25 Sep 2026");
    expect(untitledRow).toHaveTextContent("Untitled_Proposal_001");
    expect(untitledRow).toHaveTextContent("Created 20 Sep 2026");
    expect(namedRow.querySelector(".proposals-row__name--untitled")).toBeNull();
    expect(
      untitledRow.querySelector(".proposals-row__name--untitled"),
    ).not.toBeNull();
    expect(namedRow).toHaveAttribute(
      "href",
      "/proposals/22222222-2222-4222-8222-222222222222",
    );
    expect(screen.queryAllByTestId("skeleton-row")).toHaveLength(0);
  });

  it("shows submitted rows with the Submitted date prefix, formatted from submitted_at not created_at", async () => {
    // created_at and submitted_at deliberately differ, so this only passes if the Submitted tab
    // reads submitted_at (Story 3.2 fixes a bug where it always formatted created_at).
    mockApi([
      {
        ...NAMED_ROW,
        status: "submitted",
        submitted_at: "2026-09-27T09:00:00Z",
      },
    ]);
    renderPage("submitted");

    const row = await screen.findByRole("link", { name: /Macbeal/ });
    expect(row).toHaveTextContent(strings.proposals.statusSubmitted);
    expect(row).toHaveTextContent("Submitted 27 Sep 2026");
    expect(row).not.toHaveTextContent("25 Sep 2026");
  });

  it("FORM-218: shows the customer number on a submitted row that carries one", async () => {
    mockApi([
      {
        ...NAMED_ROW,
        status: "submitted",
        submitted_at: "2026-09-27T09:00:00Z",
        customer_number: "CUS-10023",
      },
    ]);
    renderPage("submitted");

    const row = await screen.findByRole("link", { name: /Macbeal/ });
    expect(row).toHaveTextContent(strings.customerNumberLabel("CUS-10023"));
  });

  it("FORM-218: shows no customer number on a submitted row that has none", async () => {
    mockApi([
      {
        ...NAMED_ROW,
        status: "submitted",
        submitted_at: "2026-09-27T09:00:00Z",
      },
    ]);
    renderPage("submitted");

    const row = await screen.findByRole("link", { name: /Macbeal/ });
    expect(row).not.toHaveTextContent("Customer ");
  });

  it("shows a centred empty tile with New proposal for an agent with no drafts", async () => {
    mockApi([]);
    renderPage("draft");

    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: strings.proposals.emptyDrafts,
      }),
    ).toBeInTheDocument();
    // The header row's own button gives way to the one, centred copy (mockups/key-proposals.html C).
    expect(
      screen.getAllByRole("button", { name: strings.proposals.newProposal }),
    ).toHaveLength(1);
  });

  it("shows Submitted's empty text with no create button in the tile, but keeps the header one", async () => {
    mockApi([]);
    renderPage("submitted");

    expect(
      await screen.findByText(strings.proposals.emptySubmitted),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", {
        level: 2,
        name: strings.proposals.emptyDrafts,
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: strings.proposals.newProposal }),
    ).toHaveLength(1);
  });

  it("creates a draft and navigates to it with its display name in state", async () => {
    mockApi([]);
    renderPage("draft");
    await screen.findByRole("heading", { level: 2 });

    await userEvent.click(
      screen.getByRole("button", { name: strings.proposals.newProposal }),
    );

    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent(
        "/proposals/33333333-3333-4333-8333-333333333333",
      ),
    );
    const posts = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input) === "/api/proposals" && init?.method === "POST",
    );
    expect(posts).toHaveLength(1);
  });

  it("disables the button while creating so a double click makes only one draft", async () => {
    let resolvePost: (() => void) | undefined;
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/proposals" && init?.method === "POST") {
        await new Promise<void>((resolve) => (resolvePost = resolve));
        return jsonResponse(NEW_DRAFT, 201);
      }
      return jsonResponse([]);
    });
    renderPage("draft");
    await screen.findByRole("heading", { level: 2 });

    const button = screen.getByRole("button", {
      name: strings.proposals.newProposal,
    });
    await userEvent.click(button);
    expect(button).toHaveAttribute("aria-disabled", "true");
    // A second activation while disabled must not start a second request.
    await userEvent.click(button);
    resolvePost?.();

    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent(
        "/proposals/33333333-3333-4333-8333-333333333333",
      ),
    );
    const posts = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input) === "/api/proposals" && init?.method === "POST",
    );
    expect(posts).toHaveLength(1);
  });

  it("re-enables the button if creating the draft fails, without navigating", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/proposals" && init?.method === "POST") {
        return jsonResponse({ errors: [] }, 500);
      }
      return jsonResponse([]);
    });
    renderPage("draft");
    await screen.findByRole("heading", { level: 2 });

    const button = screen.getByRole("button", {
      name: strings.proposals.newProposal,
    });
    await userEvent.click(button);

    await waitFor(() => expect(button).not.toHaveAttribute("aria-disabled"));
    expect(screen.getByTestId("path")).toHaveTextContent("/proposals");
  });

  it("shows an error message if the list can't be loaded", async () => {
    fetchMock.mockResolvedValue(new Response("", { status: 500 }));
    renderPage("draft");

    expect(
      await screen.findByText(strings.proposals.loadError),
    ).toBeInTheDocument();
  });
});

// Story 3.3/FORM-21: the success toast a submit's own navigate() carries in location.state
// (EXPERIENCE.md "After submit ... shows the toast").
describe("3.3 ProposalsPage success toast", () => {
  const TOAST_MESSAGE = "Proposal submitted. Thank you for your feedback.";

  it("shows the toast carried in location.state", async () => {
    mockApi([]);
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/proposals/submitted", state: { toast: TOAST_MESSAGE } },
        ]}
      >
        <ProposalsPage status="submitted" />
      </MemoryRouter>,
    );

    expect(await screen.findByText(TOAST_MESSAGE)).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("shows no toast without one in location.state", async () => {
    mockApi([]);
    renderPage("submitted");
    await screen.findByRole("heading", { level: 2 });

    // Not queryByRole("status"): renderPage's own CurrentPath debug helper is an <output>, which
    // carries that implicit role too -- this checks for the toast's own text instead.
    expect(screen.queryByText(TOAST_MESSAGE)).not.toBeInTheDocument();
  });

  it("clears the toast from history so a reload of the same entry doesn't replay it", async () => {
    mockApi([]);
    render(
      <MemoryRouter
        initialEntries={[
          { pathname: "/proposals/submitted", state: { toast: TOAST_MESSAGE } },
        ]}
      >
        <ProposalsPage status="submitted" />
        <CurrentPath />
      </MemoryRouter>,
    );
    await screen.findByText(TOAST_MESSAGE);

    // The replace() swaps location.state to null without changing the pathname she's on.
    expect(screen.getByTestId("path")).toHaveTextContent(
      "/proposals/submitted",
    );
  });
});

// Story FORM-227: delete a draft, from a Drafts row (spec Intent, AC).
describe("FORM-227 delete a draft", () => {
  it("shows a delete button on each draft row, never on a submitted one", async () => {
    mockApiWithDelete([NAMED_ROW]);
    const draft = renderPage("draft");
    await screen.findByRole("link", { name: /Macbeal/ });

    expect(
      screen.getByRole("button", {
        name: strings.proposals.deleteRowLabel(NAMED_ROW.display_name),
      }),
    ).toBeInTheDocument();
    // Unmount before rendering the Submitted tab: two renders side by side in the same document
    // would still show the Drafts tab's own delete button, which is not what the second half of
    // this test means to check.
    draft.unmount();

    mockApiWithDelete([
      {
        ...NAMED_ROW,
        status: "submitted",
        submitted_at: "2026-09-27T09:00:00Z",
      },
    ]);
    renderPage("submitted");
    await screen.findByRole("link", { name: /Macbeal/ });

    expect(
      screen.queryByRole("button", {
        name: strings.proposals.deleteRowLabel(NAMED_ROW.display_name),
      }),
    ).not.toBeInTheDocument();
  });

  it("opens the confirm modal naming the row; Cancel leaves the row and list unchanged", async () => {
    mockApiWithDelete([NAMED_ROW]);
    renderPage("draft");
    await screen.findByRole("link", { name: /Macbeal/ });

    await userEvent.click(
      screen.getByRole("button", {
        name: strings.proposals.deleteRowLabel(NAMED_ROW.display_name),
      }),
    );
    const dialog = await screen.findByRole("dialog", {
      name: strings.deleteDraftModal.title(NAMED_ROW.display_name),
    });
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.deleteDraftModal.cancel,
      }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Macbeal/ })).toBeInTheDocument();
    const deletes = fetchMock.mock.calls.filter(
      ([, init]) => init?.method === "DELETE",
    );
    expect(deletes).toHaveLength(0);
  });

  it("Escape closes the modal without deleting, same as Cancel", async () => {
    mockApiWithDelete([NAMED_ROW]);
    renderPage("draft");
    await screen.findByRole("link", { name: /Macbeal/ });

    await userEvent.click(
      screen.getByRole("button", {
        name: strings.proposals.deleteRowLabel(NAMED_ROW.display_name),
      }),
    );
    const dialog = await screen.findByRole("dialog");
    dialog.focus();
    await userEvent.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Macbeal/ })).toBeInTheDocument();
  });

  it("deletes the row on confirm, removes it from the list and shows the toast", async () => {
    mockApiWithDelete([NAMED_ROW]);
    renderPage("draft");
    await screen.findByRole("link", { name: /Macbeal/ });

    await userEvent.click(
      screen.getByRole("button", {
        name: strings.proposals.deleteRowLabel(NAMED_ROW.display_name),
      }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.deleteDraftModal.confirm,
      }),
    );

    await waitFor(() =>
      expect(
        screen.queryByRole("link", { name: /Macbeal/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByText(strings.deleteDraftModal.toast),
    ).toBeInTheDocument();
    const deletes = fetchMock.mock.calls.filter(
      ([input, init]) =>
        String(input) === `/api/proposals/${NAMED_ROW.id}` &&
        init?.method === "DELETE",
    );
    expect(deletes).toHaveLength(1);
  });

  it("shows an error and keeps the row if the delete fails", async () => {
    mockApiWithDelete([NAMED_ROW], () => jsonResponse({ errors: [] }, 500));
    renderPage("draft");
    await screen.findByRole("link", { name: /Macbeal/ });

    await userEvent.click(
      screen.getByRole("button", {
        name: strings.proposals.deleteRowLabel(NAMED_ROW.display_name),
      }),
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
    expect(screen.getByRole("link", { name: /Macbeal/ })).toBeInTheDocument();
  });

  it("FORM-232: says the draft is open elsewhere when another session's lock refuses it", async () => {
    mockApiWithDelete([NAMED_ROW], () =>
      jsonResponse(
        {
          errors: [
            { field: "lock", code: "lock_not_held", message: "Locked." },
          ],
        },
        409,
      ),
    );
    renderPage("draft");
    await screen.findByRole("link", { name: /Macbeal/ });

    await userEvent.click(
      screen.getByRole("button", {
        name: strings.proposals.deleteRowLabel(NAMED_ROW.display_name),
      }),
    );
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(
      within(dialog).getByRole("button", {
        name: strings.deleteDraftModal.confirm,
      }),
    );

    expect(
      await screen.findByText(strings.deleteDraftModal.lockedMessage),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Macbeal/ })).toBeInTheDocument();
  });
});
