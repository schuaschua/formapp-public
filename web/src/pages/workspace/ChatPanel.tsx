// Story 4.5: the chat panel (DESIGN.md Components "Chat panel"/"Chat input"/"Send button",
// EXPERIENCE.md "Chat panel"/"AI replying"/"Failure/cutoff"). Loads history on open, sends a
// message through `sendChat`'s SSE relay, streams the reply into a bubble, and tells `Workspace`
// when a turn starts/ends (`onTurnActiveChange`, so the form goes read-only the moment she sends,
// without waiting for the next lock heartbeat) and when one finishes cleanly (`onDone`, so
// `Workspace` re-fetches the draft, AC11).

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import {
  getChatHistory,
  sendChat,
  ThrottledError,
  type ChatEvent,
  type ChatMessage,
} from "../../api/client";
import { useMicRecognition, type MicErrorReason } from "../../speech";
import { strings } from "../../strings";
import "./ChatPanel.css";

/** A microphone glyph, matching `AppShell`'s inline-SVG icon style (`currentColor`, so it takes
 * `--mic-button-foreground` in both states). */
function MicIcon() {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0" />
      <path d="M12 18v3M8 21h8" />
    </svg>
  );
}

/** Story 6.2: the mic caption shown under the input (UX-DR45), worded exactly as the UX gives it. */
function micCaptionFor(reason: MicErrorReason): string {
  if (reason === "blocked") return strings.workspace.micBlockedMessage;
  if (reason === "no_speech") return strings.workspace.micNoSpeechMessage;
  return strings.workspace.micUnavailableMessage;
}

// Story 4.8: the Send button's states live in one place (spec Boundaries), so a later mic button
// (Epic 6) can share the row.
type SendButtonState = "ready" | "turn_active" | "locked" | "throttled";

function sendButtonState(
  turnActive: boolean,
  canSend: boolean,
  throttleSeconds: number | null,
): SendButtonState {
  if (turnActive) return "turn_active";
  if (throttleSeconds !== null) return "throttled";
  if (!canSend) return "locked";
  return "ready";
}

type Bubble = {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Still receiving deltas: shows the caret and typing dots (DESIGN.md "Chat panel"). */
  streaming?: boolean;
};

let bubbleSeq = 0;
function nextBubbleId(): string {
  bubbleSeq += 1;
  return `bubble-${bubbleSeq}`;
}

function fromHistory(messages: ChatMessage[]): Bubble[] {
  return messages.map((message) => ({
    id: nextBubbleId(),
    role: message.role === "user" ? "user" : "assistant",
    text: message.text,
  }));
}

export type ChatPanelProps = {
  draftId: string;
  /** This tab holds the edit lock (Story 4.4/4.5, AD-16): false disables the input and send
   * button with the lock-less placeholder, whoever -- another session or the AI -- holds it
   * (AC8). */
  canSend: boolean;
  /** Called the instant a turn starts (true) and again the instant it ends, cleanly or not
   * (false) -- before the next lock heartbeat would ever notice (EXPERIENCE.md "AI replying"). */
  onTurnActiveChange: (active: boolean) => void;
  /** Called once a turn's stream ends with `done` -- never for `error` (AC11: only a successful
   * turn re-fetches the draft). */
  onDone: () => void;
};

/** The chat panel: history, streaming bubbles, the input pill and send button. */
export function ChatPanel({
  draftId,
  canSend,
  onTurnActiveChange,
  onDone,
}: ChatPanelProps) {
  const [messages, setMessages] = useState<Bubble[]>([]);
  const [historyError, setHistoryError] = useState(false);
  const [inputValue, setInputValue] = useState("");
  const [turnActive, setTurnActive] = useState(false);
  const [announcement, setAnnouncement] = useState("");
  // Story 4.8: seconds left on a 429's countdown; null means "not throttled".
  const [throttleSeconds, setThrottleSeconds] = useState<number | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const throttleIntervalRef = useRef<ReturnType<typeof setInterval> | null>(
    null,
  );

  function clearThrottleInterval() {
    if (throttleIntervalRef.current !== null) {
      clearInterval(throttleIntervalRef.current);
      throttleIntervalRef.current = null;
    }
  }

  function startThrottleCountdown(seconds: number) {
    clearThrottleInterval();
    setThrottleSeconds(Math.max(1, Math.ceil(seconds)));
    throttleIntervalRef.current = setInterval(() => {
      setThrottleSeconds((current) => {
        if (current === null || current <= 1) {
          clearThrottleInterval();
          return null;
        }
        return current - 1;
      });
    }, 1000);
  }

  useEffect(() => clearThrottleInterval, []);

  // Story 6.2 (FORM-230, AD-19): the mic follows Send -- computed early so `useMicRecognition`'s
  // `enabled` and the Send button below read the same value.
  const buttonState = sendButtonState(turnActive, canSend, throttleSeconds);
  const micEnabled = buttonState === "ready";

  // Guards a still-in-flight history load or chat stream against a draftId change under this
  // same mounted panel (Workspace's own draftId-can-change-in-place note; same pattern as
  // autosave.ts's currentDraftIdRef).
  const draftIdRef = useRef(draftId);
  const [trackedDraftId, setTrackedDraftId] = useState(draftId);
  if (trackedDraftId !== draftId) {
    setTrackedDraftId(draftId);
    setMessages([]);
    setHistoryError(false);
    setInputValue("");
    setTurnActive(false);
    setAnnouncement("");
    // Not clearThrottleInterval() here: reading the ref is a render-time access React's own
    // rules forbid (this whole block runs during render, the same "adjust state on prop change"
    // pattern the comment above describes). Nulling the state alone already hides any countdown;
    // a stale interval's own next tick sees throttleSeconds is already null and clears itself
    // from inside its callback (not render), a harmless one tick later at worst.
    setThrottleSeconds(null);
  }

  const onTurnActiveChangeRef = useRef(onTurnActiveChange);
  const onDoneRef = useRef(onDone);
  const inputValueRef = useRef(inputValue);
  useEffect(() => {
    draftIdRef.current = draftId;
    onTurnActiveChangeRef.current = onTurnActiveChange;
    onDoneRef.current = onDone;
    inputValueRef.current = inputValue;
  });

  // Story 6.2/6.4/6.5 (FORM-230/FORM-233/FORM-234): the mic (spine AD-19 "Client") --
  // `web/src/speech/` is the only Speech SDK boundary; this component only ever calls its hook.
  // `onAutoSend` is `sendMessage` below (a function declaration, so it's hoisted and safe to
  // reference here) -- the one send path, shared by a tap on Send and a mic that just stopped.
  const getInputText = useCallback(() => inputValueRef.current, []);
  const mic = useMicRecognition({
    enabled: micEnabled,
    getText: getInputText,
    setText: setInputValue,
    onAutoSend: sendMessage,
  });

  useEffect(() => {
    let current = true;
    getChatHistory(draftId).then(
      (history) => {
        if (!current) return;
        setMessages(fromHistory(history));
      },
      () => {
        if (current) setHistoryError(true);
      },
    );
    return () => {
      current = false;
    };
  }, [draftId]);

  useEffect(() => {
    const list = listRef.current;
    if (list) list.scrollTop = list.scrollHeight;
  }, [messages]);

  // Story 6.5 (FORM-234, FR62/AD-19): the one send path, called both by a typed Send (via
  // `handleSend` below, reading the message box) and by the mic itself the instant a session
  // stops having heard real speech (`onAutoSend` above) -- same throttle, lock and MCP tools, and
  // the box clears (or, on a refusal, keeps its text) exactly as it does either way.
  function sendMessage(rawText: string) {
    const text = rawText.trim();
    if (!text || turnActive || !canSend || throttleSeconds !== null) return;
    // Sending stops listening (EXPERIENCE.md "Listening"): a session in progress must not keep
    // recognising into a message that's already gone. A no-op when this send *is* the mic's own
    // auto-send -- its session has already stopped by the time this runs.
    mic.stop();
    const requestDraftId = draftIdRef.current;
    const isCurrentDraft = () => draftIdRef.current === requestDraftId;

    setInputValue("");
    const userBubbleId = nextBubbleId();
    const aiBubbleId = nextBubbleId();
    setMessages((prev) => [
      ...prev,
      { id: userBubbleId, role: "user", text },
      { id: aiBubbleId, role: "assistant", text: "", streaming: true },
    ]);
    setTurnActive(true);
    onTurnActiveChangeRef.current(true);

    function finish(finalText: string | null) {
      if (!isCurrentDraft()) return;
      setMessages((prev) =>
        prev.map((bubble) =>
          bubble.id === aiBubbleId
            ? { ...bubble, text: finalText ?? bubble.text, streaming: false }
            : bubble,
        ),
      );
      setTurnActive(false);
      onTurnActiveChangeRef.current(false);
    }

    function handleEvent(event: ChatEvent) {
      if (!isCurrentDraft()) return;
      if (event.type === "delta") {
        setMessages((prev) =>
          prev.map((bubble) =>
            bubble.id === aiBubbleId
              ? { ...bubble, text: bubble.text + event.text }
              : bubble,
          ),
        );
      } else if (event.type === "done") {
        setMessages((prev) => {
          const bubble = prev.find((b) => b.id === aiBubbleId);
          if (bubble) setAnnouncement(bubble.text);
          return prev;
        });
        finish(null);
        onDoneRef.current();
      } else if (event.type === "error") {
        setAnnouncement(strings.workspace.chatFailureMessage);
        finish(strings.workspace.chatFailureMessage);
      }
    }

    sendChat(draftId, text, handleEvent).catch((error: unknown) => {
      if (!isCurrentDraft()) return;
      if (error instanceof ThrottledError) {
        // Refused before the turn ever started (Story 4.8: no lock taken, nothing counted) --
        // drop the optimistic bubbles and give her text back, so nothing is lost, and show the
        // countdown instead of the fixed failure message (that's reserved for a real failure).
        setMessages((prev) =>
          prev.filter(
            (bubble) => bubble.id !== userBubbleId && bubble.id !== aiBubbleId,
          ),
        );
        setTurnActive(false);
        onTurnActiveChangeRef.current(false);
        setInputValue(text);
        startThrottleCountdown(error.retryAfterSeconds);
        return;
      }
      setAnnouncement(strings.workspace.chatFailureMessage);
      finish(strings.workspace.chatFailureMessage);
    });
  }

  function handleSend() {
    sendMessage(inputValue);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "Enter" || event.key === "ArrowUp") {
      event.preventDefault();
      handleSend();
    }
  }

  // Story 6.4 (FORM-233, FR61, UX-DR44): a tap/click, or a Space/Enter keydown while the mic has
  // focus, toggles -- starts a session if idle, stops it (triggering the mic's own auto-send,
  // FR62) if listening. `event.repeat` guards a held key firing `keydown` repeatedly;
  // `preventDefault` on Space/Enter stops the button from also "clicking" (a second, redundant
  // toggle) and the page from scrolling on Space.
  function handleMicClick() {
    mic.toggle();
  }
  function handleMicKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (event.key !== " " && event.key !== "Enter") return;
    if (event.repeat) return;
    event.preventDefault();
    mic.toggle();
  }

  // Story 4.8: throttling never disables the input -- it stays typeable throughout (spec I/O
  // matrix) -- only the Send button reacts to it.
  const inputDisabled = !canSend || turnActive;
  const sendDisabled = buttonState !== "ready" || inputValue.trim() === "";
  const micCaption = mic.error ? micCaptionFor(mic.error) : null;
  const placeholder = canSend
    ? strings.workspace.chatPlaceholder
    : strings.workspace.chatLocklessPlaceholder;

  return (
    <div className="chat-panel">
      <div className="chat-panel__messages" ref={listRef}>
        {historyError && (
          <p className="chat-panel__error">
            {strings.workspace.chatHistoryLoadError}
          </p>
        )}
        {messages.map((bubble) => (
          <div
            key={bubble.id}
            className={
              bubble.role === "user"
                ? "chat-bubble chat-bubble--user"
                : "chat-bubble chat-bubble--ai"
            }
          >
            {bubble.role === "assistant" && (
              <span className="chat-bubble__label">
                {strings.workspace.chatAiLabel}
              </span>
            )}
            <span className="chat-bubble__text">{bubble.text}</span>
            {bubble.streaming && (
              <span className="chat-bubble__typing" aria-hidden="true">
                <span className="chat-bubble__caret" />
                <span className="chat-bubble__dots">
                  <span />
                  <span />
                  <span />
                </span>
              </span>
            )}
          </div>
        ))}
      </div>
      {/* AI bubble arrival, announced politely once (not per delta chunk), EXPERIENCE.md
          Accessibility. */}
      <div aria-live="polite" className="visually-hidden">
        {announcement}
      </div>
      <div className="chat-panel__input-row">
        <input
          type="text"
          className="chat-panel__input"
          value={inputValue}
          onChange={(event) => setInputValue(event.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={inputDisabled}
          aria-label={strings.workspace.chatPlaceholder}
        />
        <button
          type="button"
          className={
            mic.listening
              ? "chat-panel__mic chat-panel__mic--listening"
              : "chat-panel__mic"
          }
          disabled={!micEnabled}
          aria-pressed={mic.listening}
          aria-label={
            mic.listening
              ? strings.workspace.micStopAndSend
              : strings.workspace.micStartSpeaking
          }
          onClick={handleMicClick}
          onKeyDown={handleMicKeyDown}
        >
          {mic.listening ? (
            <span className="chat-panel__mic-listening">
              {strings.workspace.micListening}
              <span className="chat-panel__mic-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </span>
            </span>
          ) : (
            <MicIcon />
          )}
        </button>
        <button
          type="button"
          className={
            buttonState === "throttled"
              ? "chat-panel__send chat-panel__send--throttled"
              : "chat-panel__send"
          }
          onClick={handleSend}
          disabled={sendDisabled}
          aria-label={
            buttonState === "throttled" ? undefined : strings.workspace.chatSend
          }
          aria-live="polite"
        >
          {buttonState === "throttled"
            ? strings.workspace.chatWait(throttleSeconds ?? 0)
            : "↑"}
        </button>
      </div>
      {/* UX-DR45: never red, sits under the input; announced politely since it's the only
          feedback a blocked/unavailable/no-speech session gets. */}
      {micCaption && (
        <p className="chat-panel__mic-caption" aria-live="polite">
          {micCaption}
        </p>
      )}
    </div>
  );
}
