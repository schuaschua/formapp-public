# Coding style (formapp)

Status: **draft for review**. Formatting and most style are decided by tools with their default settings (Python's run locally, the rest checked in CI); this file holds only what the tools can't check. Related: `security.md`, `terraform.md`, spine Consistency Conventions.

## 1. Tools (defaults)

| Area | Tool | Setting |
|---|---|---|
| Python formatting | `ruff format` (run locally, not in CI) | defaults |
| Python linting | `ruff check` (run locally, not in CI) | default rules plus `I` (import order), `B` (bugbear), `UP` (pyupgrade), `S` (security) |
| Python types | `mypy` (run locally, not in CI) | `strict` for `api/domain/`; default elsewhere |
| TypeScript | `tsc` | `"strict": true` |
| TypeScript/React linting | ESLint | recommended + `typescript-eslint` recommended + `react-hooks` |
| TypeScript/React formatting | Prettier | defaults |
| Terraform | `terraform fmt`, `tflint` | defaults + the `azurerm` ruleset (see `terraform.md`) |

1. Never disable a rule inline (`# noqa`, `eslint-disable`, `# type: ignore`) without a comment saying why; never disable one for a whole file.
2. A failing format or lint check in `scripts/check.sh` blocks the pull request; fix the code, don't loosen the config. The Python checks run locally only in the POC: run `ruff format`, `ruff check` and `mypy` before pushing.

## 2. Everywhere

3. Use the schema question ids (`C1`, `H10`) as keys and names for answers everywhere; never invent aliases like `firstName` for C1 (spine Consistency Conventions).
4. Calculate money only with `Decimal` in Python; never use floats for prices. On the wire, amounts stay JSON numbers as the spine defines them (AD-5 `quote`, AD-7 currency answers), rounded to 2 decimals and parsed straight into `Decimal`.
5. Dates are `YYYY-MM-DD`, timestamps ISO 8601 UTC.
6. Comments explain why, not what. Reference the rule you're implementing where it isn't obvious, e.g. `# AD-6: human edits are final`.
7. No dead code, commented-out code or TODOs without a Jira key (`# TODO FORM-42: …`).

## 3. Python (`api/`, `agent/`)

8. Type-hint every function signature.
9. Keep `api/domain/` framework-free: it never imports FastAPI, SQLAlchemy, MCP or HTTP libraries (spine AD-2). Adapters call the domain; the domain never calls adapters.
10. Raise domain errors carrying an AD-12 error code; adapters map them to responses. Never return error dicts from the domain, and never use a bare `except:`.
11. Use `async` for I/O in adapters; keep domain functions synchronous and pure where possible.
12. Read configuration only through one settings object (`pydantic-settings`) built from environment variables; never read `os.environ` elsewhere.
13. Docstrings (one line is fine) on public functions in `api/domain/` and on every MCP tool, since the tool docstring is what the model reads.

## 4. TypeScript / React (`web/`)

14. Function components and hooks only.
15. All API calls go through one client module (`web/src/api/`); components never call `fetch` directly.
16. Never implement business rules in the web app: no price calculation, and client-side validation is convenience only; the server decides (spine AD-7, `security.md` rule 19).
17. Use design tokens from `DESIGN.md` as CSS variables; never hard-code colours, font sizes or spacing.
18. Put user-facing text in one strings module, worded as in `EXPERIENCE.md` Voice and Tone; never scatter UI copy through components.
19. Meet the accessibility floor in `EXPERIENCE.md` (labels, focus order, keyboard use, 16px/14px minimums).

## 5. Tests

20. Every acceptance criterion has at least one test; name the story in the test (`test_story_1_10_clearing_text_answer_stays_blank`, or `describe("1.10 …")`).
21. Python tests live in `api/tests/` and `agent/tests/`, mirroring the package layout, and run with `pytest`; React tests sit next to the component as `*.test.tsx` and run with Vitest and Testing Library.
22. Test behaviour, not implementation: assert on responses, database state and what the user sees, not on private functions or component internals.
23. Unit tests never call real Azure, Foundry or the network; use fakes. Integration tests use a real PostgreSQL in a container. Use the test seams (spine AD-18): never sleep in a test to wait for time-based behaviour, move the injectable `Clock` instead; never call the real Foundry agent in unit or integration tests, use the `AgentGateway` stub; never run functional tests against `demo`, where only the read-only post-deploy smoke check runs.
24. Use synthetic fixtures only, built from the seed content (Ally Macbeal, the RM examples); never real data (`security.md` rule 1).
25. Don't lower coverage thresholds (`api/` 80%, `web/` 60%); agent behaviour is checked by its evaluation set instead.

## 6. Pull requests

26. One story (or one subtask) per pull request, into `dev`, titled with the Jira key: `FORM-12: drafts list`.
27. The description links the Jira story and lists which acceptance criteria it covers; CI must be green before review.
28. Keep pull requests small enough to review in one sitting; split large stories by subtask.

## 7. Database migrations

29. Every Alembic migration must be backward-compatible (expand, then contract): add columns, tables and constraints first, and remove or rename only in a later release, because the old `api` version briefly runs against the new schema. The pipeline runs migrations before the new image goes live (spine AD-10, AD-11).

## Not applied in the POC

| Item | Revisit when |
| --- | --- |
| `ruff format`, `ruff check` and `mypy` in CI for `api/` and `agent/` (removed 2026-09-27 to speed up CI) | A UAT or production environment is added (restore the full CI suite). |
