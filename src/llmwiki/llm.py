"""Accesso ai modelli. Tre backend dietro la stessa interfaccia:

- AnthropicLLM: Claude tramite l'SDK ufficiale.
- OpenAICompatLLM: qualunque endpoint /chat/completions (Ollama, LM Studio, vLLM, OpenRouter...).
  È anche l'unico che espone i logprob, cioè la confidenza vera del decision model.
- MockLLM: nessun modello, risposte deterministiche; serve a provare la pipeline e nei test.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from dataclasses import dataclass, field

from . import prompts
from .config import LLMConfig


class LLMError(Exception):
    """Errore del modello. `status` è il codice HTTP quando il server ha risposto con un
    rifiuto: distingue "questa richiesta non va" da "il server non c'è"."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def rejected(self) -> bool:
        return self.status is not None and 400 <= self.status < 500


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolResult:
    id: str
    content: str
    is_error: bool = False


@dataclass
class Turn:
    text: str
    tool_calls: list[ToolCall] = field(default_factory=list)


JUDGE_SCHEMA = {
    "type": "object",
    "properties": {"supported": {"type": "boolean"}, "confidence": {"type": "number"}},
    "required": ["supported", "confidence"],
    "additionalProperties": False,
}


def parse_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise LLMError(f"risposta non JSON: {text[:200]!r}") from None
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"risposta non JSON: {text[:200]!r}") from exc
    if not isinstance(value, dict):
        raise LLMError("risposta JSON non è un oggetto")
    return value


class LLM:
    """Interfaccia comune. `kind` è solo un'etichetta (log, mock), non cambia la richiesta."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self.calls: dict[str, int] = {}

    def _count(self, kind: str) -> None:
        self.calls[kind] = self.calls.get(kind, 0) + 1

    async def complete(self, *, model: str, system: str, prompt: str, effort: str = "",
                       kind: str = "") -> str:
        raise NotImplementedError

    async def complete_json(self, *, model: str, system: str, prompt: str, schema: dict,
                            effort: str = "", kind: str = "") -> dict:
        system = (
            f"{system}\n\nRispondi solo con un oggetto JSON conforme a questo schema:\n"
            f"{json.dumps(schema, ensure_ascii=False)}"
        )
        return parse_json(await self.complete(model=model, system=system, prompt=prompt,
                                              effort=effort, kind=kind))

    async def judge(self, *, model: str, claim: str, passage: str) -> tuple[float, str]:
        """Probabilità che `passage` supporti `claim`, più il metodo usato per stimarla."""
        data = await self.complete_json(
            model=model, system=prompts.JUDGE_JSON, prompt=prompts.judge_prompt(claim, passage),
            schema=JUDGE_SCHEMA, effort=self.cfg.judge_effort, kind="judge",
        )
        try:
            confidence = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        if data.get("supported") is False and confidence > 0.5:
            # il modello ha dato la confidenza nel proprio "no": la ribalto
            confidence = 1.0 - confidence
        return confidence, "llm-json"

    def conversation(self, *, model: str, system: str, tools: list[dict], user: str,
                     effort: str = "") -> Conversation:
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


class Conversation:
    async def next(self, results: list[ToolResult] | None = None,
                   user_text: str | None = None) -> Turn:
        raise NotImplementedError


# ------------------------------------------------------------------ Anthropic

# Modelli su cui un rifiuto dei classificatori può essere rilanciato lato server.
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicLLM(LLM):
    def __init__(self, cfg: LLMConfig) -> None:
        super().__init__(cfg)
        import anthropic

        self._anthropic = anthropic
        # Credenziali risolte dall'SDK: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN o `ant auth login`.
        self.client = anthropic.AsyncAnthropic(max_retries=4, timeout=cfg.timeout)

    async def _create(self, *, model: str, kind: str, **kwargs):
        anthropic = self._anthropic
        self._count(kind)
        try:
            if self.cfg.refusal_fallbacks and model.startswith(_FALLBACK_MODELS):
                response = await self.client.beta.messages.create(
                    model=model, betas=[_FALLBACK_BETA], fallbacks="default", **kwargs
                )
            else:
                response = await self.client.messages.create(model=model, **kwargs)
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "credenziali Anthropic mancanti o non valide: imposta ANTHROPIC_API_KEY "
                "oppure esegui `ant auth login`"
            ) from exc
        except anthropic.RateLimitError as exc:
            raise LLMError("limite di richieste Anthropic raggiunto: abbassa index.concurrency") from exc
        except anthropic.APIStatusError as exc:
            raise LLMError(f"errore API Anthropic {exc.status_code}: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError(f"connessione ad Anthropic non riuscita: {exc}") from exc
        if response.stop_reason == "refusal":
            raise LLMError("il modello ha rifiutato la richiesta (stop_reason: refusal)")
        return response

    @staticmethod
    def _text(response) -> str:
        return "".join(block.text for block in response.content if block.type == "text").strip()

    async def complete(self, *, model, system, prompt, effort="", kind="") -> str:
        kwargs: dict = {}
        if effort:
            kwargs["output_config"] = {"effort": effort}
        response = await self._create(
            model=model, kind=kind, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": prompt}], **kwargs,
        )
        if response.stop_reason == "max_tokens":
            raise LLMError("risposta troncata (max_tokens)")
        return self._text(response)

    async def complete_json(self, *, model, system, prompt, schema, effort="", kind="") -> dict:
        output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
        if effort:
            output_config["effort"] = effort
        response = await self._create(
            model=model, kind=kind, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": prompt}], output_config=output_config,
        )
        return parse_json(self._text(response))

    def conversation(self, *, model, system, tools, user, effort="") -> Conversation:
        return _AnthropicConversation(self, model, system, tools, user, effort)


class _AnthropicConversation(Conversation):
    def __init__(self, llm: AnthropicLLM, model, system, tools, user, effort) -> None:
        self.llm, self.model, self.system, self.effort = llm, model, system, effort
        self.tools = [
            {"name": t["name"], "description": t["description"], "input_schema": t["parameters"]}
            for t in tools
        ]
        self.messages: list[dict] = [{"role": "user", "content": user}]

    async def next(self, results=None, user_text=None) -> Turn:
        if results:
            content: list[dict] = []
            for result in results:
                block = {"type": "tool_result", "tool_use_id": result.id, "content": result.content}
                if result.is_error:
                    block["is_error"] = True
                content.append(block)
            if user_text:
                content.append({"type": "text", "text": user_text})
            self.messages.append({"role": "user", "content": content})
        elif user_text:
            self.messages.append({"role": "user", "content": user_text})

        kwargs: dict = {}
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        response = await self.llm._create(
            model=self.model, kind="agent", max_tokens=16000, system=self.system,
            tools=self.tools, messages=self.messages,
            cache_control={"type": "ephemeral"},  # il prefisso della conversazione si riusa a ogni passo
            **kwargs,
        )
        # Il contenuto torna indietro intero: i blocchi di thinking vanno riproposti invariati.
        self.messages.append({"role": "assistant", "content": response.content})
        if response.stop_reason == "max_tokens":
            raise LLMError("risposta dell'agente troncata (max_tokens)")
        calls = [
            ToolCall(block.id, block.name, dict(block.input))
            for block in response.content if block.type == "tool_use"
        ]
        return Turn(self.llm._text(response), calls)


# ------------------------------------------------------------------ compatibile OpenAI


class OpenAICompatLLM(LLM):
    def __init__(self, cfg: LLMConfig) -> None:
        super().__init__(cfg)
        import httpx

        self._httpx = httpx
        headers = {}
        key = os.environ.get(cfg.api_key_env or "", "")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        self.http = httpx.AsyncClient(
            base_url=cfg.base_url.rstrip("/"), headers=headers, timeout=cfg.timeout
        )
        self._logprobs_ok = True
        self._judge_mode = 0

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _chat(self, body: dict, kind: str) -> dict:
        httpx = self._httpx
        self._count(kind)
        last: Exception | None = None
        for attempt in range(4):
            try:
                response = await self.http.post("/chat/completions", json=body)
            except httpx.HTTPError as exc:
                last = LLMError(f"endpoint {self.cfg.base_url} non raggiungibile: {exc!r}")
            else:
                if response.status_code == 200:
                    return response.json()
                last = LLMError(f"errore {response.status_code} dal modello: {response.text[:300]}",
                                response.status_code)
                if last.rejected and response.status_code not in (408, 409, 429):
                    raise last
            await asyncio.sleep(min(2 ** attempt, 20))
        raise last  # type: ignore[misc]

    @staticmethod
    def _content(data: dict) -> str:
        content = data["choices"][0]["message"].get("content") or ""
        return re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()

    def _effort(self, effort: str) -> dict:
        if self.cfg.send_reasoning_effort and effort in ("none", "low", "medium", "high"):
            return {"reasoning_effort": effort}
        return {}

    async def complete(self, *, model, system, prompt, effort="", kind="") -> str:
        data = await self._chat({
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            **self._effort(effort),
        }, kind)
        return self._content(data)

    async def complete_json(self, *, model, system, prompt, schema, effort="", kind="") -> dict:
        body = {
            **self._effort(effort),
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema, "strict": True},
            },
        }
        try:
            data = await self._chat(body, kind)
        except LLMError as exc:
            if not exc.rejected:
                raise  # server spento o in errore: ripetere la richiesta non serve
            # server che non conosce response_format: schema nel prompt
            return await super().complete_json(model=model, system=system, prompt=prompt,
                                               schema=schema, effort=effort, kind=kind)
        return parse_json(self._content(data))

    async def judge(self, *, model, claim, passage) -> tuple[float, str]:
        """Decision model: una sola parola in uscita, la confidenza è la probabilità del token."""
        if self._logprobs_ok:
            confidence = await self._judge_logprobs(model, claim, passage)
            if confidence is not None:
                return confidence, "logprobs"
            self._logprobs_ok = False  # questo server non li espone: non riprovo a ogni citazione
        return await super().judge(model=model, claim=claim, passage=passage)

    # Tre modi di ottenere un sì/no con la sua probabilità, dal più veloce al più lento:
    # ragionamento spento, modello che non ragiona, modello che ragiona comunque (si guarda il
    # primo token della risposta, dopo il ragionamento). Quello che funziona viene ricordato.
    _JUDGE_MODES = (
        {"max_tokens": 4, "reasoning_effort": "none"},
        {"max_tokens": 4},
        {"max_tokens": 2048},
    )

    async def _judge_logprobs(self, model: str, claim: str, passage: str) -> float | None:
        for mode in range(self._judge_mode, len(self._JUDGE_MODES)):
            body = {
                "model": model,
                "messages": [
                    {"role": "system", "content": prompts.JUDGE_WORD},
                    {"role": "user", "content": prompts.judge_prompt(claim, passage)},
                ],
                "temperature": 0, "logprobs": True, "top_logprobs": 10,
                **self._JUDGE_MODES[mode],
            }
            try:
                confidence = self._yes_probability(await self._chat(body, "judge"))
            except LLMError as exc:
                if not exc.rejected:
                    raise  # server irraggiungibile: non significa che i logprob non ci siano
                confidence = None
            if confidence is not None:
                self._judge_mode = mode
                return confidence
        return None

    @staticmethod
    def _yes_probability(data: dict) -> float | None:
        try:
            tokens = data["choices"][0]["logprobs"]["content"]
        except (KeyError, IndexError, TypeError):
            return None
        for token in tokens or []:
            yes = no = 0.0
            for candidate in token.get("top_logprobs") or []:
                word = candidate.get("token", "").strip().lower()
                probability = math.exp(candidate.get("logprob", -100.0))
                if word and "yes".startswith(word):
                    yes += probability
                elif word and "no".startswith(word):
                    no += probability
            if yes + no > 0.2:
                return yes / (yes + no)
        return None

    def conversation(self, *, model, system, tools, user, effort="") -> Conversation:
        return _OpenAIConversation(self, model, system, tools, user, self._effort(effort))


class _OpenAIConversation(Conversation):
    def __init__(self, llm: OpenAICompatLLM, model, system, tools, user, extra=None) -> None:
        self.llm, self.model, self.extra = llm, model, extra or {}
        self.tools = [{"type": "function", "function": t} for t in tools]
        self.messages: list[dict] = [
            {"role": "system", "content": system}, {"role": "user", "content": user},
        ]

    async def next(self, results=None, user_text=None) -> Turn:
        for result in results or []:
            self.messages.append(
                {"role": "tool", "tool_call_id": result.id, "content": result.content}
            )
        if user_text:
            self.messages.append({"role": "user", "content": user_text})
        data = await self.llm._chat(
            {"model": self.model, "messages": self.messages, "tools": self.tools, **self.extra},
            "agent"
        )
        message = data["choices"][0]["message"]
        self.messages.append(message)
        calls = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function", {})
            try:
                args = json.loads(function.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_invalid_json": function.get("arguments")}
            calls.append(ToolCall(call.get("id") or f"call_{index}", function.get("name", ""),
                                  args if isinstance(args, dict) else {}))
        return Turn(self.llm._content(data), calls)


# ------------------------------------------------------------------ mock


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"\w+", text.lower()) if len(w) > 3 or w.isdigit()}


def _overlap(claim: str, passage: str) -> float:
    claim_words, passage_words = _words(claim), _words(passage)
    if not claim_words:
        return 0.0
    score = len(claim_words & passage_words) / len(claim_words)
    if any(word.isdigit() and word not in passage_words for word in claim_words):
        score = min(score, 0.3)  # un numero che nel passaggio non c'è non è supportato
    return score


class MockLLM(LLM):
    """Nessuna chiamata di rete. I "riassunti" sono le prime righe del contenuto, il giudizio
    è una sovrapposizione di parole: basta per esercitare tutto il resto del sistema."""

    def __init__(self, cfg: LLMConfig) -> None:
        super().__init__(cfg)
        self.delay = 0.0

    async def complete(self, *, model, system, prompt, effort="", kind="") -> str:
        self._count(kind)
        if self.delay:
            await asyncio.sleep(self.delay)
        body = [re.sub(r"^\d+\|\s?", "", line) for line in prompt.splitlines() if line.strip()]
        title = next((line.lstrip("# ").strip() for line in body if line.strip("# ").strip()), "")
        return f"# {title[:80]}\n\n" + "\n".join(body[:12])

    async def complete_json(self, *, model, system, prompt, schema, effort="", kind="") -> dict:
        self._count(kind)
        claim, _, passage = prompt.partition("PASSAGGIO:")
        passage = re.sub(r"^\(righe citate: [^)]*\)$|^\d+\||^Documento: .*$", "", passage, flags=re.M)
        score = _overlap(claim.replace("AFFERMAZIONE:", ""), passage)
        if kind == "recheck":
            return {"supported": score >= 0.6, "reason": f"sovrapposizione {score:.2f}",
                    "start_line": 0, "end_line": 0}
        return {"supported": score >= 0.6, "confidence": score}

    def conversation(self, *, model, system, tools, user, effort="") -> Conversation:
        return _MockConversation(self, user)


class _MockConversation(Conversation):
    """Cerca la domanda, poi risponde citando i primi risultati."""

    def __init__(self, llm: MockLLM, user: str) -> None:
        self.llm, self.user, self.step = llm, user, 0

    async def next(self, results=None, user_text=None) -> Turn:
        self.llm._count("agent")
        self.step += 1
        if self.step == 1:
            return Turn("", [ToolCall("mock-1", "search", {"query": self.user, "limit": 5})])
        hits: list[dict] = []
        if results:
            try:
                hits = json.loads(results[0].content).get("results", [])
            except (json.JSONDecodeError, AttributeError):
                hits = []
        hits = [hit for hit in hits if hit.get("kind") == "text"][:2]
        if not hits:
            return Turn("", [ToolCall("mock-2", "answer", {
                "answer": "Nei documenti indicizzati non ho trovato nulla su questo.",
                "citations": [],
            })])
        parts, citations = [], []
        for number, hit in enumerate(hits, 1):
            claim = hit["snippet"].replace("«", "").replace("»", "").replace(" … ", " ").strip()
            parts.append(f"{claim} [{number}]")
            citations.append({"id": number, "doc": hit["doc"], "start_line": hit["start_line"],
                              "end_line": hit["end_line"], "claim": claim})
        return Turn("", [ToolCall("mock-2", "answer", {
            "answer": "\n\n".join(parts), "citations": citations,
        })])


def make_llm(cfg: LLMConfig) -> LLM:
    provider = cfg.provider.lower()
    if provider == "anthropic":
        return AnthropicLLM(cfg)
    if provider == "openai":
        return OpenAICompatLLM(cfg)
    if provider == "mock":
        return MockLLM(cfg)
    raise ValueError(f"llm.provider sconosciuto: {cfg.provider!r}")
