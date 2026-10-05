"""Feedback adapters (Story 7.2/FORM-238, spine AD-18, AD-20).

- ``foundry`` -- the production ``jobs.ports.CategoryPort``: calls the hosted agent's Responses
  endpoint with no tools and temperature 0, over the ``api`` managed identity, mirroring
  ``adapters.chat.foundry.FoundryAgentGateway``'s client/credential pattern.

Tests inject a fake ``client``/``credential`` (spine AD-18); no test calls Foundry.
"""
