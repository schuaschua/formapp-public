# formapp

Agent-first life insurance proposal form, a proof of concept: an insurance agent chats with an AI that fills a 5-page form. React + FastAPI (MCP server) on Azure Container Apps, PostgreSQL, and a Microsoft Agent Framework agent hosted on Microsoft Foundry, deployed with Terraform.

This is a public copy of the code. All data is synthetic; names, IDs and Azure resource names are placeholders, so set your own values in `infra/demo/*/terraform.tfvars` and `infra/bootstrap/state-backend.sh` before deploying. See `AGENTS.md` and `docs/standards/` for how the project is built and checked.
