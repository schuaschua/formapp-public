import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { NEW_DRAFT } from "../pages/proposals.fixtures";
import {
  FIXTURE_DRAFT,
  FIXTURE_SCHEMA,
} from "../pages/workspace/workspace.fixtures";
import { strings } from "../strings";
import { App, AppShell } from "./App";

// A synthetic signed-in agent (security.md rule 1).
const ALICE = { name: "Alice Synthetic", first_name: "Alice" };
const TITLE = strings.proposals.title;

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

type ApiState = {
  signedIn: boolean;
  drafts: unknown[];
  submitted: unknown[];
  /** Draft wire bodies (Story 1.9), keyed by id; `GET /api/proposals/:id` and its `/schema` 404
   * for any id not listed here. */
  draftsById: Record<string, unknown>;
  schemasById: Record<string, unknown>;
};

/**
 * A route-aware fetch mock: /api/me, /api/proposals?status=draft and ?status=submitted each get
 * their own answer, so a page's own fetch never sees another route's body. `failMeOnceWith` overrides
 * exactly the next /api/me call (by URL, not call order, since a navigation can fire both an /api/me
 * recheck and a proposals fetch at once).
 */
function mockApi(overrides: Partial<ApiState> = {}) {
  const state: ApiState = {
    signedIn: true,
    drafts: [],
    submitted: [],
    draftsById: {},
    schemasById: {},
    ...overrides,
  };
  let meOverrideStatus: number | null = null;
  fetchMock.mockImplementation(async (input) => {
    const url = String(input);
    if (url === "/api/me") {
      if (meOverrideStatus !== null) {
        const status = meOverrideStatus;
        meOverrideStatus = null;
        return jsonResponse({ errors: [] }, status);
      }
      return state.signedIn
        ? jsonResponse(ALICE)
        : jsonResponse({ errors: [] }, 401);
    }
    if (url.startsWith("/api/proposals?status=draft")) {
      return jsonResponse(state.drafts);
    }
    if (url.startsWith("/api/proposals?status=submitted")) {
      return jsonResponse(state.submitted);
    }
    const schemaMatch = /^\/api\/proposals\/([^/]+)\/schema$/.exec(url);
    if (schemaMatch) {
      const id = schemaMatch[1] as string;
      return id in state.schemasById
        ? jsonResponse(state.schemasById[id])
        : jsonResponse({ errors: [] }, 404);
    }
    const draftMatch = /^\/api\/proposals\/([^/]+)$/.exec(url);
    if (draftMatch) {
      const id = draftMatch[1] as string;
      return id in state.draftsById
        ? jsonResponse(state.draftsById[id])
        : jsonResponse({ errors: [] }, 404);
    }
    return jsonResponse({ errors: [] }, 404);
  });
  return {
    state,
    failMeOnceWith(status: number) {
      meOverrideStatus = status;
    },
  };
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  mockApi();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function CurrentPath() {
  return (
    <>
      <output data-testid="path">{useLocation().pathname}</output>
      <Link to="/proposals/submitted">test: go to Submitted</Link>
    </>
  );
}

async function goToSubmitted() {
  await userEvent.click(
    screen.getByRole("link", { name: "test: go to Submitted" }),
  );
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <CurrentPath />
    </MemoryRouter>,
  );
}

describe("1.4 app shell and routes", () => {
  it("story 1.9: /proposals/:id renders the workspace inside the shell", async () => {
    mockApi({
      draftsById: { [FIXTURE_DRAFT.id]: FIXTURE_DRAFT },
      schemasById: { [FIXTURE_DRAFT.id]: FIXTURE_SCHEMA },
    });
    renderAt(`/proposals/${FIXTURE_DRAFT.id}`);

    expect(
      await screen.findByRole("heading", { level: 2, name: "1 · Needs" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("banner")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("banner")).toHaveTextContent(
        `${strings.proposals.drafts} / Ally_Macbeal_Proposal_001`,
      ),
    );
    expect(screen.getByRole("main")).toContainElement(
      screen.getByRole("heading", { level: 2 }),
    );
    expect(screen.getByTestId("glow-canvas")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(screen.getByTestId("path")).toHaveTextContent(
      `/proposals/${FIXTURE_DRAFT.id}`,
    );
  });

  it.each(["/proposals", "/proposals/submitted"])(
    "story 1.8: %s renders My proposals inside the shell",
    async (path) => {
      renderAt(path);

      expect(
        await screen.findByRole("heading", { level: 1, name: TITLE }),
      ).toBeInTheDocument();
      expect(screen.getByRole("banner")).toBeInTheDocument();
      expect(screen.getByRole("main")).toContainElement(
        screen.getByRole("heading", { level: 1 }),
      );
      expect(screen.getByTestId("glow-canvas")).toHaveAttribute(
        "aria-hidden",
        "true",
      );
      expect(screen.getByTestId("path")).toHaveTextContent(path);
    },
  );

  it.each(["/nope", "/proposals/42/extra", "/welcome"])(
    "story 1.4: unknown path %s shows the Drafts route",
    async (path) => {
      renderAt(path);

      expect(
        await screen.findByRole("heading", { level: 1, name: TITLE }),
      ).toBeInTheDocument();
      expect(screen.getByTestId("path")).toHaveTextContent("/proposals");
    },
  );

  it.each([
    ["/proposals", "Drafts - formapp"],
    ["/proposals/submitted", "Submitted - formapp"],
    ["/nope", "Drafts - formapp"],
  ])("story 1.4: %s sets the tab title %j", async (path, title) => {
    renderAt(path);

    await waitFor(() => expect(document.title).toBe(title));
  });

  it("story 1.9: a draft's tab title is its display name", async () => {
    mockApi({
      draftsById: { [FIXTURE_DRAFT.id]: FIXTURE_DRAFT },
      schemasById: { [FIXTURE_DRAFT.id]: FIXTURE_SCHEMA },
    });
    renderAt(`/proposals/${FIXTURE_DRAFT.id}`);

    await waitFor(() =>
      expect(document.title).toBe("Ally_Macbeal_Proposal_001 - formapp"),
    );
  });

  it("story 1.4: the skip link moves focus to the main area", async () => {
    renderAt("/proposals");
    await screen.findByRole("heading", { level: 1 });

    await userEvent.tab();
    const skip = screen.getByRole("link", { name: strings.skipToMain });
    expect(skip).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(screen.getByRole("main")).toHaveFocus();
    expect(screen.getByTestId("path")).toHaveTextContent("/proposals");
  });

  it("story 1.4: the logo links to Drafts", async () => {
    renderAt("/proposals/42");

    expect(
      await screen.findByRole("link", { name: strings.appName }),
    ).toHaveAttribute("href", "/proposals");
  });

  it("story 1.4: the header slot shows what a page puts in it", () => {
    render(
      <MemoryRouter>
        <AppShell header={<span>Drafts / Ally_Macbeal_Proposal_001</span>}>
          <p>Body</p>
        </AppShell>
      </MemoryRouter>,
    );

    expect(screen.getByRole("banner")).toHaveTextContent(
      "Drafts / Ally_Macbeal_Proposal_001",
    );
    expect(screen.getByRole("main")).toHaveTextContent("Body");
  });
});

describe("1.6 sign-in routing", () => {
  it("story 1.6: a signed-out visitor at / sees the Welcome page without the shell header", async () => {
    mockApi({ signedIn: false });
    renderAt("/");

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: strings.welcome.title,
      }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("banner")).not.toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent(/^\/$/);
    expect(document.title).toBe("formapp");
  });

  it("story 1.6: a signed-in user at / goes to My proposals › Drafts", async () => {
    renderAt("/");

    expect(
      await screen.findByRole("heading", { level: 1, name: TITLE }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent("/proposals");
  });

  it.each(["/proposals", "/proposals/submitted", "/proposals/42", "/nope"])(
    "story 1.6: a signed-out visitor at %s goes to the Welcome page",
    async (path) => {
      mockApi({ signedIn: false });
      renderAt(path);

      expect(
        await screen.findByRole("link", { name: strings.welcome.signIn }),
      ).toBeInTheDocument();
      expect(screen.getByTestId("path")).toHaveTextContent(/^\/$/);
    },
  );

  it("story 1.6: nothing renders until /api/me answers, and no spinner", async () => {
    let answer: (response: Response) => void = () => {};
    fetchMock.mockImplementation(
      () => new Promise<Response>((resolve) => (answer = resolve)),
    );
    renderAt("/proposals");

    expect(screen.queryByRole("heading")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
    expect(screen.queryByRole("main")).not.toBeInTheDocument();

    await act(async () => answer(new Response(JSON.stringify(ALICE))));
    expect(
      await screen.findByRole("heading", { level: 1, name: TITLE }),
    ).toBeInTheDocument();
  });

  it("story 1.6: the header shows her avatar and first name once signed in", async () => {
    renderAt("/proposals");

    const avatar = await screen.findByRole("button", {
      name: strings.account.buttonLabel("Alice"),
    });
    expect(screen.getByRole("banner")).toContainElement(avatar);
    expect(avatar).toHaveTextContent("Alice");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/me");
  });

  it("story 1.6: when the session expires, the next navigation lands on Welcome", async () => {
    const api = mockApi();
    renderAt("/proposals");
    await screen.findByRole("heading", { level: 1, name: TITLE });

    api.state.signedIn = false;
    await goToSubmitted();

    expect(
      await screen.findByRole("link", { name: strings.welcome.signIn }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent(/^\/$/);
  });

  it("story 1.6: a failed first check shows Welcome; a failed later check keeps her signed in", async () => {
    // Offline for every check of the first render: the redirect to Welcome is a navigation, which
    // checks again, and a one-off rejection would let that second check sign her back in.
    fetchMock.mockRejectedValue(new TypeError("offline"));
    const { unmount } = renderAt("/proposals");
    expect(
      await screen.findByRole("link", { name: strings.welcome.signIn }),
    ).toBeInTheDocument();
    unmount();

    const api = mockApi();
    renderAt("/proposals");
    await screen.findByRole("heading", { level: 1, name: TITLE });
    api.failMeOnceWith(503);
    await goToSubmitted();

    expect(
      await screen.findByText(strings.proposals.emptySubmitted),
    ).toBeInTheDocument();
    expect(screen.getByTestId("path")).toHaveTextContent(
      "/proposals/submitted",
    );
  });
});

describe("1.8 breadcrumb after New proposal", () => {
  it("story 1.8: creating a draft opens it with a Drafts / <name> breadcrumb", async () => {
    fetchMock.mockImplementation(async (input, init) => {
      const url = String(input);
      if (url === "/api/me") return jsonResponse(ALICE);
      if (url === "/api/proposals" && init?.method === "POST") {
        return jsonResponse(NEW_DRAFT, 201);
      }
      if (url.startsWith("/api/proposals?status=")) return jsonResponse([]);
      // Story 1.9: the workspace re-fetches the draft and its schema once it opens, rather than
      // trusting the POST response or `location.state` (spec assumption "Breadcrumb on open").
      if (url === `/api/proposals/${NEW_DRAFT.id}`)
        return jsonResponse(NEW_DRAFT);
      if (url === `/api/proposals/${NEW_DRAFT.id}/schema`) {
        return jsonResponse(FIXTURE_SCHEMA);
      }
      return jsonResponse({ errors: [] }, 404);
    });
    renderAt("/proposals");
    await screen.findByRole("heading", { level: 2 }); // the empty-Drafts tile has loaded

    await userEvent.click(
      screen.getByRole("button", { name: strings.proposals.newProposal }),
    );

    expect(await screen.findByTestId("path")).toHaveTextContent(
      "/proposals/33333333-3333-4333-8333-333333333333",
    );
    await waitFor(() =>
      expect(screen.getByRole("banner")).toHaveTextContent(
        `${strings.proposals.drafts} / Untitled_Proposal_003`,
      ),
    );

    await userEvent.click(
      screen.getByRole("link", { name: strings.proposals.drafts }),
    );
    expect(screen.getByTestId("path")).toHaveTextContent("/proposals");
  });

  it("story 1.9: opening a draft by typing its URL still shows the breadcrumb", async () => {
    // Unlike Story 1.8's placeholder, the breadcrumb now comes from the fetched draft itself, so a
    // direct URL nav (no `location.state`) shows it too, once the fetch resolves.
    mockApi({
      draftsById: { [FIXTURE_DRAFT.id]: FIXTURE_DRAFT },
      schemasById: { [FIXTURE_DRAFT.id]: FIXTURE_SCHEMA },
    });
    renderAt(`/proposals/${FIXTURE_DRAFT.id}`);

    await waitFor(() =>
      expect(screen.getByRole("banner")).toHaveTextContent(
        `${strings.proposals.drafts} / Ally_Macbeal_Proposal_001`,
      ),
    );
  });

  it("story 1.9: another agent's proposal id sends her back to Drafts, no breadcrumb", async () => {
    mockApi(); // no entry for this id in draftsById/schemasById: both fetches 404
    renderAt("/proposals/99999999-9999-4999-8999-999999999999");

    await waitFor(() =>
      expect(screen.getByTestId("path")).toHaveTextContent("/proposals"),
    );
    await screen.findByRole("heading", { level: 1, name: TITLE });
    expect(screen.getByRole("banner").querySelector(".breadcrumb")).toBeNull();
  });
});
