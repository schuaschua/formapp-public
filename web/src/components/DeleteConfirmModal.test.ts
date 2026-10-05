import { describe, expect, it } from "vitest";
import { ApiError } from "../api/client";
import { strings } from "../strings";
import { deleteFailedMessage } from "./DeleteConfirmModal";

// FORM-232: a refused delete says why when Alice can act on it.
describe("FORM-232 deleteFailedMessage", () => {
  const refusal = (code: string) =>
    new ApiError(409, [{ field: "lock", code, message: "" }]);

  it("names another window for lock_not_held", () => {
    expect(deleteFailedMessage(refusal("lock_not_held"))).toBe(
      strings.deleteDraftModal.lockedMessage,
    );
  });

  it("names the AI for turn_in_progress", () => {
    expect(deleteFailedMessage(refusal("turn_in_progress"))).toBe(
      strings.deleteDraftModal.aiBusyMessage,
    );
  });

  it("falls back to the generic message otherwise", () => {
    expect(deleteFailedMessage(refusal("proposal_submitted"))).toBe(
      strings.deleteDraftModal.failedMessage,
    );
    expect(deleteFailedMessage(new ApiError(500, undefined))).toBe(
      strings.deleteDraftModal.failedMessage,
    );
    expect(deleteFailedMessage(new TypeError("offline"))).toBe(
      strings.deleteDraftModal.failedMessage,
    );
  });
});
