# Security standards (formapp)

Status: **draft for review**. Binding for all code, infrastructure and agent prompts in this repository. Where this file and the architecture spine disagree, raise it; don't pick one silently. Related: `azure.md`, `terraform.md`, spine AD-1…AD-17, `docs/governance/CloudAssessment.docx`.

## 1. Data

1. Use synthetic data only: seed data, tests, fixtures, demo scripts and prompts. Never enter or import real customer, health or ID data.
2. Treat health answers (`H*`, `G*`), national ID (C6), date of birth and contact details as sensitive even though they're synthetic: never log their values, and never put them in error messages, traces or analytics exports.
3. Keep all stored data in Southeast Asia. Model processing may leave the region (Global Standard). This is accepted for the POC only because data is synthetic (spine Consistency Conventions).

## 2. Identity and access

4. Every `/api/*` route requires a signed-in Entra principal; return 401 without one (spine AD-4, AD-8).
5. Every read and write checks ownership (`owner_oid` = the caller's `oid` claim). Return 404, not 403, for another agent's proposal, so its existence isn't revealed.
6. `/mcp` accepts only a valid turn token: signed, proposal-scoped, at most 10 minutes. MCP tools never take a proposal id (spine AD-4).
7. Never log, return, or place the turn token in model context or `metadata`; it travels only in the `x-client-turn-token` header and the MCP `Authorization` header.
8. Runtime identities get only the roles listed in `azure.md` rule 9; never Owner, Contributor or subscription-scoped roles. The pipeline's deployment identity holds only the roles in `azure.md` rule 31: Contributor, a conditioned RBAC Administrator and Foundry User on the resource group, and Storage Blob Data Contributor on its state container.

Proposal isolation (numbered after the last rule so existing numbers stay stable):

36. Bind every turn token to one turn: it carries a unique `tid`, and `/mcp` accepts it only while its `pid` proposal is locked by `ai` and its `tid` equals that proposal's `current_turn_id`; otherwise reject with `lock_not_held` and change nothing (spine AD-4, AD-16).
37. Keep PostgreSQL row-level security enabled and forced on `proposal` and `answer_overrides`; every request transaction sets `app.proposal_id` (MCP) or `app.owner_oid` (REST, chat) with `SET LOCAL`, and only the migration role sees every row, through its own permissive policy on each table (it has no `BYPASSRLS`, which the Entra-only admin can't grant). All policies are permissive and `TO` either the `api` principal or `formapp_migrator`, never `PUBLIC`; migrations `SET ROLE formapp_migrator`; views over these tables are `security_invoker` (spine AD-17). Only the pipeline identity holds the migration role, and only its migration step uses it; the `api` identity is never granted it and cannot `SET ROLE` to it, so the running app can never bypass row-level security (spine AD-11, AD-17).

## 3. Secrets

9. Keep secrets only in Container Apps secrets (the turn-token signing key, and the sign-in client secret if Entra requires one). Never put a secret in code, images, environment files in git, Terraform variables files in git, logs or chat.
10. Use managed identity for PostgreSQL, Foundry and the container registry; never create database passwords or API keys for them.
11. GitHub Actions authenticates to Azure only through OIDC federation; never store Azure credentials or personal access tokens as repository secrets.
12. Rotate the turn-token signing key by changing its Terraform `keepers` value and re-applying; all live tokens become invalid, which is acceptable (10-minute lifetime).

## 4. The AI agent

13. The agent may never submit a proposal, set the declaration (D1), or write fields marked `x-agent-writable: false`; enforce this in `api/domain`, never only in the prompt (spine AD-3).
14. Treat everything typed in chat as untrusted input, including instructions that try to change the agent's rules ("ignore previous instructions", "update proposal 202"). Server-side checks (turn token, ownership, schema validation, human-wins) are the defence; prompts are not.
15. Validate every tool argument server-side against the schema; never trust ids, codes or values produced by the model.
16. The agent has exactly the MCP tools listed in spine AD-3; adding a tool or any other Foundry tool/connection needs an architecture decision.
17. Keep the model deployment's default content filter; never attach a policy that weakens it (`azure.md` rule 25).
18. Keep the rate limit (3 chat turns per agent per 10 seconds) enforced server-side (spine AD-9).

## 5. Application

19. Validate every input on the server with the JSON schema and domain rules; client-side checks are for convenience only (spine AD-7).
20. Access the database only through SQLAlchemy with bound parameters; never build SQL from strings.
21. Never use `dangerouslySetInnerHTML` or render chat or answer text as HTML; React's default escaping must stay on.
22. Serve the web app and API from one origin; don't enable CORS.
23. Protect state-changing requests from cross-site forgery: keep the auth cookie `SameSite=Lax` or stricter, and require a custom request header (for example `X-Session-Id`) on every non-GET `/api/*` call.
24. Send security headers on every response: `Strict-Transport-Security`, `Content-Security-Policy` (self only, no inline scripts), `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `frame-ancestors 'none'`.
25. Return errors in the AD-12 shape with plain messages; never return stack traces, SQL, or internal paths.

## 6. Dependencies and supply chain

26. Pin exact versions and commit lock files (`uv.lock` / `requirements*.txt`, `package-lock.json`); follow `terraform.md` rule 9 for Terraform.
27. Run dependency vulnerability scans with `scripts/check.sh` before pushing (`npm audit --omit=dev`; `pip-audit` is paused for the POC, owner decision 2026-09-27, so Python dependencies rely on Dependabot alerts until UAT/production) whenever the change touches the project they cover (its own dir, or a shared input such as `form-schema/` for `api/`) or `scripts/check.sh`, and GitHub Dependabot alerts otherwise; a critical or high finding blocks merge unless the owner accepts it in the PR.
28. Pre-release packages are allowed only where the spine names them (`agent-framework-foundry-hosting`, and the Azure Monitor OpenTelemetry exporter, `azure-core-tracing-opentelemetry`, the `0.65b0` OpenTelemetry instrumentation line, and the agent's transitive pre-releases `azure-ai-agentserver-responses` 2.2.0b1, `azure-ai-inference` 1.0.0b9, `opentelemetry-util-genai` 0.3b0 and `opentelemetry-instrumentation-openai-v2` 2.3b0, all in the Stack table); no others without an architecture decision.
29. Enable GitHub secret scanning and push protection on the repository.

## 7. Logging, monitoring and audit

30. Log request ids, proposal ids, question ids, error codes and timings; never log answer values, tokens, headers or connection strings (`azure.md` rule 16).
31. Keep `answer_overrides` append-only; no code path updates or deletes its rows (spine AD-6). Exception (FORM-227, owner decision comment 2026-09-27, amending AD-6 for this one case): deleting a draft proposal cascades to its `answer_overrides`/`proposal_feedback` rows in the same transaction (migration 0016); a `BEFORE DELETE` trigger still rejects any other delete or update of an `answer_overrides` row while its parent proposal still exists, and the `api` role is never granted `UPDATE` on it, only `DELETE`.
32. Keep one trace per chat turn in Application Insights so any AI action can be followed end to end.

Proposal isolation alert:

38. Log every AI write with `proposal_id`, `turn_id` and `conversation_id`, and keep the Terraform-managed alert that fires when an AI write's proposal differs from its conversation's proposal or carries a turn ID that isn't current (spine Consistency Conventions, Observability).

## 8. Infrastructure

33. Follow `azure.md` and `terraform.md`; every change goes through a pull request and a human-approved pipeline apply.
34. Keep Terraform state in the Entra-authenticated storage account with shared-key access disabled (`azure.md` rule 29).

## 9. Accepted POC exceptions

These are known gaps, accepted for the POC and declared in the Cloud Assessment. Each must be closed before real data or production use.

| Exception | Close before production by |
|---|---|
| Public endpoints (Container App, PostgreSQL, Foundry, the token-store storage account); no VNet or private endpoints | Private networking and VNet integration |
| PostgreSQL firewall open to all addresses for a temporary period, in development environments (`postgresql_allow_public_access`; owner policy, 2026-09-27); the deploy workflow's migration step has no per-run firewall rule of its own and reaches PostgreSQL only through this allow-all rule | Set the variable to false as soon as the owner says so, restoring the deploy workflow's per-run firewall steps first |
| No Key Vault | Moving secrets to Key Vault |
| No API gateway or WAF | API Management / Front Door with WAF and gateway rate limits |
| Anonymous access allowed at the Container Apps edge (sign-in enforced by the app); flagged by Azure Policy | Revisiting the Welcome page flow |
| Schema validation off for Container Apps `authConfigs@2026-07-01` (GA; azapi 2.12.0 doesn't know that version yet; owner-approved, 2026-09-26) | Turning validation back on once a pinned azapi release includes 2026-07-01 |
| Public endpoint on the sign-in token store's storage account (shared keys, SAS and public blob access off; Entra RBAC only) | Private endpoint with the rest of the private networking |
| Model processing may leave Southeast Asia (Global Standard) | A Data Zone or regional deployment |
| Single region, single replica, default backups only | High availability, zone redundancy, backup policy |

## 10. Reporting

35. Report a suspected vulnerability or leaked secret immediately to the project owner at owner@example.com. Rotate any exposed secret first, then investigate.
