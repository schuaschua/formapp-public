// Story 6.2 (FORM-230, spine AD-19): `tokenCache` owns the browser's cached Speech token. Mocks
// `../api/client`'s `getSpeechToken` -- never a real Azure or network call.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getSpeechTokenMock = vi.fn();

vi.mock("../api/client", () => ({
  getSpeechToken: (...args: unknown[]) => getSpeechTokenMock(...args),
}));

async function loadTokenCache() {
  vi.resetModules();
  return import("./tokenCache");
}

function tokenExpiringIn(ms: number) {
  return {
    token: "aad#resource-id#synthetic-entra-token",
    authMode: "aad",
    region: "southeastasia",
    endpoint: "https://cog-sample-demo-sea.cognitiveservices.azure.com",
    voice: "en-SG-LunaNeural",
    locale: "en-SG",
    expiresAt: new Date(Date.now() + ms).toISOString(),
  };
}

describe("6.2 speech/tokenCache", () => {
  beforeEach(() => {
    getSpeechTokenMock.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("mints once and reuses the cached token while it's fresh", async () => {
    getSpeechTokenMock.mockResolvedValue(tokenExpiringIn(10 * 60 * 1000));
    const { currentSpeechToken } = await loadTokenCache();

    const first = await currentSpeechToken();
    const second = await currentSpeechToken();

    expect(second).toEqual(first);
    expect(getSpeechTokenMock).toHaveBeenCalledOnce();
  });

  it("refreshes before expires_at: a token already inside the 2-minute window is re-minted on the very next call", async () => {
    getSpeechTokenMock
      .mockResolvedValueOnce(tokenExpiringIn(90 * 1000))
      .mockResolvedValueOnce(tokenExpiringIn(10 * 60 * 1000));
    const { currentSpeechToken } = await loadTokenCache();

    await currentSpeechToken();
    await currentSpeechToken();

    expect(getSpeechTokenMock).toHaveBeenCalledTimes(2);
  });

  it("a token well outside the refresh window is not re-minted", async () => {
    getSpeechTokenMock.mockResolvedValue(tokenExpiringIn(10 * 60 * 1000));
    const { currentSpeechToken } = await loadTokenCache();

    await currentSpeechToken();
    await currentSpeechToken();
    await currentSpeechToken();

    expect(getSpeechTokenMock).toHaveBeenCalledOnce();
  });

  it("propagates a mint failure and never caches it", async () => {
    getSpeechTokenMock.mockRejectedValueOnce(new Error("speech_unavailable"));
    const { currentSpeechToken } = await loadTokenCache();

    await expect(currentSpeechToken()).rejects.toThrow("speech_unavailable");

    getSpeechTokenMock.mockResolvedValueOnce(tokenExpiringIn(10 * 60 * 1000));
    await expect(currentSpeechToken()).resolves.toMatchObject({
      locale: "en-SG",
    });
    expect(getSpeechTokenMock).toHaveBeenCalledTimes(2);
  });
});
