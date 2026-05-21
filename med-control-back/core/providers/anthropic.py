from collections.abc import AsyncGenerator

import anthropic as anthropic_sdk

from .base import BaseProvider


class AnthropicProvider(BaseProvider):
    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        self.model = model
        self._client = anthropic_sdk.AsyncAnthropic(api_key=api_key)

    @property
    def supports_tools(self) -> bool:
        return True

    def _normalize_messages(self, messages: list[dict]) -> tuple[list[dict] | str, list[dict]]:
        """
        Convierte el historial interno (formato Ollama/OpenAI) al formato de Anthropic.
        Retorna (system_blocks, messages_list).
        """
        system_text = ""
        result: list[dict] = []
        tool_id_counter = 0
        pending_tool_ids: list[str] = []

        for msg in messages:
            role = msg["role"]

            if role == "system":
                system_text = msg["content"]

            elif role == "user":
                result.append({"role": "user", "content": msg["content"]})

            elif role == "assistant":
                if "tool_calls" in msg:
                    content: list[dict] = []
                    if msg.get("content"):
                        content.append({"type": "text", "text": msg["content"]})

                    pending_tool_ids = []
                    for tc in msg["tool_calls"]:
                        tool_id = f"toolu_{tool_id_counter:02d}"
                        tool_id_counter += 1
                        pending_tool_ids.append(tool_id)
                        content.append({
                            "type": "tool_use",
                            "id": tool_id,
                            "name": tc["function"]["name"],
                            "input": tc["function"]["arguments"] or {},
                        })
                    result.append({"role": "assistant", "content": content})
                else:
                    result.append({"role": "assistant", "content": msg["content"]})

            elif role == "tool":
                tool_id = pending_tool_ids.pop(0) if pending_tool_ids else f"toolu_{tool_id_counter:02d}"
                result.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": msg["content"],
                        }
                    ],
                })

        system: list[dict] | str = (
            [{"type": "text", "text": system_text, "cache_control": {"type": "ephemeral"}}]
            if system_text
            else ""
        )
        return system, result

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        converted = [
            {
                "name": t["function"]["name"],
                "description": t["function"]["description"],
                "input_schema": t["function"]["parameters"],
            }
            for t in tools
        ]
        if converted:
            converted[-1]["cache_control"] = {"type": "ephemeral"}
        return converted

    async def stream(
        self,
        messages: list[dict],
        tools: list[dict],
    ) -> AsyncGenerator[dict, None]:
        system, normalized = self._normalize_messages(messages)
        converted_tools = self._convert_tools(tools) if tools else []

        async with self._client.messages.stream(
            model=self.model,
            system=system,
            messages=normalized,
            tools=converted_tools or anthropic_sdk.NOT_GIVEN,
            max_tokens=4096,
        ) as stream:
            async for event in stream:
                if (
                    hasattr(event, "type")
                    and event.type == "content_block_delta"
                    and hasattr(event.delta, "text")
                ):
                    yield {"type": "token", "content": event.delta.text}

            final = await stream.get_final_message()

        tool_calls = [
            {"name": block.name, "arguments": block.input}
            for block in final.content
            if block.type == "tool_use"
        ]
        if tool_calls:
            yield {"type": "tool_calls", "calls": tool_calls}
