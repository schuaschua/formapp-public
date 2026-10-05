"""The nightly feedback job (Story 7.1, spine AD-20): its own package, run with
``python -m jobs.feedback``, never imported by the request-serving api code (`api/domain`,
`api/adapters`, `AGENTS.md`: the agent reaches data only through the MCP server; this job is the
api's own batch code, so AD-10 still holds -- only ``api`` and this job read PostgreSQL).
"""
