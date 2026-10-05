// Story 2.3: RM with thousands separators (epic-2-context.md "Formatting and style": "Prices show
// as RM with thousands separators"), from numbers the api already rounded to 2 decimals -- this
// never computes a price itself (coding-style.md rule 16), only formats one it was given.

const FORMAT = new Intl.NumberFormat("en-MY", {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

/** `219.95` -> `"RM219.95"`; `2507.42` -> `"RM2,507.42"`. */
export function formatRm(amount: number): string {
  return `RM${FORMAT.format(amount)}`;
}
