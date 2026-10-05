// The Ajv2020 validator RJSF renders question rows with (Story 1.9, spec assumption "Package
// versions"): no `@rjsf/validator-ajv2020` package exists, so this is `customizeValidator` from
// `@rjsf/validator-ajv8` given the 2020-12 Ajv class shipped inside `ajv` itself. This is the only
// client-side validator instantiated (coding-style.md rule 16): it renders controls and marks
// required fields, but never decides whether an answer is accepted -- the server does that.
import { customizeValidator } from "@rjsf/validator-ajv8";
import type Ajv from "ajv";
import Ajv2020 from "ajv/dist/2020";
import type { Schema } from "../../api/client";

export const validator = customizeValidator({
  // Ajv2020 is a sibling subclass of AjvCore, not `Ajv` itself, so its constructor shape needs the
  // cast; `createAjvInstance` (inside `@rjsf/validator-ajv8`) only ever calls `new AjvClass(opts)`.
  AjvClass: Ajv2020 as unknown as typeof Ajv,
});

/**
 * The Gynaecology section (DESIGN.md Components, the only named subsection in the seed content):
 * shown only when at least one of its questions is active.
 */
export const sectionHeadings: { label: string; ids: readonly string[] }[] = [
  { label: "Gynaecology", ids: ["G1", "G2", "G3", "H15"] },
];

/**
 * Every question id named in an `allOf[].then.required` clause: a follow-up of whichever question
 * gates it (spec assumption "Section headings"). Order and page membership don't matter here --
 * `Workspace` only asks whether a given active id is a follow-up, to indent and lighten its row.
 */
export function followUpIds(schema: Schema): Set<string> {
  const ids = new Set<string>();
  for (const rule of schema.allOf ?? []) {
    if (typeof rule !== "object" || rule === null) continue;
    const then = (rule as Record<string, unknown>).then;
    if (typeof then !== "object" || then === null) continue;
    const required = (then as Record<string, unknown>).required;
    if (!Array.isArray(required)) continue;
    for (const id of required) {
      if (typeof id === "string") ids.add(id);
    }
  }
  return ids;
}
