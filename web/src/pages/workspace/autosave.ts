// Story 1.10: per-field diff-and-send autosave, revision tracking, the stale-revision silent
// retry, the save-failed/connection-lost banners and the offline queue (spec assumption
// "Retry timing"). Kept as one hook so `Workspace` wires it once and every widget just calls
// `commit(qid, value)` -- on blur for text/number/date, immediately on click for Yes/No, select
// and option-choice controls (DESIGN.md/EXPERIENCE.md "Autosave").

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getDraft, patchAnswers, type Draft } from "../../api/client";

/** The save-status region's text (EXPERIENCE.md "Save status"): blank until the first edit. */
export type SaveStatus = "idle" | "saving" | "saved";

/** At most one system-failure banner at a time (EXPERIENCE.md State Patterns: both share the
 * identical red banner treatment, so one flag covers both). */
export type Banner = "none" | "save-failed" | "offline";

/** A field's last-rejected-value problem: the amber highlight's message (UX-DR43). */
export type FieldProblem = { message: string };

export type AutosaveController = {
  saveStatus: SaveStatus;
  banner: Banner;
  fieldProblems: Record<string, FieldProblem>;
  /** Diff-and-send one field's new value; a true no-op (equal to what's already saved or already
   * queued/in flight) sends nothing at all (AC "leaving a field without changing it"). */
  commit: (questionId: string, value: unknown) => void;
  /** Diff-and-send several fields as one PATCH (Story 2.3: changing P1 drops foreign riders from
   * P2 in the same write). Two sequential `commit()` calls would race into two separate PATCH
   * requests -- the first's `flush()` can start sending before the second's `commit()` runs --
   * so this is the only way to batch a write; a field whose new value is a no-op is left out,
   * like `commit`'s own diff-and-send. */
  commitMany: (patch: Record<string, unknown>) => void;
  /** The banner's "Retry" button: retries right away, without waiting for the scheduled retry. */
  retry: () => void;
  /** Story 3.1: replaces `fieldProblems` wholesale with a fresh `POST .../validate` result -- a
   * clean result ([]) clears every highlight, and it never merges with whatever a prior save
   * already put there, since a fresh Submit is authoritative. */
  reportProblems: (problems: Record<string, FieldProblem>) => void;
  /** FORM-213: merges one field's client-side problem into `fieldProblems` without disturbing any
   * other field's -- `null` clears just that entry. See `WorkspaceUiContextValue`'s own docstring
   * for why this exists alongside `reportProblems`. */
  setFieldProblem: (questionId: string, problem: FieldProblem | null) => void;
};

// No AC gives an exact figure (spec assumption "Retry timing"); real timers, never a sleep in a
// test (AD-18) -- frontend tests drive this with `vi.useFakeTimers()`.
const RETRY_DELAY_MS = 3000;

function sameValue(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) || Array.isArray(b)) {
    return JSON.stringify(a ?? null) === JSON.stringify(b ?? null);
  }
  return Object.is(a ?? null, b ?? null);
}

/**
 * Wires one draft's autosave. `draftId`/`revision`/`answers` come from the workspace's own draft
 * state; `onSaved` is called with every server-confirmed draft so the workspace can update its
 * `active`/`answers`/`revision`/`displayName` straight from the response (spec assumption).
 * `onLockLost` (Story 4.4, AD-16) is called once a write comes back `409 lock_not_held` -- the
 * workspace re-checks the lock right away rather than waiting for the next heartbeat.
 */
export function useAutosave(params: {
  draftId: string;
  revision: number;
  answers: Record<string, unknown>;
  onSaved: (draft: Draft) => void;
  onLockLost?: () => void;
}): AutosaveController {
  const { draftId, revision, answers, onSaved, onLockLost } = params;
  const [saveStatus, setSaveStatus] = useState<SaveStatus>("idle");
  const [banner, setBanner] = useState<Banner>("none");
  const [fieldProblems, setFieldProblems] = useState<
    Record<string, FieldProblem>
  >({});

  // A new draft (Workspace stays mounted across a URL param change, see its own comment): reset
  // this hook's own status the same way `Workspace` resets its state, during render, not an effect
  // (React's documented "adjusting state when a prop changes" pattern -- see coding-style.md's own
  // precedent in Workspace.tsx's `loadedForId`).
  const [trackedDraftId, setTrackedDraftId] = useState(draftId);
  if (trackedDraftId !== draftId) {
    setTrackedDraftId(draftId);
    setSaveStatus("idle");
    setBanner("none");
    setFieldProblems({});
  }

  const revisionRef = useRef(revision);
  const savedRef = useRef(answers);
  const onSavedRef = useRef(onSaved);
  const onLockLostRef = useRef(onLockLost);
  // The draft `send()`'s continuations should still believe is current: `Workspace` stays mounted
  // across a URL param change, so a PATCH still in flight for the previous draftId can resolve
  // after she has already navigated to a new one.
  const currentDraftIdRef = useRef(draftId);
  const pendingRef = useRef<Record<string, unknown>>({});
  const inFlightRef = useRef<Record<string, unknown> | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const sendRef = useRef<
    (snapshot: Record<string, unknown>, isStaleRetry: boolean) => void
  >(() => {});
  const flushRef = useRef<() => void>(() => {});

  const clearRetryTimer = useCallback(() => {
    if (retryTimerRef.current !== null) {
      clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    }
  }, []);

  // Refs only ever get written in effects/callbacks, never during render: this keeps the ones
  // event handlers read at their latest value without re-creating those handlers every render.
  useEffect(() => {
    revisionRef.current = revision;
    savedRef.current = answers;
    onSavedRef.current = onSaved;
    onLockLostRef.current = onLockLost;
    currentDraftIdRef.current = draftId;
  });

  // A new draft: drop whatever this hook instance still remembered about the previous one.
  useEffect(() => {
    pendingRef.current = {};
    inFlightRef.current = null;
    clearRetryTimer();
  }, [draftId, clearRetryTimer]);

  const send = useCallback(
    (snapshot: Record<string, unknown>, isStaleRetry: boolean) => {
      // Captured now, not read again later: `currentDraftIdRef` may have moved on to a different
      // draft by the time any of the continuations below run.
      const requestDraftId = draftId;
      const isCurrentDraft = () => currentDraftIdRef.current === requestDraftId;
      patchAnswers(draftId, revisionRef.current, snapshot).then(
        (draft) => {
          if (!isCurrentDraft()) return;
          inFlightRef.current = null;
          revisionRef.current = draft.revision;
          setSaveStatus("saved");
          setBanner("none");
          setFieldProblems((current) => {
            if (Object.keys(snapshot).every((qid) => !(qid in current)))
              return current;
            const next = { ...current };
            for (const qid of Object.keys(snapshot)) delete next[qid];
            return next;
          });
          onSavedRef.current(draft);
          flushRef.current();
        },
        (error: unknown) => {
          if (!isCurrentDraft()) return;
          if (
            error instanceof ApiError &&
            error.status === 409 &&
            error.fieldErrors?.some(
              (fieldError) => fieldError.code === "lock_not_held",
            )
          ) {
            // Story 4.4: lost the edit lock mid-edit -- never a silent retry (reloading the
            // revision changes nothing about who holds the lock). The value stays on screen with
            // a "not saved" note (the server's own message) and no "Saved ✓"; `onLockLost` tells
            // the workspace to re-check the lock right away, so it already knows who holds it by
            // the time it switches to read-only (spec matrix "Lost lock mid-edit").
            const message =
              error.fieldErrors.find(
                (fieldError) => fieldError.code === "lock_not_held",
              )?.message ?? "";
            inFlightRef.current = null;
            setSaveStatus("idle");
            setFieldProblems((current) => {
              const next = { ...current };
              for (const qid of Object.keys(snapshot)) {
                next[qid] = { message };
              }
              return next;
            });
            onLockLostRef.current?.();
            return;
          }
          if (error instanceof ApiError && error.status === 409) {
            if (isStaleRetry) {
              // A second conflict in a row: stop silently retrying and surface it like any other
              // failure, rather than loop forever (EXPERIENCE.md names only the first retry).
              inFlightRef.current = null;
              pendingRef.current = { ...snapshot, ...pendingRef.current };
              setBanner("save-failed");
              return;
            }
            // Keep inFlightRef set to `snapshot` for this whole sequence (never null it here): a
            // commit() landing in this window must queue behind it, not start a second concurrent
            // send() for the same fields.
            getDraft(draftId).then(
              (draft) => {
                if (!isCurrentDraft()) return;
                revisionRef.current = draft.revision;
                onSavedRef.current(draft);
                inFlightRef.current = snapshot;
                sendRef.current(snapshot, true);
              },
              () => {
                if (!isCurrentDraft()) return;
                inFlightRef.current = null;
                pendingRef.current = { ...snapshot, ...pendingRef.current };
                setBanner("save-failed");
              },
            );
            return;
          }
          // The api's own 401 body is already in the closed AD-12 shape (so `fieldErrors` is
          // truthy below), but a signed-out session is `client.ts`'s/`session.tsx`'s 401 hook's
          // job, not a field problem to show on this edit -- do nothing and let that hook redirect.
          if (error instanceof ApiError && error.status === 401) {
            return;
          }
          if (error instanceof ApiError && error.fieldErrors) {
            inFlightRef.current = null;
            setSaveStatus("idle");
            setFieldProblems((current) => {
              const next = { ...current };
              for (const fieldError of error.fieldErrors ?? []) {
                next[fieldError.field] = { message: fieldError.message };
              }
              return next;
            });
            flushRef.current();
            return;
          }
          // A 5xx, a network failure, or a timeout: keep the value on screen, retry on our own.
          inFlightRef.current = null;
          pendingRef.current = { ...snapshot, ...pendingRef.current };
          setSaveStatus("idle");
          setBanner("save-failed");
          clearRetryTimer();
          retryTimerRef.current = setTimeout(() => {
            retryTimerRef.current = null;
            flushRef.current();
          }, RETRY_DELAY_MS);
        },
      );
    },
    [draftId, clearRetryTimer],
  );

  const flush = useCallback(() => {
    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      setBanner("offline");
      return;
    }
    if (inFlightRef.current !== null) return; // already sending; flush() runs again once it settles
    const snapshot = pendingRef.current;
    if (Object.keys(snapshot).length === 0) return;
    pendingRef.current = {};
    inFlightRef.current = snapshot;
    setSaveStatus("saving");
    send(snapshot, false);
  }, [send]);

  useEffect(() => {
    sendRef.current = send;
    flushRef.current = flush;
  });

  // The "what does she already believe this field is" lookup `commit` and `commitMany` both diff
  // against: queued first, then in flight, then the last server-confirmed value.
  const knownValue = useCallback(
    (questionId: string): unknown =>
      questionId in pendingRef.current
        ? pendingRef.current[questionId]
        : inFlightRef.current && questionId in inFlightRef.current
          ? inFlightRef.current[questionId]
          : savedRef.current[questionId],
    [],
  );

  const commit = useCallback(
    (questionId: string, value: unknown) => {
      if (sameValue(value, knownValue(questionId))) return; // a true no-op
      pendingRef.current = { ...pendingRef.current, [questionId]: value };
      flush();
    },
    [flush, knownValue],
  );

  const commitMany = useCallback(
    (patch: Record<string, unknown>) => {
      const changed: Record<string, unknown> = {};
      for (const [questionId, value] of Object.entries(patch)) {
        if (!sameValue(value, knownValue(questionId)))
          changed[questionId] = value;
      }
      if (Object.keys(changed).length === 0) return; // every field was already a no-op
      pendingRef.current = { ...pendingRef.current, ...changed };
      flush();
    },
    [flush, knownValue],
  );

  const retry = useCallback(() => {
    clearRetryTimer();
    flush();
  }, [clearRetryTimer, flush]);

  const reportProblems = useCallback(
    (problems: Record<string, FieldProblem>) => {
      setFieldProblems(problems);
    },
    [],
  );

  const setFieldProblem = useCallback(
    (questionId: string, problem: FieldProblem | null) => {
      setFieldProblems((current) => {
        if (problem === null) {
          if (!(questionId in current)) return current; // true no-op, skip the re-render
          const next = { ...current };
          delete next[questionId];
          return next;
        }
        return { ...current, [questionId]: problem };
      });
    },
    [],
  );

  useEffect(() => {
    function handleOnline() {
      setBanner((current) => (current === "offline" ? "none" : current));
      flushRef.current();
    }
    function handleOffline() {
      setBanner("offline");
    }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => clearRetryTimer, [clearRetryTimer]);

  return {
    saveStatus,
    banner,
    fieldProblems,
    commit,
    commitMany,
    retry,
    reportProblems,
    setFieldProblem,
  };
}
