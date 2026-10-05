import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

async function loadClient() {
  vi.resetModules();
  return import("./client");
}

describe("1.4 API client", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function sentHeaders(call: number): Headers {
    const init = fetchMock.mock.calls[call]?.[1];
    return new Headers(init?.headers);
  }

  it("story 1.4: every /api call sends the tab's session ID as X-Session-Id", async () => {
    const { apiFetch, sessionId } = await loadClient();

    await apiFetch("/api/me");
    await apiFetch("/api/proposals", { method: "POST", body: "{}" });
    await apiFetch("/api/proposals/42/answers", {
      method: "PATCH",
      headers: { "Content-Type": "application/json", "X-Session-Id": "forged" },
    });

    expect(sessionId).toMatch(UUID_V4);
    expect(fetchMock).toHaveBeenCalledTimes(3);
    for (const call of [0, 1, 2]) {
      expect(sentHeaders(call).get("X-Session-Id")).toBe(sessionId);
    }
    expect(sentHeaders(2).get("Content-Type")).toBe("application/json");
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe("POST");
  });

  it("story 1.4: the session ID stays the same for the tab's lifetime", async () => {
    const { apiFetch, sessionId } = await loadClient();
    await apiFetch("/api/me");
    await apiFetch("/api/me");

    expect(sentHeaders(0).get("X-Session-Id")).toBe(sessionId);
    expect(sentHeaders(1).get("X-Session-Id")).toBe(sessionId);
  });

  it("story 1.4: a new tab gets a different session ID", async () => {
    const first = await loadClient();
    const second = await loadClient();

    expect(second.sessionId).toMatch(UUID_V4);
    expect(second.sessionId).not.toBe(first.sessionId);
  });

  it("story 1.4: the session ID is kept only in memory, never in storage or cookies", async () => {
    const { sessionId } = await loadClient();

    const stored = [
      ...Object.values(localStorage),
      ...Object.values(sessionStorage),
      document.cookie,
    ].join(" ");
    expect(stored).not.toContain(sessionId);
  });

  it("story 1.4: calls are same-origin /api only", async () => {
    const { apiFetch } = await loadClient();

    await apiFetch("/api/me?view=short");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/me?view=short");
    expect(fetchMock.mock.calls[0]?.[1]?.credentials).toBe("same-origin");

    for (const path of [
      "https://evil.example.test/api/me",
      "//evil.example.test/api/me",
      "/\\evil.example.test/api/me",
      "/healthz",
      "/api/../healthz",
      "/api/%2e%2e/mcp",
      "/api",
    ]) {
      await expect(apiFetch(path), path).rejects.toThrow(/same-origin/);
    }
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("story 1.4: a refused path is a rejected promise, never a synchronous throw", async () => {
    const { apiFetch } = await loadClient();

    let call: Promise<Response> | undefined;
    expect(() => {
      call = apiFetch("/healthz");
    }).not.toThrow();
    await expect(call).rejects.toThrow(/same-origin/);
  });

  it("story 1.4: without crypto.randomUUID the session ID is still a random UUIDv4", async () => {
    vi.stubGlobal("crypto", {
      getRandomValues: crypto.getRandomValues.bind(crypto),
    });
    const first = await loadClient();
    const second = await loadClient();

    expect(first.sessionId).toMatch(UUID_V4);
    expect(second.sessionId).toMatch(UUID_V4);
    expect(second.sessionId).not.toBe(first.sessionId);
  });
});

describe("1.6 GET /api/me", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("story 1.6: returns her display name and first name", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ name: "Alice Synthetic", first_name: "Alice" }),
      ),
    );
    const { getMe } = await loadClient();

    await expect(getMe()).resolves.toEqual({
      name: "Alice Synthetic",
      firstName: "Alice",
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/me");
  });

  it("story 1.6: a 401 means nobody is signed in", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 401 }));
    const { getMe } = await loadClient();

    await expect(getMe()).resolves.toBeNull();
  });

  it.each([
    [new Response("{}", { status: 500 }), "failed with 500"],
    [new Response(JSON.stringify({ name: "Alice" })), "unexpected body"],
    [new Response("null"), "unexpected body"],
    [
      new Response(JSON.stringify({ name: 1, first_name: "Alice" })),
      "unexpected body",
    ],
  ])(
    "story 1.6: any other answer is an error, not a sign-out",
    async (response, message) => {
      fetchMock.mockResolvedValue(response);
      const { getMe } = await loadClient();

      await expect(getMe()).rejects.toThrow(message);
    },
  );
});

describe("1.8 GET /api/proposals", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const GOOD_ROW = {
    id: "11111111-1111-4111-8111-111111111111",
    display_name: "Untitled_Proposal_001",
    status: "draft",
    created_at: "2026-09-20T09:00:00Z",
    submitted_at: null,
  };

  it.each([
    ["missing field", [{ ...GOOD_ROW, display_name: undefined }]],
    ["wrong type", [{ ...GOOD_ROW, id: 1 }]],
    ["an unexpected status value", [{ ...GOOD_ROW, status: "cancelled" }]],
    ["an unexpected shape (a string, not an object)", ["not-a-row"]],
    ["the whole body not an array", GOOD_ROW],
  ])(
    "story 1.8: %s is an error, not a silently wrong row",
    async (_label, body) => {
      fetchMock.mockResolvedValue(new Response(JSON.stringify(body)));
      const { listProposals } = await loadClient();

      await expect(listProposals("draft")).rejects.toThrow(
        "GET /api/proposals returned an unexpected body.",
      );
    },
  );
});

describe("1.8 POST /api/proposals", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const GOOD_DRAFT = {
    id: "33333333-3333-4333-8333-333333333333",
    status: "draft",
    schema_version: 1,
    revision: 0,
    lock: { holder: "you", expires_at: null },
    active: ["C1"],
    answers: {},
    provenance: {},
    quote: null,
    display_name: "Untitled_Proposal_003",
  };

  it.each([
    ["missing field", { ...GOOD_DRAFT, revision: undefined }],
    ["wrong type", { ...GOOD_DRAFT, schema_version: "1" }],
    ["answers as an array, not a record", { ...GOOD_DRAFT, answers: [] }],
    ["provenance as an array, not a record", { ...GOOD_DRAFT, provenance: [] }],
    ["an unexpected shape (a string, not an object)", "not-a-draft"],
  ])(
    "story 1.8: %s is an error, not a silently wrong draft",
    async (_label, body) => {
      fetchMock.mockResolvedValue(
        new Response(JSON.stringify(body), { status: 201 }),
      );
      const { createProposal } = await loadClient();

      await expect(createProposal()).rejects.toThrow(
        "The draft api returned an unexpected body.",
      );
    },
  );
});

describe("1.9 GET /api/proposals/:id and /schema", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const GOOD_DRAFT = {
    id: "33333333-3333-4333-8333-333333333333",
    status: "draft",
    schema_version: 1,
    revision: 0,
    lock: { holder: "you", expires_at: null },
    active: ["C1"],
    answers: {},
    provenance: {},
    quote: null,
    display_name: "Untitled_Proposal_003",
  };

  it("story 1.9: getDraft returns the parsed draft", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(GOOD_DRAFT)));
    const { getDraft } = await loadClient();

    await expect(getDraft(GOOD_DRAFT.id)).resolves.toEqual({
      id: GOOD_DRAFT.id,
      status: "draft",
      schemaVersion: 1,
      revision: 0,
      lock: { holder: "you", expiresAt: null },
      active: ["C1"],
      answers: {},
      provenance: {},
      quote: null,
      displayName: "Untitled_Proposal_003",
      submittedAt: null,
      customerNumber: null,
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/proposals/${GOOD_DRAFT.id}`,
    );
  });

  it("story 1.9: getDraft throws NotFoundError on a 404", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 404 }));
    const { getDraft, NotFoundError } = await loadClient();

    await expect(getDraft(GOOD_DRAFT.id)).rejects.toBeInstanceOf(NotFoundError);
  });

  it("story 1.9: getDraft throws NotFoundError on a 422 (a malformed id)", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 422 }));
    const { getDraft, NotFoundError } = await loadClient();

    await expect(getDraft(GOOD_DRAFT.id)).rejects.toBeInstanceOf(NotFoundError);
  });

  it("story 1.9: getDraft throws a plain error on any other failure", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 500 }));
    const { getDraft, NotFoundError } = await loadClient();

    await expect(getDraft(GOOD_DRAFT.id)).rejects.not.toBeInstanceOf(
      NotFoundError,
    );
  });

  const GOOD_SCHEMA = {
    $id: "urn:formapp:form-schema:v1",
    properties: { C1: { title: "First name", type: "string" } },
    required: ["C1"],
    allOf: [],
  };

  it("story 1.9: getSchema returns properties, required and allOf", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(GOOD_SCHEMA)));
    const { getSchema } = await loadClient();

    await expect(getSchema(GOOD_DRAFT.id)).resolves.toEqual({
      properties: GOOD_SCHEMA.properties,
      required: GOOD_SCHEMA.required,
      allOf: [],
    });
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/proposals/${GOOD_DRAFT.id}/schema`,
    );
  });

  it("story 1.9: getSchema throws NotFoundError on a 404", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 404 }));
    const { getSchema, NotFoundError } = await loadClient();

    await expect(getSchema(GOOD_DRAFT.id)).rejects.toBeInstanceOf(
      NotFoundError,
    );
  });

  it("story 1.9: getSchema throws NotFoundError on a 422 (a malformed id)", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 422 }));
    const { getSchema, NotFoundError } = await loadClient();

    await expect(getSchema(GOOD_DRAFT.id)).rejects.toBeInstanceOf(
      NotFoundError,
    );
  });

  it.each([
    ["missing required", { properties: {} }],
    ["properties not an object", { properties: [], required: [] }],
    ["required not an array of strings", { properties: {}, required: [1] }],
    ["an unexpected shape (a string, not an object)", "not-a-schema"],
  ])(
    "story 1.9: %s is an error, not a silently wrong schema",
    async (_label, body) => {
      fetchMock.mockResolvedValue(new Response(JSON.stringify(body)));
      const { getSchema } = await loadClient();

      await expect(getSchema(GOOD_DRAFT.id)).rejects.toThrow(
        "GET /api/proposals/:id/schema returned an unexpected body.",
      );
    },
  );
});

describe("2.3 GET /api/products?proposal_id=", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const PROPOSAL_ID = "33333333-3333-4333-8333-333333333333";

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const GOOD_PRODUCT = {
    code: "FSH",
    name: "FamilyShield Life & Health",
    type: "life_health",
    covers_dependents: true,
    policy_terms: [{ code: "20_yrs", label: "20 yrs" }],
    sum_assured_min: 200000,
    sum_assured_max: 600000,
    default_sum_assured: 300000,
    default_term: "20_yrs",
    min_age: 18,
    max_age: 55,
    monthly: 185.22,
    yearly: 2111.51,
    riders: [
      {
        code: "R07",
        name: "Maternity & newborn",
        monthly: 34.73,
        yearly: 395.91,
      },
    ],
  };

  it("story 2.3: getProducts returns the parsed, camelCased products", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify([GOOD_PRODUCT])));
    const { getProducts } = await loadClient();

    await expect(getProducts(PROPOSAL_ID)).resolves.toEqual([
      {
        code: "FSH",
        name: "FamilyShield Life & Health",
        type: "life_health",
        coversDependents: true,
        policyTerms: [{ code: "20_yrs", label: "20 yrs" }],
        sumAssuredMin: 200000,
        sumAssuredMax: 600000,
        defaultSumAssured: 300000,
        defaultTerm: "20_yrs",
        minAge: 18,
        maxAge: 55,
        monthly: 185.22,
        yearly: 2111.51,
        riders: [
          {
            code: "R07",
            name: "Maternity & newborn",
            monthly: 34.73,
            yearly: 395.91,
          },
        ],
      },
    ]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      `/api/products?proposal_id=${PROPOSAL_ID}`,
    );
  });

  it("story 2.3: getProducts keeps null sum-assured fields null (CFH)", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify([
          {
            ...GOOD_PRODUCT,
            code: "CFH",
            sum_assured_min: null,
            sum_assured_max: null,
            default_sum_assured: null,
            riders: [],
          },
        ]),
      ),
    );
    const { getProducts } = await loadClient();

    const [product] = await getProducts(PROPOSAL_ID);
    expect(product).toMatchObject({
      sumAssuredMin: null,
      sumAssuredMax: null,
      defaultSumAssured: null,
    });
  });

  it("story 2.3: getProducts throws NotFoundError on a 404", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 404 }));
    const { getProducts, NotFoundError } = await loadClient();

    await expect(getProducts(PROPOSAL_ID)).rejects.toBeInstanceOf(
      NotFoundError,
    );
  });

  it("story 2.3: getProducts throws NotFoundError on a 422 (a malformed proposal id)", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 422 }));
    const { getProducts, NotFoundError } = await loadClient();

    await expect(getProducts(PROPOSAL_ID)).rejects.toBeInstanceOf(
      NotFoundError,
    );
  });

  it("story 2.3: getProducts throws a plain error on any other failure", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 500 }));
    const { getProducts, NotFoundError } = await loadClient();

    await expect(getProducts(PROPOSAL_ID)).rejects.not.toBeInstanceOf(
      NotFoundError,
    );
  });

  it("story 2.3: getProducts rejects an unexpected body, not a silently wrong list", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ code: "FSH" })));
    const { getProducts } = await loadClient();

    await expect(getProducts(PROPOSAL_ID)).rejects.toThrow(
      "GET /api/products returned an unexpected body.",
    );
  });
});

describe("4.4 POST /api/proposals/:id/lock", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const DRAFT_ID = "33333333-3333-4333-8333-333333333333";

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("story 4.4: lockDraft posts take_over: false by default and returns the parsed lock", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({ holder: "you", expires_at: "2026-09-27T09:01:00Z" }),
      ),
    );
    const { lockDraft } = await loadClient();

    await expect(lockDraft(DRAFT_ID)).resolves.toEqual({
      holder: "you",
      expiresAt: "2026-09-27T09:01:00Z",
    });
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(`/api/proposals/${DRAFT_ID}/lock`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ take_over: false });
  });

  it("story 4.4: lockDraft({ takeOver: true }) posts take_over: true", async () => {
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ holder: "you", expires_at: null })),
    );
    const { lockDraft } = await loadClient();

    await lockDraft(DRAFT_ID, { takeOver: true });

    const [, init] = fetchMock.mock.calls[0] ?? [];
    expect(JSON.parse(String(init?.body))).toEqual({ take_over: true });
  });

  it.each(["other_session", "ai"] as const)(
    "story 4.4: lockDraft reports holder %s when blocked",
    async (holder) => {
      fetchMock.mockResolvedValue(
        new Response(
          JSON.stringify({ holder, expires_at: "2026-09-27T09:01:00Z" }),
        ),
      );
      const { lockDraft } = await loadClient();

      await expect(lockDraft(DRAFT_ID)).resolves.toEqual({
        holder,
        expiresAt: "2026-09-27T09:01:00Z",
      });
    },
  );

  it("story 4.4: lockDraft throws NotFoundError on a 404", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 404 }));
    const { lockDraft, NotFoundError } = await loadClient();

    await expect(lockDraft(DRAFT_ID)).rejects.toBeInstanceOf(NotFoundError);
  });

  it("story 4.4: lockDraft throws NotFoundError on a 422 (a malformed id)", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 422 }));
    const { lockDraft, NotFoundError } = await loadClient();

    await expect(lockDraft(DRAFT_ID)).rejects.toBeInstanceOf(NotFoundError);
  });

  it("story 4.4: lockDraft throws ApiError on any other failure", async () => {
    fetchMock.mockResolvedValue(new Response("{}", { status: 500 }));
    const { lockDraft, ApiError } = await loadClient();

    await expect(lockDraft(DRAFT_ID)).rejects.toBeInstanceOf(ApiError);
  });
});

describe("4.5 chat", () => {
  const fetchMock = vi.fn<typeof fetch>();
  const DRAFT_ID = "55555555-5555-4555-8555-555555555555";

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** One SSE response, framed exactly like the api's own relay (Story 4.5, AD-5). */
  function sseResponse(
    events: { event: string; data: unknown }[],
    status = 200,
  ): Response {
    const encoder = new TextEncoder();
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const event of events) {
          controller.enqueue(
            encoder.encode(
              `event: ${event.event}\ndata: ${JSON.stringify(event.data)}\n\n`,
            ),
          );
        }
        controller.close();
      },
    });
    return new Response(stream, { status });
  }

  it("story 4.5: sendChat posts the message and relays delta/done events in order", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        { event: "delta", data: { text: "Hello" } },
        { event: "delta", data: { text: ", world" } },
        { event: "done", data: { revision: 7 } },
      ]),
    );
    const { sendChat } = await loadClient();
    const received: unknown[] = [];

    await sendChat(DRAFT_ID, "hi there", (event) => received.push(event));

    expect(received).toEqual([
      { type: "delta", text: "Hello" },
      { type: "delta", text: ", world" },
      { type: "done", revision: 7 },
    ]);
    const [url, init] = fetchMock.mock.calls[0] ?? [];
    expect(url).toBe(`/api/proposals/${DRAFT_ID}/chat`);
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ message: "hi there" });
  });

  it("story 4.5: sendChat relays an error event without throwing", async () => {
    fetchMock.mockResolvedValue(
      sseResponse([
        { event: "delta", data: { text: "partial" } },
        { event: "error", data: { code: "timeout", message: "Timed out." } },
      ]),
    );
    const { sendChat } = await loadClient();
    const received: unknown[] = [];

    await expect(
      sendChat(DRAFT_ID, "hi", (event) => received.push(event)),
    ).resolves.toBeUndefined();

    expect(received).toEqual([
      { type: "delta", text: "partial" },
      { type: "error", code: "timeout", message: "Timed out." },
    ]);
  });

  it("story 4.5: sendChat drops a malformed SSE frame instead of throwing", async () => {
    fetchMock.mockResolvedValue(
      new Response("event: delta\ndata: not-json\n\nevent: done\ndata: {}\n\n"),
    );
    const { sendChat } = await loadClient();
    const received: unknown[] = [];

    await sendChat(DRAFT_ID, "hi", (event) => received.push(event));

    expect(received).toEqual([]); // both frames drop: malformed JSON, then done with no revision
  });

  it("story 4.5: sendChat throws NotFoundError on a 404 or a 422, before any stream is read", async () => {
    const { sendChat, NotFoundError } = await loadClient();

    fetchMock.mockResolvedValue(new Response("{}", { status: 404 }));
    await expect(sendChat(DRAFT_ID, "hi", () => {})).rejects.toBeInstanceOf(
      NotFoundError,
    );

    fetchMock.mockResolvedValue(new Response("{}", { status: 422 }));
    await expect(sendChat(DRAFT_ID, "hi", () => {})).rejects.toBeInstanceOf(
      NotFoundError,
    );
  });

  it.each(["proposal_submitted", "turn_in_progress", "lock_not_held"])(
    "story 4.5: sendChat throws ApiError with the %s field error on a 409",
    async (code) => {
      fetchMock.mockResolvedValue(
        new Response(
          JSON.stringify({ errors: [{ field: "x", code, message: "no" }] }),
          { status: 409 },
        ),
      );
      const { sendChat, ApiError } = await loadClient();

      const error = await sendChat(DRAFT_ID, "hi", () => {}).catch((e) => e);

      expect(error).toBeInstanceOf(ApiError);
      expect(
        (error as InstanceType<typeof ApiError>).fieldErrors?.[0]?.code,
      ).toBe(code);
    },
  );

  it("story 4.5: getChatHistory returns [] before the first turn", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify({ messages: [] })));
    const { getChatHistory } = await loadClient();

    await expect(getChatHistory(DRAFT_ID)).resolves.toEqual([]);
  });

  it("story 4.5: getChatHistory parses role/text messages, oldest first", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          messages: [
            { role: "user", text: "Her name is Ally." },
            { role: "assistant", text: "Noted." },
          ],
        }),
      ),
    );
    const { getChatHistory } = await loadClient();

    await expect(getChatHistory(DRAFT_ID)).resolves.toEqual([
      { role: "user", text: "Her name is Ally." },
      { role: "assistant", text: "Noted." },
    ]);
  });

  it("story 4.5: getChatHistory throws NotFoundError on a 404 or a 422", async () => {
    const { getChatHistory, NotFoundError } = await loadClient();

    fetchMock.mockResolvedValue(new Response("{}", { status: 404 }));
    await expect(getChatHistory(DRAFT_ID)).rejects.toBeInstanceOf(
      NotFoundError,
    );

    fetchMock.mockResolvedValue(new Response("{}", { status: 422 }));
    await expect(getChatHistory(DRAFT_ID)).rejects.toBeInstanceOf(
      NotFoundError,
    );
  });
});

describe("6.1/6.2 GET /api/speech/token", () => {
  const fetchMock = vi.fn<typeof fetch>();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  const GOOD_BODY = {
    token: "aad#resource-id#synthetic-entra-token",
    auth_mode: "aad",
    region: "southeastasia",
    endpoint: "https://cog-sample-demo-sea.cognitiveservices.azure.com",
    voice: "en-SG-LunaNeural",
    locale: "en-SG",
    expires_at: "2026-09-28T10:10:00Z",
  };

  it("story 6.2: getSpeechToken camelCases the wire shape, including locale (AD-19)", async () => {
    fetchMock.mockResolvedValue(new Response(JSON.stringify(GOOD_BODY)));
    const { getSpeechToken } = await loadClient();

    await expect(getSpeechToken()).resolves.toEqual({
      token: "aad#resource-id#synthetic-entra-token",
      authMode: "aad",
      region: "southeastasia",
      endpoint: "https://cog-sample-demo-sea.cognitiveservices.azure.com",
      voice: "en-SG-LunaNeural",
      locale: "en-SG",
      expiresAt: "2026-09-28T10:10:00Z",
    });
  });

  it("story 6.2: getSpeechToken throws ApiError with the speech_unavailable field error on a 503", async () => {
    fetchMock.mockResolvedValue(
      new Response(
        JSON.stringify({
          errors: [
            { field: "speech", code: "speech_unavailable", message: "no" },
          ],
        }),
        { status: 503 },
      ),
    );
    const { getSpeechToken, ApiError } = await loadClient();

    const error = await getSpeechToken().catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(
      (error as InstanceType<typeof ApiError>).fieldErrors?.[0]?.code,
    ).toBe("speech_unavailable");
  });

  it.each([
    ["missing locale", { ...GOOD_BODY, locale: undefined }],
    ["wrong type", { ...GOOD_BODY, expires_at: 1 }],
  ])(
    "story 6.2: %s is an error, not a silently wrong token",
    async (_label, body) => {
      fetchMock.mockResolvedValue(new Response(JSON.stringify(body)));
      const { getSpeechToken } = await loadClient();

      await expect(getSpeechToken()).rejects.toThrow(
        "GET /api/speech/token returned an unexpected body.",
      );
    },
  );
});
