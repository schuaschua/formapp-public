"""Chat adapter: SSE relay to the hosted agent through the AgentGateway (spine AD-5, AD-18); Epic 4.

Story 4.5 builds this package out:

- ``gateway`` -- the ``AgentGateway`` protocol every Foundry call (Responses create/stream,
  conversation create, chat history read) goes through, and ``GatewayError`` (AD-18).
- ``foundry`` -- the production implementation, calling the hosted agent's Responses endpoint with
  the ``api`` managed identity (AD-9).
- ``stub`` -- the test-only implementation: scripted reply text and a scripted MCP tool plan
  (applied through the same domain functions the real ``/mcp`` server uses), mid-stream failure and
  timeout, driven by the injectable ``Clock`` (AD-18).
- ``turns`` -- chat-turn orchestration: opens a turn (``open_chat_turn``) and relays one turn's
  reply as the AD-5 SSE events (``run_chat_turn``).
- ``logging_events`` -- the turn-start/turn-end/AI-write log lines every AI-write alert query reads
  (AD-9, Observability, security.md rule 38), shared by ``turns`` and the ``/mcp`` ``patch_draft``
  tool so both paths log identically.

``turns`` and ``stub`` each wrap their own DB work that runs outside the normal per-REST-request
cycle in an explicit ``adapters.db.scope.scoped(...)`` (AD-17, security.md rule 37): the automatic
per-request middleware scope only covers the request that opens the turn, not the streaming body
that follows it. ``turns``' own conversation and end-of-turn writes are genuine chat-adapter
transactions, scoped by owner (``for_owner``), same as a normal REST write; ``stub``'s scripted
``patch_draft`` stands in for a real MCP tool call, so it's scoped by proposal (``for_proposal``),
same as the real ``/mcp`` server's own ``_authorize``.
"""
