// FORM-230 (spine AD-19 "Client": "it owns the token cache and refreshes before expires_at").
// The one module-scoped cache for the browser Speech token: `recognizer.ts` calls
// `currentSpeechToken` instead of `getSpeechToken` directly, so a second hold of the mic a few
// seconds later never mints a fresh token needlessly, and one minted just before `expires_at`
// is never handed to the SDK.

import { getSpeechToken, type SpeechTokenData } from "../api/client";

// Refresh this long before the token actually expires (mirrors api's own `_EARLY_REFRESH` in
// `adapters/speech/azure.py`): a hold that starts right at the edge never races expiry mid-hold.
const EARLY_REFRESH_MS = 2 * 60 * 1000;

let cached: SpeechTokenData | null = null;

function isFresh(token: SpeechTokenData, now: number): boolean {
  return new Date(token.expiresAt).getTime() - EARLY_REFRESH_MS > now;
}

/**
 * The current Speech token: the cached one while it is still fresh, or a newly minted one
 * otherwise. Propagates whatever `getSpeechToken` throws (an `ApiError`, including the
 * `speech_unavailable` 503, or a network failure) so `recognizer.ts` maps it to the "unavailable"
 * caption (UX-DR45) -- never caches a failure.
 */
export async function currentSpeechToken(): Promise<SpeechTokenData> {
  const now = Date.now();
  if (cached && isFresh(cached, now)) {
    return cached;
  }
  const token = await getSpeechToken();
  cached = token;
  return token;
}

/** Test-only: clears the module-scoped cache so each test starts cold. */
export function resetSpeechTokenCacheForTests(): void {
  cached = null;
}
