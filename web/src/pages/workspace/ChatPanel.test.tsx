import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { MicErrorReason } from "../../speech";
import { strings } from "../../strings";
import { ChatPanel } from "./ChatPanel";

// Story 6.4/6.5 (FORM-233/FORM-234): `web/src/speech/` (the real Speech SDK boundary) is mocked
// out entirely -- this file never loads the SDK. The replacement hook is real React state (so the
// mic button and "Listening" pill actually re-render), driven from tests through `micDriver`,
// which mirrors the real hook's contract: `toggle` starts a session (capturing the box's current
// text once) if idle, or ends the current one if listening -- auto-sending through `onAutoSend`
// (FR62) if it heard speech, and (like the real `recognizer.ts`) showing the no-speech caption if
// it didn't; `speak` appends after the captured base text and marks this session as having heard
// something; `fail` reports one of the other two UX-DR45 reasons.
type MicDriver = {
  toggle: () => void;
  stop: () => void;
  speak: (text: string) => void;
  fail: (reason: MicErrorReason) => void;
};

let micDriver: MicDriver | null = null;

vi.mock("../../speech", () => ({
  useMicRecognition: (opts: {
    enabled: boolean;
    getText: () => string;
    setText: (text: string) => void;
    onAutoSend: (text: string) => void;
  }) => {
    const [listening, setListening] = useState(false);
    const [error, setError] = useState<MicErrorReason | null>(null);
    const baseRef = useRef("");
    const spokenRef = useRef("");
    const heardRef = useRef(false);

    function endSession(autoSend: boolean) {
      setListening(false);
      if (heardRef.current) {
        if (autoSend) {
          opts.onAutoSend(
            [baseRef.current, spokenRef.current].filter(Boolean).join(" "),
          );
        }
      } else {
        setError("no_speech");
      }
    }

    micDriver = {
      toggle: () => {
        if (listening) {
          endSession(true);
          return;
        }
        if (!opts.enabled) return;
        baseRef.current = opts.getText();
        spokenRef.current = "";
        heardRef.current = false;
        setListening(true);
        setError(null);
      },
      stop: () => {
        if (!listening) return;
        endSession(false);
      },
      speak: (text: string) => {
        heardRef.current = true;
        spokenRef.current = text;
        opts.setText([baseRef.current, text].filter(Boolean).join(" "));
      },
      fail: (reason: MicErrorReason) => {
        setError(reason);
        setListening(false);
      },
    };

    return {
      listening,
      error,
      toggle: micDriver.toggle,
      stop: micDriver.stop,
    };
  },
}));

const DRAFT_ID = "66666666-6666-4666-8666-666666666666";
const CHAT_URL = `/api/proposals/${DRAFT_ID}/chat`;

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/** One SSE response, framed exactly like the api's own relay (Story 4.5, AD-5). */
function sseResponse(events: { event: string; data: unknown }[]): Response {
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
  return new Response(stream, { status: 200 });
}

function mockChat({
  history = [],
  chatResponse,
}: {
  history?: { role: string; text: string }[];
  chatResponse?: () => Response;
} = {}) {
  fetchMock.mockImplementation(async (input, init) => {
    const url = String(input);
    if (url === CHAT_URL && (!init || init.method === undefined)) {
      return jsonResponse({ messages: history });
    }
    if (url === CHAT_URL && init?.method === "POST") {
      return chatResponse
        ? chatResponse()
        : sseResponse([{ event: "done", data: { revision: 1 } }]);
    }
    return jsonResponse({ errors: [] }, 404);
  });
}

function chatBodies(): { message: string }[] {
  return fetchMock.mock.calls
    .filter(
      ([input, init]) => String(input) === CHAT_URL && init?.method === "POST",
    )
    .map(([, init]) => JSON.parse(String(init?.body)));
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
  mockChat();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

function renderPanel(
  overrides: {
    canSend?: boolean;
    onTurnActiveChange?: (active: boolean) => void;
    onDone?: () => void;
  } = {},
) {
  const onTurnActiveChange = overrides.onTurnActiveChange ?? vi.fn();
  const onDone = overrides.onDone ?? vi.fn();
  render(
    <ChatPanel
      draftId={DRAFT_ID}
      canSend={overrides.canSend ?? true}
      onTurnActiveChange={onTurnActiveChange}
      onDone={onDone}
    />,
  );
  return { onTurnActiveChange, onDone };
}

describe("4.5 ChatPanel", () => {
  it("story 4.5: loads history on mount and renders each bubble", async () => {
    mockChat({
      history: [
        { role: "user", text: "Her name is Ally." },
        { role: "assistant", text: "Noted, thanks." },
      ],
    });

    renderPanel();

    expect(await screen.findByText("Her name is Ally.")).toBeInTheDocument();
    expect(screen.getByText("Noted, thanks.")).toBeInTheDocument();
    expect(screen.getByText(strings.workspace.chatAiLabel)).toBeInTheDocument();
  });

  it("story 4.5: sending streams deltas into an AI bubble, then finalizes on done", async () => {
    mockChat({
      chatResponse: () =>
        sseResponse([
          { event: "delta", data: { text: "Got it. " } },
          { event: "delta", data: { text: "Filled it in." } },
          { event: "done", data: { revision: 2 } },
        ]),
    });
    const { onTurnActiveChange, onDone } = renderPanel();
    const user = userEvent.setup();

    await user.type(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
      "Her name is Ally.{Enter}",
    );

    expect(await screen.findByText("Her name is Ally.")).toBeInTheDocument();
    await waitFor(() =>
      expect(
        document.querySelector(".chat-bubble--ai .chat-bubble__text"),
      ).toHaveTextContent("Got it. Filled it in."),
    );
    await waitFor(() => expect(onDone).toHaveBeenCalledOnce());
    expect(onTurnActiveChange).toHaveBeenNthCalledWith(1, true);
    expect(onTurnActiveChange).toHaveBeenLastCalledWith(false);
    expect(chatBodies()).toEqual([{ message: "Her name is Ally." }]);
  });

  it("story 4.5: up-arrow also sends", async () => {
    renderPanel();
    const user = userEvent.setup();

    await user.type(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
      "hi{ArrowUp}",
    );

    await waitFor(() => expect(chatBodies()).toEqual([{ message: "hi" }]));
  });

  it("story 4.5: an empty message never sends", async () => {
    renderPanel();
    const user = userEvent.setup();

    await user.type(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
      "   {Enter}",
    );

    expect(chatBodies()).toEqual([]);
  });

  it("story 4.5: without the lock, input and send are disabled with the lock-less placeholder", () => {
    renderPanel({ canSend: false });

    const input = screen.getByPlaceholderText(
      strings.workspace.chatLocklessPlaceholder,
    );
    expect(input).toBeDisabled();
    expect(
      screen.getByRole("button", { name: strings.workspace.chatSend }),
    ).toBeDisabled();
    // Story 6.2 (FORM-230, AD-19): no edit lock disables Send, so it disables the mic too.
    expect(
      screen.getByRole("button", { name: strings.workspace.micStartSpeaking }),
    ).toBeDisabled();
  });

  it("story 4.5: a mid-stream failure shows the fixed message and still releases turn-active", async () => {
    mockChat({
      chatResponse: () =>
        sseResponse([
          { event: "delta", data: { text: "Working on it..." } },
          { event: "error", data: { code: "timeout", message: "boom" } },
        ]),
    });
    const { onTurnActiveChange, onDone } = renderPanel();
    const user = userEvent.setup();

    await user.type(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
      "hi{Enter}",
    );

    await waitFor(() =>
      expect(
        document.querySelector(".chat-bubble--ai .chat-bubble__text"),
      ).toHaveTextContent(strings.workspace.chatFailureMessage),
    );
    expect(onTurnActiveChange).toHaveBeenLastCalledWith(false);
    expect(onDone).not.toHaveBeenCalled(); // error, not done: no re-fetch
  });

  it("story 4.5: while a turn is active, the input and send button are disabled", async () => {
    let resolveEvents: (() => void) | undefined;
    mockChat({
      chatResponse: () => {
        const encoder = new TextEncoder();
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode('event: delta\ndata: {"text":"..."}\n\n'),
            );
            resolveEvents = () => {
              controller.enqueue(
                encoder.encode('event: done\ndata: {"revision":1}\n\n'),
              );
              controller.close();
            };
          },
        });
        return new Response(stream, { status: 200 });
      },
    });
    renderPanel();
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText(
      strings.workspace.chatPlaceholder,
    );

    await user.type(input, "hi{Enter}");

    await waitFor(() => expect(input).toBeDisabled());
    // Story 6.2 (FORM-230, AD-19): the mic follows Send -- disabled the instant Send is.
    expect(
      screen.getByRole("button", { name: strings.workspace.micStartSpeaking }),
    ).toBeDisabled();
    resolveEvents?.();
    await waitFor(() => expect(input).toBeEnabled());
    expect(
      screen.getByRole("button", { name: strings.workspace.micStartSpeaking }),
    ).toBeEnabled();
  });

  it("story 4.5: the AI bubble's arrival is announced once it finishes, not per delta", async () => {
    mockChat({
      chatResponse: () =>
        sseResponse([
          { event: "delta", data: { text: "Hello" } },
          { event: "done", data: { revision: 1 } },
        ]),
    });
    renderPanel();
    const user = userEvent.setup();

    await user.type(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
      "hi{Enter}",
    );

    await waitFor(() => {
      const live = document.querySelector('[aria-live="polite"]');
      expect(live).toHaveTextContent("Hello");
    });
  });

  it("story 4.8: a throttled send shows a Wait Ns countdown, re-enables at 0, and never disables the input", async () => {
    vi.useFakeTimers();
    mockChat({
      chatResponse: () =>
        jsonResponse(
          {
            code: "rate_limited",
            message: "Too many chat turns.",
            retry_after_seconds: 3,
          },
          429,
        ),
    });
    renderPanel();
    const input = screen.getByPlaceholderText(
      strings.workspace.chatPlaceholder,
    );

    // fireEvent, not userEvent: userEvent's own internal delays don't mix with fake timers, even
    // with delay: null (its click/keyboard sequencing still touches real timers under the hood).
    // fireEvent dispatches synchronously, so it plays cleanly with fake timers here.
    fireEvent.change(input, { target: { value: "hi" } });
    fireEvent.keyDown(input, { key: "Enter" });
    // Flushes the mocked fetch's rejection through to the catch handler (several hops: apiFetch's
    // own await, then retryAfterSecondsOf's response.json()): findByRole/waitFor's own polling
    // relies on real setTimeout, which fake timers replace, so repeated small advances -- not a
    // wait -- are what actually let that microtask chain finish, one hop per iteration.
    await act(async () => {
      for (let flush = 0; flush < 20; flush += 1) {
        await vi.advanceTimersByTimeAsync(0);
      }
    });

    expect(
      screen.getByRole("button", { name: strings.workspace.chatWait(3) }),
    ).toBeDisabled();
    expect(input).toBeEnabled(); // Story 4.8: input stays typeable throughout
    // Story 6.2 (FORM-230, AD-19): throttled disables Send, so it disables the mic too.
    expect(
      screen.getByRole("button", { name: strings.workspace.micStartSpeaking }),
    ).toBeDisabled();
    // Refused before the turn ever started: nothing counted, her text comes back.
    expect(input).toHaveValue("hi");
    expect(screen.queryByText("hi")).not.toBeInTheDocument(); // no stray user bubble

    // A timer-callback state update (the countdown's own setInterval) needs its own act()
    // boundary to flush into the DOM synchronously, unlike the fetch-rejection microtasks above.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });
    expect(
      screen.getByRole("button", { name: strings.workspace.chatWait(2) }),
    ).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    expect(
      screen.getByRole("button", { name: strings.workspace.chatSend }),
    ).toBeEnabled();
  });

  // Story 4.6: `GET /api/proposals/:id/chat` always puts the AI's opening checklist first
  // (`api/domain/checklist.py`); ChatPanel needs no special case for it -- it's just the first
  // history message, rendered like any other "✦ formapp AI" bubble.
  it("story 4.6: renders the opening checklist as the first AI bubble, ahead of real history", async () => {
    mockChat({
      history: [
        {
          role: "assistant",
          text: "Hi Alice. To fill in this proposal, you can use the microphone, ask me for help, or type the details into the form yourself.",
        },
        { role: "user", text: "Her name is Ally." },
      ],
    });

    renderPanel();

    await screen.findByText("Her name is Ally.");
    const bubbles = document.querySelectorAll(
      ".chat-panel__messages > .chat-bubble",
    );
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0]).toHaveTextContent("Hi Alice. To fill in this proposal");
    expect(bubbles[0]).toHaveTextContent(strings.workspace.chatAiLabel);
    expect(bubbles[1]).toHaveTextContent("Her name is Ally.");
  });
});

describe("6.4/6.5 ChatPanel mic (FORM-233/FORM-234)", () => {
  beforeEach(() => {
    micDriver = null;
  });

  function idleMicButton() {
    return screen.getByRole("button", {
      name: strings.workspace.micStartSpeaking,
    });
  }

  function listeningMicButton() {
    return screen.getByRole("button", {
      name: strings.workspace.micStopAndSend,
    });
  }

  it("story 6.4: a tap (click) shows the Listening pill with aria-pressed and the name 'Stop and send'; tapping again hides it", () => {
    renderPanel();

    fireEvent.click(idleMicButton());
    const listening = listeningMicButton();
    expect(listening).toHaveAttribute("aria-pressed", "true");
    expect(
      screen.getByText(strings.workspace.micListening),
    ).toBeInTheDocument();

    fireEvent.click(listening);
    const idle = idleMicButton();
    expect(idle).toHaveAttribute("aria-pressed", "false");
  });

  it("story 6.4: Space or Enter keydown on the mic also toggles (UX-DR44)", () => {
    renderPanel();

    fireEvent.keyDown(idleMicButton(), { key: " " });
    expect(listeningMicButton()).toBeInTheDocument();

    fireEvent.keyDown(listeningMicButton(), { key: "Enter" });
    expect(idleMicButton()).toBeInTheDocument();
  });

  it("story 6.4: her words appear in the message box as she speaks, after anything already typed", async () => {
    renderPanel();
    const user = userEvent.setup();
    const input = screen.getByPlaceholderText(
      strings.workspace.chatPlaceholder,
    );
    await user.type(input, "existing customer");

    fireEvent.click(idleMicButton());
    act(() => micDriver?.speak("ally 1994 november"));

    expect(input).toHaveValue("existing customer ally 1994 november");
  });

  it("story 6.4: speaking into an empty box never adds a leading space", () => {
    renderPanel();

    fireEvent.click(idleMicButton());
    act(() => micDriver?.speak("her budget is 200 a month"));

    expect(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
    ).toHaveValue("her budget is 200 a month");
  });

  it("story 6.4: pressing Send directly while listening stops listening and sends once, not twice", async () => {
    renderPanel();

    fireEvent.click(idleMicButton());
    act(() => micDriver?.speak("hello"));
    expect(listeningMicButton()).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: strings.workspace.chatSend }),
    );

    expect(idleMicButton()).toBeInTheDocument(); // back to "Start speaking", not "Listening"
    await waitFor(() => expect(chatBodies()).toEqual([{ message: "hello" }]));
  });

  it("story 6.5: tapping the mic off after hearing speech sends it at once, and the box clears", async () => {
    renderPanel();
    const input = screen.getByPlaceholderText(
      strings.workspace.chatPlaceholder,
    );

    fireEvent.click(idleMicButton());
    act(() => micDriver?.speak("hello"));
    expect(chatBodies()).toEqual([]); // nothing sent yet, however long she's spoken

    fireEvent.click(listeningMicButton());

    await waitFor(() => expect(chatBodies()).toEqual([{ message: "hello" }]));
    expect(input).toHaveValue(""); // cleared exactly as a typed send clears it
    expect(idleMicButton()).toBeInTheDocument();
  });

  it("story 6.5: tapping the mic off after hearing nothing sends nothing, and shows the caption", () => {
    renderPanel();

    fireEvent.click(idleMicButton());
    fireEvent.click(listeningMicButton());

    expect(chatBodies()).toEqual([]);
    expect(
      screen.getByText(strings.workspace.micNoSpeechMessage),
    ).toBeInTheDocument();
    expect(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
    ).toBeEnabled();
  });

  it("story 6.5: an auto-send that's refused (rate_limited) leaves the words in the box and shows the countdown", async () => {
    vi.useFakeTimers();
    mockChat({
      chatResponse: () =>
        jsonResponse(
          {
            code: "rate_limited",
            message: "Too many chat turns.",
            retry_after_seconds: 3,
          },
          429,
        ),
    });
    renderPanel();

    fireEvent.click(idleMicButton());
    act(() => micDriver?.speak("hello"));
    fireEvent.click(listeningMicButton());

    // Same flush pattern as the typed-send throttle test: several microtask hops between the
    // mocked fetch's rejection and the countdown appearing.
    await act(async () => {
      for (let flush = 0; flush < 20; flush += 1) {
        await vi.advanceTimersByTimeAsync(0);
      }
    });

    expect(
      screen.getByRole("button", { name: strings.workspace.chatWait(3) }),
    ).toBeDisabled();
    expect(
      screen.getByPlaceholderText(strings.workspace.chatPlaceholder),
    ).toHaveValue("hello");
    expect(screen.queryByText("hello")).not.toBeInTheDocument(); // no stray user bubble
  });

  it.each([
    ["blocked", strings.workspace.micBlockedMessage],
    ["unavailable", strings.workspace.micUnavailableMessage],
    ["no_speech", strings.workspace.micNoSpeechMessage],
  ] satisfies [MicErrorReason, string][])(
    "story 6.2: the %s caption shows under the input, and typing/Send keep working",
    async (reason, message) => {
      renderPanel();
      fireEvent.click(idleMicButton());

      act(() => micDriver?.fail(reason));

      expect(screen.getByText(message)).toBeInTheDocument();
      const input = screen.getByPlaceholderText(
        strings.workspace.chatPlaceholder,
      );
      expect(input).toBeEnabled();
      const user = userEvent.setup();
      await user.type(input, "hi{Enter}");
      await waitFor(() => expect(chatBodies()).toEqual([{ message: "hi" }]));
    },
  );
});
