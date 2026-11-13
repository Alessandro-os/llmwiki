"""I backend reali contro un finto endpoint HTTP: controlla come vengono costruite le richieste
e lette le risposte, senza rete e senza credenziali."""

from __future__ import annotations

import asyncio
import json
import math

import httpx

from llmwiki.config import LLMConfig
from llmwiki.llm import AnthropicLLM, OpenAICompatLLM, ToolResult

TOOLS = [{
    "name": "search", "description": "cerca",
    "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
}]


def test_openai_compatible_backend():
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if body.get("logprobs"):
            return httpx.Response(200, json={"choices": [{
                "message": {"role": "assistant", "content": "YES"},
                "logprobs": {"content": [{"token": "YES", "top_logprobs": [
                    {"token": "YES", "logprob": math.log(0.9)},
                    {"token": " no", "logprob": math.log(0.1)},
                ]}]},
            }]})
        if body.get("tools") and len(body["messages"]) == 2:
            return httpx.Response(200, json={"choices": [{"message": {
                "role": "assistant", "content": None,
                "tool_calls": [{"id": "c1", "type": "function", "function": {
                    "name": "search", "arguments": '{"query": "penali"}'}}],
            }}]})
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": "<think>ragiono</think>Risposta finale"}}]})

    async def scenario():
        llm = OpenAICompatLLM(LLMConfig(provider="openai", base_url="http://modello.test/v1"))
        await llm.http.aclose()
        llm.http = httpx.AsyncClient(base_url="http://modello.test/v1",
                                     transport=httpx.MockTransport(handler))
        assert await llm.complete(model="m", system="s", prompt="p") == "Risposta finale"

        confidence, method = await llm.judge(model="m", claim="c", passage="p")
        assert method == "logprobs" and abs(confidence - 0.9) < 1e-6

        conversation = llm.conversation(model="m", system="s", tools=TOOLS, user="domanda")
        turn = await conversation.next()
        assert turn.tool_calls[0].name == "search" and turn.tool_calls[0].args == {"query": "penali"}
        turn = await conversation.next([ToolResult("c1", "risultati")])
        assert turn.text == "Risposta finale" and not turn.tool_calls
        last = seen[-1]["messages"]
        assert last[-1] == {"role": "tool", "tool_call_id": "c1", "content": "risultati"}
        assert seen[-1]["tools"][0]["function"]["name"] == "search"
        await llm.aclose()

    asyncio.run(scenario())


def test_openai_judge_falls_back_without_logprobs():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("logprobs"):
            return httpx.Response(200, json={"choices": [{"message": {"content": "YES"}}]})
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"supported": false, "confidence": 0.9}'}}]})

    async def scenario():
        llm = OpenAICompatLLM(LLMConfig(provider="openai", base_url="http://modello.test/v1"))
        await llm.http.aclose()
        llm.http = httpx.AsyncClient(base_url="http://modello.test/v1",
                                     transport=httpx.MockTransport(handler))
        confidence, method = await llm.judge(model="m", claim="c", passage="p")
        # "non supportata, sicuro al 90%" diventa una probabilità di supporto del 10%
        assert method == "llm-json" and abs(confidence - 0.1) < 1e-6
        await llm.aclose()

    asyncio.run(scenario())


def test_anthropic_backend(monkeypatch):
    import anthropic
    import httpx2

    monkeypatch.setenv("ANTHROPIC_API_KEY", "chiave-di-test")
    seen: list[dict] = []

    def message(content, stop_reason="end_turn"):
        return httpx2.Response(200, json={
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        })

    def handler(request: httpx2.Request) -> httpx2.Response:
        body = json.loads(request.content)
        seen.append({"body": body, "beta": request.headers.get("anthropic-beta", "")})
        if body.get("tools") and len(body["messages"]) == 1:
            return message([
                {"type": "thinking", "thinking": "", "signature": "sig"},
                {"type": "tool_use", "id": "tu_1", "name": "search", "input": {"query": "penali"}},
            ], "tool_use")
        if "format" in body.get("output_config", {}):
            return message([{"type": "text", "text": '{"supported": true, "confidence": 0.8}'}])
        return message([{"type": "text", "text": "Risposta finale"}])

    async def scenario():
        llm = AnthropicLLM(LLMConfig(provider="anthropic"))
        llm.client = anthropic.AsyncAnthropic(
            http_client=anthropic.DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
            max_retries=0,
        )
        assert await llm.complete(model="claude-opus-5-5", system="s", prompt="p",
                                  effort="medium") == "Risposta finale"
        first = seen[-1]
        assert first["body"]["fallbacks"] == "default"
        assert "server-side-fallback-2026-07-01" in first["beta"]
        assert first["body"]["output_config"] == {"effort": "medium"}

        confidence, method = await llm.judge(model="claude-haiku-5-5", claim="c", passage="p")
        assert (confidence, method) == (0.8, "llm-json")
        judge = seen[-1]
        assert "fallbacks" not in judge["body"]  # Haiku non ha il rilancio lato server
        assert judge["body"]["output_config"]["format"]["type"] == "json_schema"

        conversation = llm.conversation(model="claude-opus-5-5", system="s", tools=TOOLS,
                                        user="domanda", effort="high")
        turn = await conversation.next()
        assert turn.tool_calls[0].name == "search" and turn.tool_calls[0].args == {"query": "penali"}
        turn = await conversation.next([ToolResult("tu_1", "risultati")])
        assert turn.text == "Risposta finale"
        sent = seen[-1]["body"]
        assert sent["tools"][0]["input_schema"]["required"] == ["query"]
        assert sent["cache_control"] == {"type": "ephemeral"}
        # il turno dell'assistente torna indietro intero, thinking compreso
        assert [block["type"] for block in sent["messages"][1]["content"]] == ["thinking", "tool_use"]
        assert sent["messages"][2]["content"][0] == {
            "type": "tool_result", "tool_use_id": "tu_1", "content": "risultati"}

    asyncio.run(scenario())
