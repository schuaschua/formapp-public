// The workspace's answer controls, custom RJSF widgets for the shapes DESIGN.md's row spec needs
// that no off-the-shelf RJSF widget provides (Story 1.9 spec assumption "RJSF customization
// depth"). Story 1.10 wires each one to autosave: Yes/No, select and option-choice pills/dropdowns
// commit at once on click/choice (there is no other commit signal for a button-like or
// dropdown-like control); the unit-mapped number input commits on blur, like every other
// text/number/date question (`Workspace`'s own `onBlur` handles those, via RJSF's built-in
// widgets). A widget calls `useWorkspaceUi().commit` directly (a plain React context, not RJSF's
// own `formContext` -- see context.ts for why) and keeps a local "what she just picked" override
// so the value visibly changes at once and stays on screen even if the save is later rejected
// (UX-DR43: "the value stays on screen"). Story 2.3's `ProductWidget` is the one exception:
// choosing P1 calls `commitMany` instead, so P1 and P2's foreign-rider drop reach the api in one
// PATCH rather than two racing ones (see `commitMany`'s own docstring in `autosave.ts`).
import type { WidgetProps } from "@rjsf/utils";
import type { KeyboardEvent } from "react";
import { useState } from "react";
import { strings } from "../../strings";
import { useWorkspaceUi } from "./context";

/** Shows `override` once set, until `serverValue` itself changes to match (a confirmed save, or a
 * value the AI/another tab set) -- then it defers to the server again. Adjusts during render, like
 * `Workspace`'s own `loadedForId`, rather than in an effect (React's documented pattern for
 * "adjusting state when a prop changes"). */
function useLocalOverride<T>(serverValue: T): [T, (next: T) => void] {
  const [override, setOverride] = useState<T | undefined>(undefined);
  const [lastServerValue, setLastServerValue] = useState(serverValue);
  if (!Object.is(lastServerValue, serverValue)) {
    setLastServerValue(serverValue);
    setOverride(undefined);
  }
  return [override === undefined ? serverValue : override, setOverride];
}

/** `H1`→cm, `H2`→kg, `N2`/`N5`→RM (spec assumption "Answer-control mapping"). */
const UNIT_BY_QID: Record<string, string> = {
  H1: "cm",
  H2: "kg",
  N2: "RM",
  N5: "RM",
};

/** `N7`/`G3` always render as a wide textarea (an AC override, ahead of the generic mapping). */
const WIDE_TEXT_IDS = new Set(["N7", "G3"]);

/** A stable empty-array fallback for `ChecklistWidget`'s unanswered case: a fresh `[]` literal on
 * every render would never `Object.is`-equal the previous one, so `useLocalOverride`'s render-time
 * reset would fire every render and React would bail out with "Too many re-renders". */
const EMPTY_ARRAY: unknown[] = [];

/**
 * The answer-control mapping (spec assumption): the two explicit AC overrides first, then a
 * yes/no or 2-3 option enum as a segmented pill, a 4+ option enum as `SelectWidget` (a native
 * select, committed immediately like every other select/option-choice control), an array with
 * `items.enum` as a pill checklist, a unit-mapped number as `UnitInputWidget`, and anything else
 * left to RJSF's own default widget for its type (text, number, native date input).
 * Returns a widget name to put in `"ui:widget"`, or `undefined` to leave the default alone.
 */
export function chooseWidget(
  qid: string,
  question: Record<string, unknown>,
): string | undefined {
  if (qid === "P1") return "ProductWidget";
  if (qid === "P2") return "RiderWidget";
  if (qid === "P3") return "TermWidget";
  if (WIDE_TEXT_IDS.has(qid)) return "textarea";
  const type = question.type;
  if (type === "array") {
    const items = question.items;
    if (
      typeof items === "object" &&
      items !== null &&
      Array.isArray((items as Record<string, unknown>).enum)
    ) {
      return "ChecklistWidget";
    }
    return undefined;
  }
  if (type === "string" && Array.isArray(question.enum)) {
    return question.enum.length <= 3 ? "SegmentedWidget" : "SelectWidget";
  }
  // FORM-213: every number/integer question gets this widget, unit-mapped (H1/H2/N2/N5) or not
  // (e.g. N4) -- it's the one place digit-only entry and the inline invalid-number error live.
  if (type === "number" || type === "integer") {
    return "UnitInputWidget";
  }
  return undefined;
}

/** The unit suffix for a question id, if the answer-control mapping gives it one. */
export function unitFor(qid: string): string | undefined {
  return UNIT_BY_QID[qid];
}

/** Yes/No and short option sets: a pill track, the selected option filled dark with white text.
 * Clicking a pill commits it at once (DESIGN.md/EXPERIENCE.md "Autosave"). */
export function SegmentedWidget(props: WidgetProps) {
  const { id, name, options, label, disabled, readonly } = props;
  const enumOptions = options.enumOptions ?? [];
  const [value, setValue] = useLocalOverride(props.value);
  const { commit } = useWorkspaceUi();
  return (
    <span id={id} className="ws-seg" role="group" aria-label={label}>
      {enumOptions.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          className={
            "ws-seg__option" +
            (option.value === value ? " ws-seg__option--on" : "")
          }
          aria-pressed={option.value === value}
          disabled={disabled || readonly}
          onClick={() => {
            setValue(option.value);
            commit(name, option.value);
          }}
        >
          {option.label}
        </button>
      ))}
    </span>
  );
}

/** A 4+-option enum (e.g. marital status): a native `<select>`, committed at once on choice like
 * every other select/option-choice control (DESIGN.md/EXPERIENCE.md "Autosave") -- unlike RJSF's
 * own default `SelectWidget`, which only exposes a per-field `onBlur`. */
export function SelectWidget(props: WidgetProps) {
  const { id, name, options, label, disabled, readonly } = props;
  const enumOptions = options.enumOptions ?? [];
  const [value, setValue] = useLocalOverride(props.value);
  const { commit } = useWorkspaceUi();
  return (
    <select
      id={id}
      aria-label={label}
      className="form-control"
      value={value == null ? "" : String(value)}
      disabled={disabled || readonly}
      onChange={(event) => {
        const selected = enumOptions.find(
          (option) => String(option.value) === event.target.value,
        );
        const nextValue = selected ? selected.value : null;
        setValue(nextValue);
        commit(name, nextValue);
      }}
    >
      <option value="" />
      {enumOptions.map((option) => (
        <option key={String(option.value)} value={String(option.value)}>
          {option.label}
        </option>
      ))}
    </select>
  );
}

/**
 * A pill checklist (checkbox group) for an array with `items.enum`, honouring `x-exclusive`: the
 * schema carries the exclusive value(s) in `options.exclusiveValues` (set by `Workspace` from the
 * question's own `x-exclusive`). Clicking a pill toggles it and commits the whole array at once;
 * picking an exclusive value (e.g. "None") clears every other pill and vice versa.
 */
export function ChecklistWidget(props: WidgetProps) {
  const { id, name, options, label, disabled, readonly } = props;
  const enumOptions = options.enumOptions ?? [];
  const exclusiveValues = Array.isArray(options.exclusiveValues)
    ? options.exclusiveValues
    : [];
  const [value, setValue] = useLocalOverride<unknown[]>(
    Array.isArray(props.value) ? props.value : EMPTY_ARRAY,
  );
  const { commit } = useWorkspaceUi();

  function toggle(optionValue: unknown) {
    const isExclusive = exclusiveValues.includes(optionValue);
    const selected = isExclusive
      ? value.includes(optionValue)
        ? []
        : [optionValue]
      : (() => {
          const withoutExclusive = value.filter(
            (item) => !exclusiveValues.includes(item),
          );
          return withoutExclusive.includes(optionValue)
            ? withoutExclusive.filter((item) => item !== optionValue)
            : [...withoutExclusive, optionValue];
        })();
    setValue(selected);
    commit(name, selected);
  }

  return (
    <span id={id} className="ws-checklist" role="group" aria-label={label}>
      {enumOptions.map((option) => (
        <button
          key={String(option.value)}
          type="button"
          className={
            "ws-checklist__option" +
            (value.includes(option.value) ? " ws-checklist__option--on" : "")
          }
          aria-pressed={value.includes(option.value)}
          disabled={disabled || readonly}
          onClick={() => toggle(option.value)}
        >
          {option.label}
        </button>
      ))}
    </span>
  );
}

const INTEGER_TEXT = /^\d+$/;
const NUMBER_TEXT = /^\d+(\.\d+)?$/;

/** Whether typed/pasted `text` is a valid answer for a number/integer question -- digits only,
 * plus a single decimal point for a plain "number" (never for an "integer", e.g. N4). Blank is
 * valid here: it means "no answer yet" (cleared on blur), not "not a number" (FORM-213). */
function isNumericText(text: string, isInteger: boolean): boolean {
  const trimmed = text.trim();
  if (trimmed === "") return true;
  return (isInteger ? INTEGER_TEXT : NUMBER_TEXT).test(trimmed);
}

/** Keys that never insert a character themselves (Backspace, arrows, ...), or that combine with
 * Ctrl/Cmd for a copy/paste/select-all-style shortcut -- always let these through. */
function isNonInsertingKey(event: KeyboardEvent<HTMLInputElement>): boolean {
  if (event.ctrlKey || event.metaKey) return true;
  return [
    "Backspace",
    "Delete",
    "Tab",
    "Enter",
    "Escape",
    "ArrowLeft",
    "ArrowRight",
    "ArrowUp",
    "ArrowDown",
    "Home",
    "End",
  ].includes(event.key);
}

/** A text/number input with its unit ("cm", "kg", "RM") inside the field, right-aligned. Commits
 * on blur, like every other text/number/date question.
 *
 * FORM-213: a plain `type="number"` input lets a browser silently blank out or otherwise mangle
 * non-numeric text rather than reliably surfacing it, so this is a `type="text"` input instead,
 * with its own digit-only gate. Typing is filtered key by key (a letter is simply never inserted),
 * but a paste or autofill is deliberately not blocked at the event level -- the same way the
 * server stays the backstop for every other field (AGENTS.md) -- so it always lands in `text` and
 * is then caught by the same `isNumericText` check as every other change: while invalid, the
 * field shows the Story 3.1 amber problem highlight (via `setFieldProblem`, `fieldProblems`'s own
 * per-field merge) and nothing is ever committed for it. */
export function UnitInputWidget(props: WidgetProps) {
  const { id, name, disabled, readonly, options, schema } = props;
  const isInteger = schema.type === "integer";
  const unit = typeof options.unit === "string" ? options.unit : undefined;
  const serverValue = typeof props.value === "number" ? props.value : null;
  const [text, setText] = useState(
    serverValue === null ? "" : String(serverValue),
  );
  const [lastServerValue, setLastServerValue] = useState(serverValue);
  const { commit, setFieldProblem } = useWorkspaceUi();
  if (!Object.is(lastServerValue, serverValue)) {
    setLastServerValue(serverValue);
    setText(serverValue === null ? "" : String(serverValue));
    // A fresh, valid server value (another tab, the AI) always supersedes any stale local error.
    setFieldProblem(name, null);
  }
  return (
    <span className="ws-unit-input">
      <input
        id={id}
        className="ws-unit-input__field"
        type="text"
        inputMode={isInteger ? "numeric" : "decimal"}
        value={text}
        disabled={disabled}
        readOnly={readonly}
        onKeyDown={(event) => {
          if (isNonInsertingKey(event)) return;
          if (event.key.length !== 1) return; // a modifier/named key on its own inserts nothing
          const allowed = isInteger ? /^[0-9]$/ : /^[0-9.]$/;
          if (!allowed.test(event.key)) event.preventDefault();
        }}
        onChange={(event) => {
          const next = event.target.value;
          setText(next);
          setFieldProblem(
            name,
            isNumericText(next, isInteger)
              ? null
              : { message: strings.workspace.numberFieldInvalidMessage },
          );
        }}
        onBlur={() => {
          if (!isNumericText(text, isInteger)) return; // stays on screen, uncommitted
          if (text.trim() === "") {
            commit(name, null);
            return;
          }
          commit(name, Number(text));
        }}
      />
      {unit && <span className="ws-unit-input__unit">{unit}</span>}
    </span>
  );
}

/**
 * P1: a native `<select>` over the eligible products from `WorkspaceUiContext.products`
 * (Story 2.3), committed at once on choice. Choosing a product sends `{P1, P2}` in one
 * `commitMany` PATCH, filtering P2 down to riders that belong to the newly chosen product, so a
 * rider foreign to the new product never lingers as a stored (and now stale) answer.
 */
export function ProductWidget(props: WidgetProps) {
  const { id, name, label, disabled, readonly } = props;
  const { products, answers, commitMany } = useWorkspaceUi();
  const [value, setValue] = useLocalOverride(props.value);
  const options = products ?? [];
  // A stored P1 can outlive its own eligibility (e.g. a C2 edit ages the insured out of it) or
  // simply not be in the list yet while it's loading -- the select must still show it as chosen
  // rather than going blank, which would look like nothing was ever selected.
  const isKnownOption =
    value == null || options.some((product) => product.code === value);
  return (
    <select
      id={id}
      aria-label={label}
      className="form-control"
      value={value == null ? "" : String(value)}
      disabled={disabled || readonly || products === null}
      onChange={(event) => {
        const nextCode = event.target.value === "" ? null : event.target.value;
        setValue(nextCode);
        const nextProduct = options.find(
          (product) => product.code === nextCode,
        );
        const riderCodes = new Set(
          nextProduct ? nextProduct.riders.map((rider) => rider.code) : [],
        );
        const currentRiders = Array.isArray(answers.P2) ? answers.P2 : [];
        const filteredRiders = currentRiders.filter(
          (code): code is string =>
            typeof code === "string" && riderCodes.has(code),
        );
        commitMany({ [name]: nextCode, P2: filteredRiders });
      }}
    >
      <option value="" />
      {!isKnownOption && <option value={String(value)}>{String(value)}</option>}
      {options.map((product) => (
        <option key={product.code} value={product.code}>
          {product.name}
        </option>
      ))}
    </select>
  );
}

/** The selected product (P1) from `WorkspaceUiContext`, or `undefined` when P1 is unset, still
 * loading, or no longer among the eligible `products` (e.g. a C2 edit aged it out) -- the lookup
 * `RiderWidget` and `TermWidget` both need before they have riders/terms to offer. */
function useSelectedProduct() {
  const { products, answers } = useWorkspaceUi();
  return products?.find((product) => product.code === answers.P1);
}

/** P2: a pill toggle over P1's own riders (Story 2.3), `commit` only -- never `commitMany`, since
 * this widget never touches P1 itself. Shows "Choose a product first" only while P1 is genuinely
 * unset; a P1 that's set but not (yet, or no longer) among the eligible `products` renders with no
 * rider pills to offer, rather than the misleading placeholder. */
export function RiderWidget(props: WidgetProps) {
  const { id, name, label, disabled, readonly } = props;
  const [value, setValue] = useLocalOverride<unknown[]>(
    Array.isArray(props.value) ? props.value : EMPTY_ARRAY,
  );
  const { commit, answers } = useWorkspaceUi();
  const selectedProduct = useSelectedProduct();

  if (answers.P1 == null) {
    return (
      <span id={id} className="ws-no-options" aria-disabled="true">
        {strings.workspace.chooseProductFirst}
      </span>
    );
  }

  function toggle(code: string) {
    const next = value.includes(code)
      ? value.filter((item) => item !== code)
      : [...value, code];
    setValue(next);
    commit(name, next);
  }

  return (
    <span id={id} className="ws-checklist" role="group" aria-label={label}>
      {(selectedProduct?.riders ?? []).map((rider) => (
        <button
          key={rider.code}
          type="button"
          className={
            "ws-checklist__option" +
            (value.includes(rider.code) ? " ws-checklist__option--on" : "")
          }
          aria-pressed={value.includes(rider.code)}
          disabled={disabled || readonly}
          onClick={() => toggle(rider.code)}
        >
          {rider.name}
        </button>
      ))}
    </span>
  );
}

/** P3: a native `<select>` over P1's own policy terms (Story 2.3), `commit` only. Shows "Choose a
 * product first" only while P1 is genuinely unset, like `RiderWidget`; a P1 that's set but not
 * (yet, or no longer) among the eligible `products` renders with no terms to offer. */
export function TermWidget(props: WidgetProps) {
  const { id, name, label, disabled, readonly } = props;
  const [value, setValue] = useLocalOverride(props.value);
  const { commit, answers } = useWorkspaceUi();
  const selectedProduct = useSelectedProduct();

  if (answers.P1 == null) {
    return (
      <span id={id} className="ws-no-options" aria-disabled="true">
        {strings.workspace.chooseProductFirst}
      </span>
    );
  }

  return (
    <select
      id={id}
      aria-label={label}
      className="form-control"
      value={value == null ? "" : String(value)}
      disabled={disabled || readonly}
      onChange={(event) => {
        const next = event.target.value === "" ? null : event.target.value;
        setValue(next);
        commit(name, next);
      }}
    >
      <option value="" />
      {(selectedProduct?.policyTerms ?? []).map((term) => (
        <option key={term.code} value={term.code}>
          {term.label}
        </option>
      ))}
    </select>
  );
}

export const workspaceWidgets = {
  SegmentedWidget,
  SelectWidget,
  ChecklistWidget,
  UnitInputWidget,
  ProductWidget,
  RiderWidget,
  TermWidget,
};
