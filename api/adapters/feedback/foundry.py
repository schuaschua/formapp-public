"""The production ``CategoryPort`` (Story 7.2/FORM-238, spine AD-18, AD-20): calls the hosted
agent's Responses endpoint -- the same URL shape ``adapters.chat.foundry.FoundryAgentGateway`` uses
for chat, ``{FOUNDRY_PROJECT_ENDPOINT}/agents/{FOUNDRY_AGENT_NAME}/endpoint/protocols/openai`` --
through the OpenAI-compatible ``openai`` SDK's async client, with no tools and temperature 0,
authenticated as the ``api`` managed identity (scope ``https://ai.azure.com/.default``).

Never exercised against real Azure in any test (no test may call Azure, spine AD-18); the unit
tests here inject a fake ``client``/``credential`` instead, exactly the seam this class exposes for
that purpose (the same seam ``FoundryAgentGateway`` uses).
"""

from typing import Any, Protocol

from openai import AsyncOpenAI

from domain.feedback_categories import FEEDBACK_CATEGORIES
from jobs.ports import CategoryPortError

# Same audience as adapters.chat.foundry.FOUNDRY_SCOPE: one hosted-agent Foundry project, one scope.
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
_API_VERSION = "v1"

_INSTRUCTIONS = (
    "You classify one piece of feedback about an AI life-insurance proposal assistant into exactly "
    "one category. Reply with only the category name below, nothing else, no punctuation: "
    + ", ".join(FEEDBACK_CATEGORIES)
)


class _TokenCredential(Protocol):
    async def get_token(self, *scopes: str) -> Any: ...


class FoundryCategoryPort:
    """See this module's docstring. ``client``/``credential`` are constructor seams for tests
    (spine AD-18); production code (``jobs.feedback``) leaves both at their defaults."""

    def __init__(
        self,
        *,
        project_endpoint: str,
        agent_name: str,
        model: str,
        credential: _TokenCredential | None = None,
        client: AsyncOpenAI | None = None,
    ) -> None:
        self._model = model
        # Built lazily in _token() when not given: azure-identity's async transport needs aiohttp,
        # same reason FoundryAgentGateway defers it (the 2026-09-27 deploy outage).
        self._credential = credential
        base_url = (
            f"{project_endpoint.rstrip('/')}/agents/{agent_name}"
            "/endpoint/protocols/openai"
        )
        self._client = client or AsyncOpenAI(
            api_key=self._token,
            base_url=base_url,
            default_query={"api-version": _API_VERSION},
        )

    @staticmethod
    def _default_credential() -> _TokenCredential:
        from azure.identity.aio import DefaultAzureCredential

        return DefaultAzureCredential()

    async def _token(self) -> str:
        if self._credential is None:
            self._credential = self._default_credential()
        token = await self._credential.get_token(FOUNDRY_SCOPE)
        return str(token.token)

    async def categorise(self, *, rating: int, comment: str) -> str:
        try:
            response = await self._client.responses.create(
                model=self._model,
                instructions=_INSTRUCTIONS,
                input=f"Rating: {rating}/5\nComment: {comment}",
                temperature=0,
                tools=[],
            )
        except Exception as exc:  # noqa: BLE001 -- any SDK/network failure ends this row cleanly
            raise CategoryPortError(
                "The categoriser couldn't classify this comment."
            ) from exc
        status = getattr(response, "status", "completed")
        if status not in ("completed", None):
            raise CategoryPortError(
                "The categoriser couldn't classify this comment."
            )
        return _output_text(response).strip()


def _output_text(response: Any) -> str:
    text = getattr(response, "output_text", None)
    return str(text) if text else ""
