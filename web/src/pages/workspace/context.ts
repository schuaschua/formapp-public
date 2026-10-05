// Story 1.10: the workspace's own React context for everything the RJSF-rendered tree needs that
// changes over time (the current page, the active/follow-up sets, autosave's field problems and
// its commit function). Deliberately *not* RJSF's own `formContext`/`registry` plumbing: `Form`
// (a class component) caches its `registry` in `this.state` and only refreshes it when its own
// `getSnapshotBeforeUpdate` decides `formContext` changed, which in practice does not fire
// reliably for a `formContext`-only update reached from outside a DOM event (e.g. a fetch
// response) -- confirmed by tracing `@rjsf/core`'s `Form.js` directly. A plain context bypasses
// that cache entirely: a consumer re-renders on every value the provider hands it, regardless of
// what any component in between (Form included) decides to skip.
import { createContext, useContext } from "react";
import type { Product } from "../../api/client";

export type FieldProblem = { message: string };

export type WorkspaceUiContextValue = {
  currentPage: number;
  active: Set<string>;
  followUps: Set<string>;
  fieldProblems: Record<string, FieldProblem>;
  commit: (questionId: string, value: unknown) => void;
  /** FORM-213: a widget's own client-side validation problem (e.g. `UnitInputWidget`'s pasted
   * non-number), merged into `fieldProblems` -- `null` clears just that one field, unlike
   * `reportProblems`'s wholesale replace. Reuses the exact Story 3.1 amber highlight/badge. */
  setFieldProblem: (questionId: string, problem: FieldProblem | null) => void;
  /** Story 2.3: `ProductWidget`'s same-PATCH `{P1, P2}` write, so changing P1 drops any rider
   * foreign to the newly chosen product in one request (never two racing PATCHes). */
  commitMany: (patch: Record<string, unknown>) => void;
  /** The proposal's eligible products at its insured age (Story 2.3), or `null` before they've
   * loaded -- never RJSF's own `formContext`/`registry` (this module's own docstring explains why).
   * `ProductWidget`/`RiderWidget`/`TermWidget` render nothing to pick from until this is set. */
  products: Product[] | null;
  /** The draft's own plain answers, so `RiderWidget`/`TermWidget` can find the currently selected
   * P1 without RJSF's `formContext` (same reason as `products`). */
  answers: Record<string, unknown>;
};

export const WorkspaceUiContext = createContext<WorkspaceUiContextValue | null>(
  null,
);

/** Every answer widget and the object-field template call this, always inside `Workspace`'s
 * provider (Story 1.9/1.10), so a missing value is a wiring bug, not a normal state. */
export function useWorkspaceUi(): WorkspaceUiContextValue {
  const value = useContext(WorkspaceUiContext);
  if (!value) {
    throw new Error(
      "useWorkspaceUi() must be used inside Workspace's provider.",
    );
  }
  return value;
}
