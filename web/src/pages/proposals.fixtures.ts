// Shared test fixture for a freshly created draft (Story 1.8), used by both ProposalsPage.test.tsx
// and App.test.tsx so the wire shape isn't duplicated byte-for-byte in two files.
export const NEW_DRAFT = {
  id: "33333333-3333-4333-8333-333333333333",
  status: "draft",
  schema_version: 1,
  revision: 0,
  lock: { holder: "you", expires_at: null },
  active: ["C1"],
  answers: {},
  provenance: {},
  quote: null,
  display_name: "Untitled_Proposal_003",
};
