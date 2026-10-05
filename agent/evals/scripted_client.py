"""A scripted stand-in for the model: it plays fixed tool calls, then a fixed reply (no Azure).

Used by the offline evaluation run in CI and by the agent's tests. Each step is a list of tool calls
the "model" makes; after the last step it answers with ``final_text``. It records every request it
is sent (messages and options), so tests can check what would have reached a real model.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, ClassVar

from agent_framework import (
    BaseChatClient,
    ChatResponse,
    ChatResponseUpdate,
    Content,
    FunctionInvocationLayer,
    Message,
    ResponseStream,
)
from agent_framework.observability import ChatTelemetryLayer


@dataclass(frozen=True)
class ScriptedCall:
    """One tool call the scripted model makes."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)


@dataclass
class ModelRequest:
    """What one model request carried: its messages, as text, and its options."""

    messages: list[Message]
    options: dict[str, Any]

    def text(self) -> str:
        """Everything the model would see in this request, as one string."""
        parts = [json.dumps(self.options, default=str)]
        for message in self.messages:
            parts.append(json.dumps(message.to_dict(), default=str))
        return "\n".join(parts)


class _RawScriptedChatClient(BaseChatClient[Any]):
    STORES_BY_DEFAULT: ClassVar[bool] = False
    OTEL_PROVIDER_NAME: ClassVar[str] = "formapp.scripted"

    def __init__(
        self,
        steps: Sequence[Sequence[ScriptedCall]] = (),
        final_text: str = "Done.",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.steps = [list(step) for step in steps]
        self.final_text = final_text
        self.requests: list[ModelRequest] = []

    def _next_contents(self, messages: Sequence[Message]) -> list[Content]:
        # Steps already played in this turn: assistant tool-call messages after the last user one.
        done = 0
        for message in reversed(messages):
            if message.role == "user":
                break
            if message.role == "assistant" and any(
                content.type == "function_call" for content in message.contents
            ):
                done += 1
        if done < len(self.steps):
            return [
                Content.from_function_call(
                    call_id=f"call-{done}-{index}",
                    name=call.name,
                    arguments=dict(call.arguments),
                )
                for index, call in enumerate(self.steps[done])
            ]
        return [Content.from_text(self.final_text)]

    def _inner_get_response(
        self,
        *,
        messages: Sequence[Message],
        stream: bool,
        options: Mapping[str, Any],
        **kwargs: Any,
    ) -> Any:
        self.requests.append(ModelRequest(list(messages), dict(options)))
        contents = self._next_contents(messages)
        if stream:

            async def _updates() -> Any:
                yield ChatResponseUpdate(role="assistant", contents=contents)

            return ResponseStream(_updates(), finalizer=ChatResponse.from_updates)

        async def _response() -> ChatResponse:
            return ChatResponse(messages=[Message(role="assistant", contents=contents)])

        return _response()


class ScriptedChatClient(
    FunctionInvocationLayer[Any],
    ChatTelemetryLayer[Any],
    _RawScriptedChatClient,
):
    """The scripted model with the same tool-calling and telemetry layers as the Foundry client."""
