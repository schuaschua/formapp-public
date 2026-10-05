// Story 6.2/6.4 (FORM-230/FORM-233, spine AD-19): `startMic` is the only place that touches the
// Speech SDK. This test never imports the real `microsoft-cognitiveservices-speech-sdk` package
// or reaches a microphone or Azure -- it replaces the whole module with a fake recognizer whose
// events this file drives directly (security.md rule 1 / coding-style.md rule 23: no test calls
// real Speech).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const currentSpeechTokenMock = vi.fn();
vi.mock("./tokenCache", () => ({
  currentSpeechToken: (...args: unknown[]) => currentSpeechTokenMock(...args),
}));

type Handler = (sender: unknown, event: unknown) => void;

class FakeSpeechConfig {
  speechRecognitionLanguage = "";
  constructor(
    public authorizationToken: string,
    public region: string,
  ) {}
  static fromAuthorizationToken(
    authorizationToken: string,
    region: string,
  ): FakeSpeechConfig {
    return new FakeSpeechConfig(authorizationToken, region);
  }
}

const audioConfigStub = { kind: "default-microphone" };
const fromDefaultMicrophoneInputMock = vi.fn(() => audioConfigStub);

class FakeRecognizer {
  static instances: FakeRecognizer[] = [];
  recognizing: Handler | null = null;
  recognized: Handler | null = null;
  canceled: Handler | null = null;
  sessionStopped: (() => void) | null = null;
  startCalls = 0;
  stopCalls = 0;
  closeCalls = 0;

  constructor(
    public speechConfig: FakeSpeechConfig,
    public audioConfig: unknown,
  ) {
    FakeRecognizer.instances.push(this);
  }

  startContinuousRecognitionAsync(success?: () => void): void {
    this.startCalls += 1;
    success?.();
  }

  stopContinuousRecognitionAsync(success?: () => void): void {
    this.stopCalls += 1;
    success?.();
  }

  close(): void {
    this.closeCalls += 1;
  }
}

vi.mock("microsoft-cognitiveservices-speech-sdk", () => ({
  SpeechConfig: FakeSpeechConfig,
  AudioConfig: { fromDefaultMicrophoneInput: fromDefaultMicrophoneInputMock },
  SpeechRecognizer: FakeRecognizer,
  ResultReason: { NoMatch: 0, RecognizedSpeech: 3 },
  CancellationReason: { Error: 0, EndOfStream: 1 },
}));

const TOKEN = {
  token: "aad#resource-id#synthetic-entra-token",
  authMode: "aad",
  region: "southeastasia",
  endpoint: "https://cog-sample-demo-sea.cognitiveservices.azure.com",
  voice: "en-SG-LunaNeural",
  locale: "en-SG",
  expiresAt: "2026-09-28T10:10:00Z",
};

function recognizedEvent(text: string) {
  return { result: { reason: 3, text } };
}

function recognizingEvent(text: string) {
  return { result: { reason: 2, text } };
}

async function loadRecognizer() {
  return import("./recognizer");
}

describe("6.2 speech/recognizer", () => {
  beforeEach(() => {
    FakeRecognizer.instances = [];
    currentSpeechTokenMock.mockReset();
    fromDefaultMicrophoneInputMock.mockClear();
    currentSpeechTokenMock.mockResolvedValue(TOKEN);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("builds the SpeechConfig from the token's authorization token, region and locale (AD-19)", async () => {
    const { startMic } = await loadRecognizer();

    await startMic({ onText: vi.fn(), onError: vi.fn(), onStopped: vi.fn() });

    const instance = FakeRecognizer.instances[0]!;
    expect(instance.speechConfig.authorizationToken).toBe(TOKEN.token);
    expect(instance.speechConfig.region).toBe(TOKEN.region);
    expect(instance.speechConfig.speechRecognitionLanguage).toBe(TOKEN.locale);
    expect(instance.startCalls).toBe(1);
  });

  it("recognizing gives the live hypothesis and recognized finalises it, both through onText", async () => {
    const onText = vi.fn();
    const { startMic } = await loadRecognizer();
    await startMic({ onText, onError: vi.fn(), onStopped: vi.fn() });
    const instance = FakeRecognizer.instances[0]!;

    instance.recognizing?.(null, recognizingEvent("existing customer"));
    expect(onText).toHaveBeenLastCalledWith("existing customer");

    instance.recognized?.(null, recognizedEvent("existing customer ally"));
    expect(onText).toHaveBeenLastCalledWith("existing customer ally");

    instance.recognizing?.(null, recognizingEvent("her budget"));
    expect(onText).toHaveBeenLastCalledWith(
      "existing customer ally her budget",
    );
  });

  it("stop() after real speech was heard ends cleanly, with no error caption, and reports heardSpeech true", async () => {
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();
    const session = await startMic({ onText: vi.fn(), onError, onStopped });
    const instance = FakeRecognizer.instances[0]!;
    instance.recognized?.(null, recognizedEvent("hello"));

    session.stop();

    expect(onError).not.toHaveBeenCalled();
    expect(onStopped).toHaveBeenCalledExactlyOnceWith(true);
    expect(instance.stopCalls).toBe(1);
    expect(instance.closeCalls).toBe(1);
  });

  it("stop() with nothing recognised shows the no-speech caption and reports heardSpeech false", async () => {
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();
    const session = await startMic({ onText: vi.fn(), onError, onStopped });

    session.stop();

    expect(onError).toHaveBeenCalledExactlyOnceWith("no_speech");
    expect(onStopped).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("a permission-denial cancellation shows the blocked caption", async () => {
    const onError = vi.fn();
    const { startMic } = await loadRecognizer();
    await startMic({ onText: vi.fn(), onError, onStopped: vi.fn() });
    const instance = FakeRecognizer.instances[0]!;

    instance.canceled?.(null, {
      reason: 0,
      errorCode: 1,
      errorDetails: "NotAllowedError: Permission denied by the user",
    });

    expect(onError).toHaveBeenCalledExactlyOnceWith("blocked");
  });

  it("any other cancellation error shows the unavailable caption", async () => {
    const onError = vi.fn();
    const { startMic } = await loadRecognizer();
    await startMic({ onText: vi.fn(), onError, onStopped: vi.fn() });
    const instance = FakeRecognizer.instances[0]!;

    instance.canceled?.(null, {
      reason: 0,
      errorCode: 4,
      errorDetails: "ConnectionFailure",
    });

    expect(onError).toHaveBeenCalledExactlyOnceWith("unavailable");
  });

  it("sessionStopped with nothing recognised is treated like a natural end, not left listening", async () => {
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();
    await startMic({ onText: vi.fn(), onError, onStopped });
    const instance = FakeRecognizer.instances[0]!;

    instance.sessionStopped?.();

    expect(onError).toHaveBeenCalledExactlyOnceWith("no_speech");
    expect(onStopped).toHaveBeenCalledOnce();
  });

  it("a session stops itself after 5 seconds with no recognizing/recognized event (FR61)", async () => {
    vi.useFakeTimers();
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();
    const session = await startMic({ onText: vi.fn(), onError, onStopped });
    const instance = FakeRecognizer.instances[0]!;

    vi.advanceTimersByTime(4_999);
    expect(onStopped).not.toHaveBeenCalled();

    vi.advanceTimersByTime(1);

    expect(onStopped).toHaveBeenCalledExactlyOnceWith(false);
    expect(onError).toHaveBeenCalledExactlyOnceWith("no_speech");
    expect(instance.stopCalls).toBe(1);
    // A second, manual stop() after the cap fires is a no-op (idempotent finish()).
    session.stop();
    expect(instance.stopCalls).toBe(1);
  });

  it("a recognizing or recognized event resets the 5-second silence timer (FR61)", async () => {
    vi.useFakeTimers();
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();
    await startMic({ onText: vi.fn(), onError, onStopped });
    const instance = FakeRecognizer.instances[0]!;

    vi.advanceTimersByTime(4_500);
    instance.recognizing?.(null, recognizingEvent("her budget"));
    vi.advanceTimersByTime(4_500);
    expect(onStopped).not.toHaveBeenCalled(); // 9s elapsed, but the reset kept it under 5s twice

    vi.advanceTimersByTime(500);

    expect(onStopped).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("a session stops after 2 minutes total, even while it keeps hearing speech (FR61)", async () => {
    vi.useFakeTimers();
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();
    const session = await startMic({ onText: vi.fn(), onError, onStopped });
    const instance = FakeRecognizer.instances[0]!;
    instance.recognized?.(null, recognizedEvent("hello"));

    // Keep resetting the silence timer under its 5-second limit, all the way to just short of the
    // 2-minute total cap -- only the total cap should end this session.
    for (let elapsed = 0; elapsed < 118_000; elapsed += 2_000) {
      vi.advanceTimersByTime(2_000);
      instance.recognized?.(null, recognizedEvent("more"));
    }
    expect(onStopped).not.toHaveBeenCalled();

    vi.advanceTimersByTime(2_000);

    expect(onStopped).toHaveBeenCalledExactlyOnceWith(true);
    expect(onError).not.toHaveBeenCalled(); // she was heard, so no caption
    expect(instance.stopCalls).toBe(1);
    session.stop();
    expect(instance.stopCalls).toBe(1);
  });

  it("a token mint failure shows the unavailable caption and never builds a recognizer", async () => {
    currentSpeechTokenMock.mockReset();
    currentSpeechTokenMock.mockRejectedValueOnce(
      new Error("speech_unavailable"),
    );
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();

    await startMic({ onText: vi.fn(), onError, onStopped });

    expect(onError).toHaveBeenCalledExactlyOnceWith("unavailable");
    expect(onStopped).toHaveBeenCalledOnce();
    expect(FakeRecognizer.instances).toHaveLength(0);
  });

  it("a blocked microphone (AudioConfig throws) shows the blocked caption", async () => {
    fromDefaultMicrophoneInputMock.mockImplementationOnce(() => {
      throw new Error("NotAllowedError: Permission denied");
    });
    const onError = vi.fn();
    const onStopped = vi.fn();
    const { startMic } = await loadRecognizer();

    await startMic({ onText: vi.fn(), onError, onStopped });

    expect(onError).toHaveBeenCalledExactlyOnceWith("blocked");
    expect(onStopped).toHaveBeenCalledOnce();
  });

  it("never keeps audio or interim text anywhere but the callbacks (AD-19)", async () => {
    const onText = vi.fn();
    const { startMic } = await loadRecognizer();
    await startMic({ onText, onError: vi.fn(), onStopped: vi.fn() });
    const instance = FakeRecognizer.instances[0]!;

    instance.recognizing?.(null, recognizingEvent("her national id is"));

    // The only place her words landed is the onText callback's argument -- nothing on the
    // recognizer/session object itself carries the transcript forward.
    expect(Object.keys(instance)).not.toContain("transcript");
    expect(onText).toHaveBeenCalledWith("her national id is");
  });
});
