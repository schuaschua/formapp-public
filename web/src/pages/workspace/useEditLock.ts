// Story 4.4: acquires the edit lock on mount and renews it every 20s, doubling as the heartbeat
// and the "did I lose it" probe (spec Approach; no push/websocket channel, AD-16) -- modelled on
// `autosave.ts`'s own timer use (real timers, driven by `vi.useFakeTimers()` in tests, never a
// sleep, AD-18). Every open tab runs this, whether or not it currently holds the lock: a plain
// (non-take-over) call is always safe to repeat -- it renews if she holds it, silently acquires it
// if it's free (including once another tab's lock has expired), and otherwise just reports who
// does, without disturbing anything (the CAS in `adapters/db/proposals.py`).

import { useCallback, useEffect, useRef, useState } from "react";
import { lockDraft, type Lock } from "../../api/client";

const HEARTBEAT_MS = 20_000;

// Optimistic until the first response arrives (nothing that reads `lock` renders before the draft
// itself has loaded, so this default is never shown on screen).
const INITIAL_LOCK: Lock = { holder: "you", expiresAt: null };

export type EditLockController = {
  lock: Lock;
  /** Moves the lock to this tab, refused while `ai` holds it live (Story 4.4/4.5, AD-16). */
  takeOver: () => void;
  /** Re-checks the lock right away rather than waiting for the next heartbeat tick -- the
   * workspace calls this the moment a write comes back `409 lock_not_held`, so the read-only
   * state it switches to already knows who holds it (spec matrix "Lost lock mid-edit"). */
  refresh: () => void;
};

/** Wires one draft's edit lock: acquire on mount, renew every 20s (Story 4.4, AD-16). */
export function useEditLock(draftId: string): EditLockController {
  const [lock, setLock] = useState<Lock>(INITIAL_LOCK);
  const draftIdRef = useRef(draftId);
  // A monotonic call id (same idea as `autosave.ts`'s `isCurrentDraft()`): a heartbeat and a
  // take-over/refresh can land close together and resolve out of order, so a response only
  // applies if it's still the most recently issued call -- never a stale one overwriting fresher
  // lock state.
  const latestCallIdRef = useRef(0);

  // A new draft: drop whatever this hook instance still believed about the previous one, the same
  // render-time-reset pattern `Workspace`/`autosave.ts` already use for a changed draftId.
  const [trackedDraftId, setTrackedDraftId] = useState(draftId);
  if (trackedDraftId !== draftId) {
    setTrackedDraftId(draftId);
    setLock(INITIAL_LOCK);
  }

  useEffect(() => {
    draftIdRef.current = draftId;
  }, [draftId]);

  const call = useCallback((takeOver: boolean) => {
    const requestDraftId = draftIdRef.current;
    const callId = (latestCallIdRef.current += 1);
    lockDraft(requestDraftId, { takeOver }).then(
      (result) => {
        if (draftIdRef.current !== requestDraftId) return;
        if (latestCallIdRef.current !== callId) return; // superseded by a later call
        setLock(result);
      },
      () => {
        // A failed lock call (network blip, a 401 the session hook already handles, a 404 sent
        // her back to Drafts already): leave the last known state, the next heartbeat tries again.
      },
    );
  }, []);

  useEffect(() => {
    call(false);
    const timer = setInterval(() => call(false), HEARTBEAT_MS);
    return () => clearInterval(timer);
  }, [draftId, call]);

  const takeOver = useCallback(() => call(true), [call]);
  const refresh = useCallback(() => call(false), [call]);

  return { lock, takeOver, refresh };
}
