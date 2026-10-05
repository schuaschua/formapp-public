<!-- bmad:context -->
<!-- Verified 2026-09-26 against (not yet committed). Managed by bmad-project-context; edits inside this block are replaced on refresh. Keep anything you want preserved outside the markers. -->

## formapp

Agent-first life insurance proposal form POC: an insurance agent chats with an AI that fills a 5-page form. React + FastAPI (MCP server) on Azure Container Apps, PostgreSQL, a Microsoft Agent Framework agent hosted on Microsoft Foundry, Terraform, all in Southeast Asia. Planning lives in `_bmad-output/` (spec, architecture spine, UX, epics); work is tracked in Jira project FORM (example.atlassian.net).

This is the public copy: the planning folder `_bmad-output/` (apart from `DESIGN.md`, which a web test reads), the agents' memory in `_bmad/memory/` and `docs/governance/` are not included, and names, IDs and Azure resource names are placeholders.

## Policy

- Branch from `dev` as `FORM-<n>-<short-name>`; merge back to `dev` by pull request. Promote `dev` to `main` only by pull request.
- Start every commit message with the Jira key, e.g. `FORM-12: add drafts list`.
- Never push directly to `dev` or `main`; changes to `infra/` and `.github/workflows/` always go through a pull request.
- Never run `terraform apply` or `destroy` locally, and never destroy the environment; applies run only from the pipeline's deploy workflow, which the owner starts by hand on `main`.
- Never commit Terraform state, `.terraform/`, `.env` files, keys or secrets; secrets live in Container Apps secrets, never in code or images.
- Never read, search or write documents outside this repository; keep scratch files in `.work/` (gitignored), never in `/tmp` or other folders.
- Use synthetic data only; never add real customer or health data anywhere (seed data, tests, fixtures, prompts).
- Never edit `_bmad/`, `.claude/skills/`, `.agents/skills/` or `.github/agents/`; they change only through a BMad update. Exceptions: `_bmad/custom/` changes only through `bmad-customize`; `_bmad/memory/<agent>/` is written only by that agent (Jules's sanctum; Scrooge's `stories.json` and `savings.json`); new custom agents are built into `skills/` and linked into `.claude/skills/`. Jules (`agent-jules`) and Scrooge (`agent-scrooge`) come from the BMad org module (github.com/example-org/bmad-org-kit) and change only through a kit update.
- Never hand-edit `SPEC.md`, `ARCHITECTURE-SPINE.md`, `DESIGN.md` or `EXPERIENCE.md`; change them through their BMad skill (`bmad-spec`, `bmad-architecture`, `bmad-ux`), which re-derives them from their `.memlog.md`.
- Never edit or reorder a `.memlog.md`; append through `_bmad/scripts/memlog.py`.
- Never edit a released `form-schema/v<N>.json`; add `v<N+1>.json` instead, because existing proposals pin their version.
- Never lower the coverage thresholds (`api/` 80%, `web/` 60%) to make a check pass; add tests instead.

## Where things are

- Binding architecture rules (AD-1…AD-16): `_bmad-output/planning-artifacts/architecture/architecture-formapp-2026-09-25/ARCHITECTURE-SPINE.md` — read the ADs a story cites before implementing it.
- UI look and behaviour: `_bmad-output/planning-artifacts/ux-designs/ux-formapp-2026-09-25/DESIGN.md` and `EXPERIENCE.md`; mockups in its `mockups/`.
- Stories and acceptance criteria: `_bmad-output/planning-artifacts/epics.md` (story ids match Jira summaries, e.g. "1.6 …").
- Question set and product catalogue: `_bmad-output/seed-content/form-content-draft.md`.
- Writing Terraform or Azure config? Follow `docs/standards/terraform.md` and `docs/standards/azure.md`.
- Writing any code? Follow `docs/standards/security.md` and `docs/standards/coding-style.md`.

## Running and verifying

- Run `scripts/check.sh` before every push and put its summary in the pull request; add `--plan` (needs `az login`) for any `infra/` change. GitHub Actions runs only the deploy and destroy workflows, and no status check gates merges.
- TODO (verify on first refresh): Python 3.13 for `api/` and `agent/`; tests with `pytest --cov` (api ≥80%); Node 22 LTS for `web/`, tests with Vitest coverage (≥60%).
- TODO (verify on first refresh): `agent/` needs `pip install --pre` because `agent-framework-foundry-hosting` is a beta package pinning `mcp<2`; `api/` uses `mcp` 2.x — keep them in separate environments.

## Conventions that differ from defaults

- Prices are RM, computed only in `api/domain`; the web app displays `quote` and never calculates prices.
- Answer keys are the schema question ids (`C1`, `H10`), everywhere: database, REST, MCP and errors.
- The agent reaches data only through the MCP server; never give `agent/` database access or import from `api/`.

<!-- /bmad:context -->
