// FORM-230/FORM-233/FORM-234 (spine AD-19 "Client"): the one React seam onto the mic. `ChatPanel`
// calls this hook and never touches `recognizer.ts` or `tokenCache.ts` directly (this file is the
// only other place inside `web/src/speech/` that isn't the SDK boundary itself). Owns session
// state, the toggle (tap-on/tap-off, FR61), the "added after anything already typed" merge (spec
// Flow 5), mapping every failure to one of the three captions UX-DR45 defines, and telling the
// caller when to auto-send (FR62) -- once, only for a session that heard real speech, and never
// for the silent `stop()` used when Send disables mid-session or is pressed directly.

import { useCallback, useEffect, useRef, useState } from "react";
import { startMic, type MicErrorReason, type MicSession } from "./recognizer";

export type { MicErrorReason };

export type UseMicRecognitionOptions = {
  /** The mic follows Send (AD-19): a session that starts while this is false never reaches the
   * SDK, and a session already in progress is stopped (without auto-sending, FR58) the instant
   * this turns false. */
  enabled: boolean;
  /** Reads the message box's current text, once, at the start of a session -- her words are added
   * after anything already typed (spec Flow 5), never replacing it. */
  getText: () => string;
  /** Replaces the message box's text with the merged (typed + spoken) text; called live as she
   * speaks, and never called again once the session ends. */
  setText: (text: string) => void;
  /** Called once a session stops having recognised real speech (FR62), with the full merged text
   * (anything already typed, plus everything recognised this session) exactly as `setText` last
   * set it. The caller sends it through the normal chat turn. Never called for a session that
   * heard nothing, and never called for the silent `stop()` (Send disabling mid-session, or Send
   * pressed directly -- its own click already sends the current text). */
  onAutoSend: (text: string) => void;
};

export type UseMicRecognitionResult = {
  /** True while the mic is the "Listening" pill (DESIGN.md "Mic button"). */
  listening: boolean;
  /** The caption to show under the input (UX-DR45), or `null`; cleared at the start of the next
   * session. */
  error: MicErrorReason | null;
  /** Tap/click, or Space/Enter keydown, on the mic (UX-DR44, FR61): starts a session if idle,
   * stops the current one (triggering `onAutoSend` if it heard speech) if listening. A no-op
   * while disabled. */
  toggle: () => void;
  /** Stops the current session, if any, without ever auto-sending -- however much it heard. Used
   * when Send disables mid-session (AD-19/FR58) and when Send is pressed directly while listening
   * (that click already sends the current box; this only silences the mic). A no-op with nothing
   * to end. */
  stop: () => void;
};

/** The message box's live text is `base + " " + spokenSoFar`, never a leading/trailing space when
 * either half is empty. */
function merge(base: string, spokenSoFar: string): string {
  return [base, spokenSoFar].filter(Boolean).join(" ");
}

export function useMicRecognition({
  enabled,
  getText,
  setText,
  onAutoSend,
}: UseMicRecognitionOptions): UseMicRecognitionResult {
  const [listening, setListening] = useState(false);
  const [error, setError] = useState<MicErrorReason | null>(null);
  const sessionRef = useRef<MicSession | null>(null);
  const baseTextRef = useRef("");
  const spokenRef = useRef("");
  // True from the moment a tap/keydown starts a session until it's fully stopped -- distinct from
  // `sessionRef` itself, which stays null until the SDK resolves (see the release-before-ready
  // race below).
  const sessionActiveRef = useRef(false);
  // Set just before a silent `stop()` ends the current session, so its `onStopped` (which may
  // fire synchronously, inside the same call) knows not to auto-send even though it heard speech.
  const suppressAutoSendRef = useRef(false);
  const onAutoSendRef = useRef(onAutoSend);
  useEffect(() => {
    onAutoSendRef.current = onAutoSend;
  });

  const endSession = useCallback((suppressAutoSend: boolean) => {
    if (!sessionActiveRef.current) return;
    sessionActiveRef.current = false;
    suppressAutoSendRef.current = suppressAutoSend;
    sessionRef.current?.stop();
  }, []);

  const stop = useCallback(() => {
    endSession(true);
  }, [endSession]);

  const toggle = useCallback(() => {
    if (!enabled) return;
    if (sessionActiveRef.current) {
      endSession(false);
      return;
    }
    sessionActiveRef.current = true;
    suppressAutoSendRef.current = false;
    setListening(true);
    setError(null);
    baseTextRef.current = getText();
    spokenRef.current = "";
    startMic({
      onText: (spokenSoFar) => {
        spokenRef.current = spokenSoFar;
        setText(merge(baseTextRef.current, spokenSoFar));
      },
      onError: (reason) => {
        setError(reason);
      },
      onStopped: (heardSpeech) => {
        sessionRef.current = null;
        const wasSuppressed = suppressAutoSendRef.current;
        sessionActiveRef.current = false;
        suppressAutoSendRef.current = false;
        setListening(false);
        if (heardSpeech && !wasSuppressed) {
          onAutoSendRef.current(merge(baseTextRef.current, spokenRef.current));
        }
      },
    })
      .then((session) => {
        sessionRef.current = session;
        // She already tapped off (or Send became disabled) before the SDK finished starting up.
        if (!sessionActiveRef.current) session.stop();
      })
      .catch(() => {
        // startMic itself never rejects (every failure path resolves a no-op session after
        // calling onError/onStopped) -- this is only a defensive backstop.
        sessionActiveRef.current = false;
        setListening(false);
      });
  }, [enabled, getText, setText, endSession]);

  // AD-19: the mic follows Send -- a session in progress is cut short, without auto-sending
  // (FR58), the instant Send disables.
  useEffect(() => {
    if (!enabled) stop();
  }, [enabled, stop]);

  return { listening, error, toggle, stop };
}
