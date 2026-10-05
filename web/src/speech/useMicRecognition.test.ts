// Story 6.2/6.4/6.5 (FORM-230/FORM-233/FORM-234, spine AD-19 "Client"): the hook `ChatPanel`
// calls -- the toggle (tap/click or Space/Enter keydown starts, the same again stops, FR61), the
// "after anything already typed" merge, mic-follows-Send, and auto-send once a session that heard
// real speech stops (FR62), never for the silent `stop()` (Send disabled mid-session, or Send
// pressed directly -- ChatPanel's own click already sends). `./recognizer` (the real Speech SDK
// boundary) is mocked -- this test never touches the SDK or a microphone.
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { MicErrorReason, MicSession, StartMicOptions } from "./recognizer";

const startMicMock = vi.fn<(options: StartMicOptions) => Promise<MicSession>>();
vi.mock("./recognizer", () => ({
  startMic: (options: StartMicOptions) => startMicMock(options),
}));

async function loadHook() {
  return import("./useMicRecognition");
}

/** A session driver mirroring the real `recognizer.ts`'s contract: `speak` calls `onText` and
 * marks this session as having heard real speech, so its `stop()` reports that through
 * `onStopped`, exactly like a `recognized` event finishing a real session would. */
type SessionDriver = {
  options: StartMicOptions;
  session: MicSession;
  speak: (text: string) => void;
};

let currentSession: SessionDriver | null = null;

function mockStartMic() {
  startMicMock.mockImplementation((options) => {
    let heardSpeech = false;
    const session: MicSession = { stop: () => options.onStopped(heardSpeech) };
    currentSession = {
      options,
      session,
      speak: (text: string) => {
        heardSpeech = true;
        options.onText(text);
      },
    };
    return Promise.resolve(session);
  });
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("6.4/6.5 speech/useMicRecognition", () => {
  beforeEach(() => {
    startMicMock.mockReset();
    currentSession = null;
  });

  it("toggle is a no-op while disabled (mic follows Send, AD-19)", async () => {
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: false,
        getText: () => "",
        setText: vi.fn(),
        onAutoSend: vi.fn(),
      }),
    );

    act(() => result.current.toggle());

    expect(startMicMock).not.toHaveBeenCalled();
    expect(result.current.listening).toBe(false);
  });

  it("toggle begins listening and appends spoken words after anything already typed", async () => {
    mockStartMic();
    const setText = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "existing customer",
        setText,
        onAutoSend: vi.fn(),
      }),
    );

    await act(async () => {
      result.current.toggle();
    });

    expect(result.current.listening).toBe(true);
    act(() => currentSession?.speak("ally 1994"));
    expect(setText).toHaveBeenLastCalledWith("existing customer ally 1994");
  });

  it("an empty box gets the spoken words with no leading space", async () => {
    mockStartMic();
    const setText = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "",
        setText,
        onAutoSend: vi.fn(),
      }),
    );

    await act(async () => {
      result.current.toggle();
    });
    act(() => currentSession?.speak("hello"));

    expect(setText).toHaveBeenLastCalledWith("hello");
  });

  it("never auto-sends while still listening: speaking only ever calls setText", async () => {
    mockStartMic();
    const setText = vi.fn();
    const onAutoSend = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "",
        setText,
        onAutoSend,
      }),
    );

    await act(async () => {
      result.current.toggle();
    });
    act(() => currentSession?.speak("her budget is 200 a month"));

    expect(setText).toHaveBeenCalledWith("her budget is 200 a month");
    expect(onAutoSend).not.toHaveBeenCalled();
  });

  it("toggling off after hearing speech auto-sends the merged text once (FR62)", async () => {
    mockStartMic();
    const onAutoSend = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "existing customer",
        setText: vi.fn(),
        onAutoSend,
      }),
    );
    await act(async () => {
      result.current.toggle();
    });
    act(() => currentSession?.speak("ally 1994"));

    act(() => result.current.toggle());

    expect(result.current.listening).toBe(false);
    expect(onAutoSend).toHaveBeenCalledExactlyOnceWith(
      "existing customer ally 1994",
    );
  });

  it("toggling off after hearing nothing never auto-sends (FR62)", async () => {
    mockStartMic();
    const onAutoSend = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "",
        setText: vi.fn(),
        onAutoSend,
      }),
    );
    await act(async () => {
      result.current.toggle();
    });

    act(() => result.current.toggle());

    expect(result.current.listening).toBe(false);
    expect(onAutoSend).not.toHaveBeenCalled();
  });

  it("an auto-stop from the recognizer itself (silence or the 2-minute cap) also auto-sends", async () => {
    mockStartMic();
    const onAutoSend = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "existing customer",
        setText: vi.fn(),
        onAutoSend,
      }),
    );
    await act(async () => {
      result.current.toggle();
    });
    act(() => currentSession?.speak("her budget"));

    // The recognizer ends the session on its own (silence/2-minute cap) -- not through toggle().
    act(() => currentSession?.options.onStopped(true));

    expect(result.current.listening).toBe(false);
    expect(onAutoSend).toHaveBeenCalledExactlyOnceWith(
      "existing customer her budget",
    );
  });

  it("stop() ends a listening session without ever auto-sending, even though it heard speech", async () => {
    mockStartMic();
    const onAutoSend = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "",
        setText: vi.fn(),
        onAutoSend,
      }),
    );
    await act(async () => {
      result.current.toggle();
    });
    act(() => currentSession?.speak("hello"));

    act(() => result.current.stop());

    expect(result.current.listening).toBe(false);
    expect(onAutoSend).not.toHaveBeenCalled();
  });

  it("Send disabling mid-session stops it without auto-sending, even though it heard speech (AD-19/FR58)", async () => {
    mockStartMic();
    const onAutoSend = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result, rerender } = renderHook(
      ({ enabled }: { enabled: boolean }) =>
        useMicRecognition({
          enabled,
          getText: () => "",
          setText: vi.fn(),
          onAutoSend,
        }),
      { initialProps: { enabled: true } },
    );
    await act(async () => {
      result.current.toggle();
    });
    act(() => currentSession?.speak("hello"));
    expect(result.current.listening).toBe(true);

    act(() => rerender({ enabled: false }));

    expect(result.current.listening).toBe(false);
    expect(onAutoSend).not.toHaveBeenCalled();
  });

  it("a caption reason from the session is exposed as error", async () => {
    mockStartMic();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "",
        setText: vi.fn(),
        onAutoSend: vi.fn(),
      }),
    );
    await act(async () => {
      result.current.toggle();
    });

    act(() => currentSession?.options.onError("blocked" as MicErrorReason));

    expect(result.current.error).toBe("blocked");
  });

  it("the next session clears a previous caption", async () => {
    mockStartMic();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "",
        setText: vi.fn(),
        onAutoSend: vi.fn(),
      }),
    );
    await act(async () => {
      result.current.toggle();
    });
    act(() => currentSession?.options.onError("no_speech" as MicErrorReason));
    expect(result.current.error).toBe("no_speech");
    act(() => result.current.stop());

    await act(async () => {
      result.current.toggle();
    });

    expect(result.current.error).toBeNull();
  });

  it("toggling off before the SDK finishes starting stops it as soon as it's ready, without auto-sending", async () => {
    const stop = vi.fn();
    const pending = deferred<MicSession>();
    startMicMock.mockImplementation(() => pending.promise);
    const onAutoSend = vi.fn();
    const { useMicRecognition } = await loadHook();
    const { result } = renderHook(() =>
      useMicRecognition({
        enabled: true,
        getText: () => "",
        setText: vi.fn(),
        onAutoSend,
      }),
    );

    act(() => result.current.toggle());
    act(() => result.current.toggle());
    await act(async () => {
      pending.resolve({ stop });
      await pending.promise;
    });

    expect(stop).toHaveBeenCalledOnce();
    expect(onAutoSend).not.toHaveBeenCalled();
  });
});
