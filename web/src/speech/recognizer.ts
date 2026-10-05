// FORM-230/FORM-233 (spine AD-19 "Client"): the only file in the web app that constructs the
// Azure Speech SDK's recognizer -- every other file, including `useMicRecognition.ts` next to it,
// reaches speech only through `startMic` below. One recognition per tap-on/tap-off of the mic:
// continuous recognition that stops itself after about 10 seconds with no `recognizing`/
// `recognized` event, or after 2 minutes total (FR61, owner change 2026-09-28), `recognizing`
// giving the live hypothesis and `recognized` finalising each phrase. Nothing here stores or logs
// audio or interim text (AD-19, security.md rule 2); the recognised words only ever reach the
// caller's `onText`, which `useMicRecognition` puts straight into the message box for her to
// check, and whether this session heard anything only ever reaches `onStopped`'s argument.

import * as SpeechSDK from "microsoft-cognitiveservices-speech-sdk";
import { currentSpeechToken } from "./tokenCache";

/** The three captions UX-DR45 defines; `useMicRecognition` maps each to its exact string. */
export type MicErrorReason = "blocked" | "unavailable" | "no_speech";

export type MicSession = {
  /** Ends this session: tapped off, Send became disabled under it, or a new session started. */
  stop: () => void;
};

export type StartMicOptions = {
  /** The full recognised text so far this session (finalised phrases plus the live hypothesis),
   * called again every time it changes. Never includes anything from before this session started --
   * `useMicRecognition` adds that back. */
  onText: (text: string) => void;
  /** Called at most once, only when the session ends for a reason she should see a caption for
   * (UX-DR45): the mic was blocked, Speech is unavailable, or nothing was recognised the whole
   * session. Never called for a session that heard real speech. */
  onError: (reason: MicErrorReason) => void;
  /** Called exactly once, once the session has fully ended, however it ended (tap-off, silence,
   * the 2-minute cap, an error). `heardSpeech` is true only if at least one phrase was recognised
   * this session -- the caller's one signal for whether to auto-send (FR62), never inferred from
   * the message box's own contents (which may already carry typed text from before this session). */
  onStopped: (heardSpeech: boolean) => void;
};

// FR61 (owner change 2026-09-28, supersedes FR57's 60-second cap): a session stops itself after
// about 10 seconds with no `recognizing`/`recognized` event, reset on each such event, or after
// 2 minutes total, whichever comes first.
const SILENCE_LIMIT_MS = 5_000; // owner change 2026-09-28 (was 10 s, then 3 s)
const TOTAL_LIMIT_MS = 120_000;

function isPermissionDenial(details: string): boolean {
  // The SDK/browser surface a mic denial as a plain string (a DOMException's name or message,
  // e.g. "NotAllowedError: Permission denied"), not a dedicated CancellationErrorCode -- so this
  // is the one place that pattern-matches it, never `web/src/pages/**`.
  return /notallowed|permission/i.test(details);
}

/**
 * Starts one continuous-recognition session against the default microphone. Resolves once the SDK
 * has genuinely started listening (or already failed, in which case `onError`/`onStopped` have
 * already fired and the returned `stop` is a no-op).
 */
export async function startMic(options: StartMicOptions): Promise<MicSession> {
  const { onText, onError, onStopped } = options;
  let finalized = "";
  let heardSpeech = false;
  let ended = false;
  let recognizer: SpeechSDK.SpeechRecognizer | null = null;
  let silenceTimer: ReturnType<typeof setTimeout> | null = null;
  let totalTimer: ReturnType<typeof setTimeout> | null = null;

  function clearTimers(): void {
    if (silenceTimer !== null) {
      clearTimeout(silenceTimer);
      silenceTimer = null;
    }
    if (totalTimer !== null) {
      clearTimeout(totalTimer);
      totalTimer = null;
    }
  }

  // Reset on every `recognizing`/`recognized` event (FR61): about 10 seconds with none of those
  // stops the session. Not started until recognition genuinely begins.
  function resetSilenceTimer(): void {
    if (silenceTimer !== null) clearTimeout(silenceTimer);
    silenceTimer = setTimeout(() => {
      finish(heardSpeech ? null : "no_speech");
    }, SILENCE_LIMIT_MS);
  }

  function finish(reason: MicErrorReason | null): void {
    if (ended) return;
    ended = true;
    clearTimers();
    const closing = recognizer;
    recognizer = null;
    if (closing) {
      closing.stopContinuousRecognitionAsync(
        () => closing.close(),
        () => closing.close(),
      );
    }
    if (reason) onError(reason);
    onStopped(heardSpeech);
  }

  const noOpSession: MicSession = { stop: () => finish(null) };

  let token;
  try {
    token = await currentSpeechToken();
  } catch {
    finish("unavailable");
    return noOpSession;
  }

  // Built as its own `const` (never reassigned), so every use below stays non-null without
  // re-narrowing `recognizer` (only `finish()`'s null-out needs that shared, reassignable `let`).
  let builtRecognizer: SpeechSDK.SpeechRecognizer;
  try {
    // AD-19/FORM-230: `auth_mode: "aad"` is the only mode this story builds (a `sts` fallback
    // needs its own owner-approved story); the token already carries the `aad#<resourceId>#`
    // prefix the SDK expects.
    const speechConfig = SpeechSDK.SpeechConfig.fromAuthorizationToken(
      token.token,
      token.region,
    );
    speechConfig.speechRecognitionLanguage = token.locale;
    const audioConfig = SpeechSDK.AudioConfig.fromDefaultMicrophoneInput();
    builtRecognizer = new SpeechSDK.SpeechRecognizer(speechConfig, audioConfig);
  } catch (error) {
    finish(isPermissionDenial(String(error)) ? "blocked" : "unavailable");
    return noOpSession;
  }
  recognizer = builtRecognizer;

  builtRecognizer.recognizing = (_sender, event) => {
    if (ended) return;
    resetSilenceTimer();
    onText([finalized, event.result.text].filter(Boolean).join(" "));
  };
  builtRecognizer.recognized = (_sender, event) => {
    if (ended) return;
    resetSilenceTimer();
    if (
      event.result.reason === SpeechSDK.ResultReason.RecognizedSpeech &&
      event.result.text
    ) {
      heardSpeech = true;
      finalized = [finalized, event.result.text].filter(Boolean).join(" ");
      onText(finalized);
    }
  };
  builtRecognizer.canceled = (_sender, event) => {
    if (event.reason !== SpeechSDK.CancellationReason.Error) {
      finish(heardSpeech ? null : "no_speech");
      return;
    }
    finish(isPermissionDenial(event.errorDetails) ? "blocked" : "unavailable");
  };
  builtRecognizer.sessionStopped = () => {
    finish(heardSpeech ? null : "no_speech");
  };

  return new Promise<MicSession>((resolve) => {
    builtRecognizer.startContinuousRecognitionAsync(
      () => {
        if (ended) {
          resolve(noOpSession);
          return;
        }
        resetSilenceTimer();
        totalTimer = setTimeout(() => {
          finish(heardSpeech ? null : "no_speech");
        }, TOTAL_LIMIT_MS);
        resolve({ stop: () => finish(heardSpeech ? null : "no_speech") });
      },
      (error) => {
        finish(isPermissionDenial(error) ? "blocked" : "unavailable");
        resolve(noOpSession);
      },
    );
  });
}
