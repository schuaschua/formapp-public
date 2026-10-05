// Shared test fixture for the workspace (Story 1.9): a small schema covering each answer-control
// mapping (a 3-option and a 2-option enum -> segmented, a 4-option enum -> the default select, a
// unit-mapped number, a checklist with `x-exclusive`, and `P1`/`P2`/`P3`'s Story 2.3 product/
// rider/term controls) plus one follow-up pair per rule (N3 -> N4, G1 -> G2, the second landing in
// the Gynaecology section), used by both Workspace.test.tsx and PageMenu.test.tsx so the shape
// isn't duplicated byte-for-byte.
import type { Schema } from "../../api/client";

export const FIXTURE_SCHEMA: Schema = {
  properties: {
    N1: {
      title: "What type of product are you looking for?",
      type: "string",
      enum: ["life", "life_health", "health"],
      "x-labels": {
        life: "Life",
        life_health: "Life + Health",
        health: "Health",
      },
      "x-page": 1,
      "x-fill": "ask",
    },
    N3: {
      title: "Should the policy cover your dependents?",
      type: "string",
      enum: ["Yes", "No"],
      "x-page": 1,
      "x-fill": "ask",
    },
    N4: {
      title: "How many dependents?",
      type: "integer",
      minimum: 1,
      maximum: 10,
      "x-page": 1,
      "x-fill": "ask",
    },
    P1: {
      title: "Selected product",
      type: "string",
      minLength: 1,
      maxLength: 50,
      "x-page": 2,
      "x-fill": "infer",
    },
    P2: {
      title: "Optional riders",
      type: "array",
      items: { type: "string", minLength: 1, maxLength: 50 },
      uniqueItems: true,
      "x-page": 2,
      "x-fill": "infer",
    },
    P3: {
      title: "Policy term",
      type: "string",
      minLength: 1,
      maxLength: 50,
      "x-page": 2,
      "x-fill": "infer",
    },
    Y1: {
      title: "Payment frequency",
      type: "string",
      enum: ["monthly", "yearly"],
      "x-labels": { monthly: "Monthly", yearly: "Yearly" },
      "x-page": 3,
      "x-fill": "infer",
    },
    C1: {
      title: "First name",
      type: "string",
      minLength: 1,
      maxLength: 50,
      "x-page": 4,
      "x-fill": "db",
    },
    C11: {
      title: "Marital status",
      type: "string",
      enum: ["single", "married", "divorced", "widowed"],
      "x-labels": {
        single: "Single",
        married: "Married",
        divorced: "Divorced",
        widowed: "Widowed",
      },
      "x-page": 4,
      "x-fill": "db",
    },
    H1: {
      title: "Height (cm)",
      type: "number",
      minimum: 100,
      maximum: 250,
      "x-page": 5,
      "x-fill": "ask",
    },
    H4: {
      title: "Do you take part in any hazardous activities?",
      type: "array",
      items: {
        type: "string",
        enum: ["none", "scuba_diving", "skydiving"],
      },
      uniqueItems: true,
      minItems: 1,
      "x-labels": {
        none: "None",
        scuba_diving: "Scuba diving",
        skydiving: "Skydiving",
      },
      "x-page": 5,
      "x-fill": "ask",
      "x-exclusive": ["none"],
    },
    G1: {
      title: "Have you ever been pregnant?",
      type: "string",
      enum: ["Yes", "No"],
      "x-page": 5,
      "x-fill": "default",
      "x-simple": true,
    },
    G2: {
      title: "Outcome of previous pregnancies",
      type: "array",
      items: {
        type: "string",
        enum: ["live_birth", "miscarriage"],
      },
      uniqueItems: true,
      minItems: 1,
      "x-labels": { live_birth: "Live birth", miscarriage: "Miscarriage" },
      "x-page": 5,
      "x-fill": "ask",
    },
  },
  required: ["N1", "N3", "Y1", "C1", "C11", "H1", "H4"],
  allOf: [
    {
      if: { properties: { N3: { const: "Yes" } }, required: ["N3"] },
      then: { required: ["N4"] },
    },
    {
      if: { properties: { G1: { const: "Yes" } }, required: ["G1"] },
      then: { required: ["G2"] },
    },
  ],
};

/**
 * A draft two pages into being filled: page 1 (N1/N3/N4) and page 3 (Y1) done; page 2 unanswered
 * (`P1`/`P3` aren't in this fixture schema's own `required`, unlike the real one -- Story 2.3's
 * "P1/P3 answered completes page 2" test uses the real schema instead, next to the fixture that
 * already exercises that); page 4 missing `C11`; page 5's `G1 = "Yes"` reveals `G2`, itself
 * unanswered, so page 5 isn't done either. "2 of 5 pages done", `quote` null (no P1/C2 yet).
 */
export const FIXTURE_DRAFT = {
  id: "44444444-4444-4444-8444-444444444444",
  status: "draft",
  schema_version: 1,
  revision: 3,
  lock: { holder: "you", expires_at: null },
  active: [
    "N1",
    "N3",
    "N4",
    "P1",
    "P2",
    "P3",
    "Y1",
    "C1",
    "C11",
    "H1",
    "H4",
    "G1",
    "G2",
  ],
  answers: {
    N1: "life_health",
    N3: "Yes",
    N4: 2,
    Y1: "monthly",
    C1: "Ally",
    H1: 165,
    G1: "Yes",
  },
  provenance: {},
  quote: null,
  display_name: "Ally_Macbeal_Proposal_001",
};

/**
 * Story 2.3's priced-and-eligible listing (`GET /api/products?proposal_id=`), snake_case wire
 * shape: FSH (with its Maternity & newborn rider) and LT20, enough to exercise
 * `ProductWidget`/`RiderWidget`/`TermWidget` and the price summary without the full seeded
 * catalogue.
 */
export const FIXTURE_PRODUCTS = [
  {
    code: "FSH",
    name: "FamilyShield Life & Health",
    type: "life_health",
    covers_dependents: true,
    policy_terms: [
      { code: "20_yrs", label: "20 yrs" },
      { code: "30_yrs", label: "30 yrs" },
    ],
    sum_assured_min: 200000,
    sum_assured_max: 600000,
    default_sum_assured: 300000,
    default_term: "20_yrs",
    min_age: 18,
    max_age: 55,
    monthly: 185.22,
    yearly: 2111.51,
    riders: [
      {
        code: "R07",
        name: "Maternity & newborn",
        monthly: 34.73,
        yearly: 395.91,
      },
    ],
  },
  {
    code: "LT20",
    name: "SecureLife Term",
    type: "life",
    covers_dependents: true,
    policy_terms: [{ code: "10_yrs", label: "10 yrs" }],
    sum_assured_min: 100000,
    sum_assured_max: 500000,
    default_sum_assured: 200000,
    default_term: "10_yrs",
    min_age: 18,
    max_age: 60,
    monthly: 60,
    yearly: 684,
    riders: [
      { code: "R01", name: "Critical illness", monthly: 20, yearly: 228 },
    ],
  },
];

/** The draft `FIXTURE_DRAFT` would become with FSH and its Maternity & newborn rider chosen, and
 * the quote Story 2.2's own reference case computes for them (epic-2-context.md). */
export const FIXTURE_DRAFT_WITH_QUOTE = {
  ...FIXTURE_DRAFT,
  answers: { ...FIXTURE_DRAFT.answers, P1: "FSH", P2: ["R07"] },
  quote: {
    monthly: 219.95,
    yearly: 2507.42,
    lines: [
      { item: "FamilyShield Life & Health", monthly: 185.22, yearly: 2111.51 },
      { item: "Maternity & newborn", monthly: 34.73, yearly: 395.91 },
    ],
  },
};

/**
 * A rejected `PATCH /api/proposals/:id/answers` (Story 1.10): the closed AD-12 error shape, one
 * field error, for the rejected-value amber-highlight tests.
 */
export const FIXTURE_422 = {
  errors: [
    { field: "C1", code: "invalid_value", message: "Enter a valid answer." },
  ],
};

/**
 * The draft a save would return after G1 flips from "Yes" to "No" (Story 1.10): G2 leaves the
 * `active` list and its answer, for the follow-up-reveal assertions.
 */
export const FIXTURE_DRAFT_G1_NO = {
  ...FIXTURE_DRAFT,
  revision: 4,
  active: ["N1", "N3", "N4", "P1", "Y1", "C1", "C11", "H1", "H4", "G1"],
  answers: { ...FIXTURE_DRAFT.answers, G1: "No" },
};

/**
 * FIXTURE_DRAFT, but submitted (Story 3.2): read-only everywhere regardless of the edit lock, no
 * Submit button, no chat panel, and a submitted_at date for the workspace's own strip.
 */
export const FIXTURE_DRAFT_SUBMITTED = {
  ...FIXTURE_DRAFT,
  status: "submitted",
  submitted_at: "2026-09-25T09:00:00Z",
};

/**
 * FIXTURE_DRAFT_SUBMITTED, but with a customer_number (FORM-218), for the submitted strip's own
 * "Customer <number>" display.
 */
export const FIXTURE_DRAFT_SUBMITTED_WITH_CUSTOMER_NUMBER = {
  ...FIXTURE_DRAFT_SUBMITTED,
  customer_number: "CUS-10023",
};
