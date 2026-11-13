"""Accesso ai modelli. L'applicazione non dipende da un fornitore: tutto il resto del codice usa
solo l'interfaccia `LLM`, e ogni capacità opzionale ha un ripiego.

- AnthropicLLM: Claude tramite l'SDK ufficiale.
- OpenAICompatLLM: qualunque endpoint /chat/completions (OpenAI, Gemini, OpenRouter, Mistral,
  Groq, Ollama, LM Studio, llama.cpp, vLLM, Strata...).
- MockLLM: nessun modello, risposte deterministiche; per la demo e per i test.

Ripieghi, dal più capace al più semplice:
- strumenti: chiamate native -> protocollo testuale in JSON (`TextToolConversation`);
- uscita strutturata: schema imposto dal server -> schema nel prompt;
- giudizio sì/no: probabilità del token (logprob) -> punteggio dichiarato dal modello;
- parametri facoltativi rifiutati (effort, fallback, cache): si tolgono e si riprova.
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
    """Errore del modello. `status` è il codice HTTP quando il server ha risposto."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status

    @property
    def rejected(self) -> bool:
        """Il server ha rifiutato *questa* richiesta (parametro non supportato, chiave errata,
        testo troppo lungo). Falso se il server è spento, sovraccarico o limita le richieste:
        in quei casi riprovare più tardi ha senso."""
        return self.status is not None and 400 <= self.status < 500 and self.status not in (408, 409, 429)

    @property
    def unavailable(self) -> bool:
        """Il modello non c'è in questo momento (spento, irraggiungibile, sovraccarico, limite
        di richieste): il lavoro va rimandato, non dato per fallito. Stato 0 = nessuna risposta."""
        return self.status is not None and not self.rejected


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
PROBE_TOOL = {
    "name": "somma", "description": "Somma due numeri interi.",
    "parameters": {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}},
                   "required": ["a", "b"]},
}
OMITTED = "[risultato già letto, omesso per fare spazio]"


def strip_thinking(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def parse_json(text: str) -> dict:
    text = strip_thinking(text)
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


class Conversation:
    async def next(self, results: list[ToolResult] | None = None,
                   user_text: str | None = None) -> Turn:
        raise NotImplementedError


class LLM:
    """Interfaccia comune. `kind` è solo un'etichetta (conteggi, mock), non cambia la richiesta."""

    def __init__(self, cfg: LLMConfig) -> None:
        self.cfg = cfg
        self.calls: dict[str, int] = {}
        self.native_tools = True  # falso dopo che il server ha rifiutato le chiamate a strumenti

    def _count(self, kind: str) -> None:
        self.calls[kind] = self.calls.get(kind, 0) + 1

    async def complete(self, *, model: str, system: str, prompt: str, effort: str = "",
                       kind: str = "") -> str:
        raise NotImplementedError

    async def complete_json(self, *, model: str, system: str, prompt: str, schema: dict,
                            effort: str = "", kind: str = "") -> dict:
        """Ripiego universale: lo schema va nel prompt e la risposta si legge con tolleranza.
        Un secondo tentativo copre il modello che la prima volta aggiunge testo attorno."""
        system = (f"{system}\n\nRispondi solo con un oggetto JSON conforme a questo schema, "
                  f"senza altro testo:\n{json.dumps(schema, ensure_ascii=False)}")
        for attempt in (1, 2):
            text = await self.complete(model=model, system=system, prompt=prompt, effort=effort, kind=kind)
            try:
                return parse_json(text)
            except LLMError:
                if attempt == 2:
                    raise
        raise AssertionError("irraggiungibile")

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
            confidence = 1.0 - confidence  # il modello ha dato la confidenza nel proprio "no"
        return confidence, "llm-json"

    def conversation(self, *, model: str, system: str, tools: list[dict], user: str,
                     effort: str = "") -> Conversation:
        """Conversazione con strumenti. `llm.tool_mode`: "native", "text", oppure "auto" (prova
        le chiamate native e passa da sola al protocollo testuale se il modello non le usa)."""
        def text() -> Conversation:
            return TextToolConversation(self, model, system, tools, user, effort)

        mode = self.cfg.tool_mode
        if mode == "text" or (mode == "auto" and not self.native_tools):
            return text()
        native = self._native_conversation(model=model, system=system, tools=tools, user=user, effort=effort)
        return native if mode == "native" else _AdaptiveConversation(self, native, text)

    def _native_conversation(self, *, model, system, tools, user, effort) -> Conversation:
        raise NotImplementedError

    async def list_models(self) -> list[dict]:
        """Modelli offerti dal fornitore: [{id, context}] (context = finestra in token, 0 se ignota)."""
        return []

    async def probe(self, model: str) -> dict:
        """Che cosa sa fare questo modello, per dirlo all'utente in chiaro."""
        out = {"ok": False, "reply": "", "tools": "", "logprobs": False, "error": ""}
        try:
            reply = await self.complete(model=model, system="Rispondi con una sola parola.",
                                        prompt="Scrivi: pronto", kind="test")
        except LLMError as exc:
            out["error"] = str(exc)
            return out
        out.update(ok=True, reply=reply[:60])
        request = {"model": model, "system": "Usa lo strumento somma.", "tools": [PROBE_TOOL],
                   "user": "Quanto fa 2 più 3? Usa lo strumento.", "effort": ""}
        for mode, build in (("native", lambda: self._native_conversation(**request)),
                            ("text", lambda: TextToolConversation(self, *request.values()))):
            try:
                turn = await build().next()
            except (LLMError, NotImplementedError):
                continue
            if any(call.name == "somma" for call in turn.tool_calls):
                out["tools"] = mode
                break
        try:
            out["logprobs"] = (await self.judge(model=model, claim="Il cielo è blu.",
                                                passage="Il cielo è blu."))[1] == "logprobs"
        except LLMError:
            pass
        return out

    async def aclose(self) -> None:
        pass


class TextToolConversation(Conversation):
    """Strumenti per qualunque modello capace di scrivere testo: sono descritti nel prompt e il
    modello risponde con un oggetto JSON che elenca le chiamate da fare."""

    def __init__(self, llm: LLM, model: str, system: str, tools: list[dict], user: str, effort: str) -> None:
        self.llm, self.model, self.effort = llm, model, effort
        described = "\n".join(
            f"- {t['name']}: {t['description']}\n  argomenti: {json.dumps(t['parameters'], ensure_ascii=False)}"
            for t in tools)
        self.system = f"{system}\n\n{prompts.TOOL_PROTOCOL.format(tools=described)}"
        self.transcript: list[list[str]] = [["utente", user]]
        self._names: dict[str, str] = {}
        self._count = 0

    async def next(self, results=None, user_text=None) -> Turn:
        if results:
            body = "\n\n".join(f"Risultato di {self._names.get(r.id, r.id)}"
                               f"{' (errore)' if r.is_error else ''}:\n{r.content}" for r in results)
            self.transcript.append(["risultati", body])
        if user_text:
            self.transcript.append(["utente", user_text])
        self._trim()
        prompt = "\n\n".join(f"[{role}]\n{content}" for role, content in self.transcript) + "\n\n[assistente]"
        text = strip_thinking(await self.llm.complete(
            model=self.model, system=self.system, prompt=prompt, effort=self.effort, kind="agent"))
        self.transcript.append(["assistente", text])
        calls = []
        try:
            data = parse_json(text)
        except LLMError:
            data = {}
        for item in data.get("calls") or ([data] if data.get("tool") else []):
            if isinstance(item, dict) and item.get("tool"):
                self._count += 1
                call = ToolCall(f"t{self._count}", str(item["tool"]),
                                item.get("args") if isinstance(item.get("args"), dict) else {})
                self._names[call.id] = call.name
                calls.append(call)
        if not calls:  # testo libero: al prossimo turno si ricorda il formato
            self.transcript.append(["utente", "Rispondi solo con l'oggetto JSON delle chiamate."])
        return Turn("" if calls else text, calls)

    def _trim(self) -> None:
        budget = self.llm.cfg.context_tokens * 3  # circa 3 caratteri per token, con margine
        if not budget:
            return
        old = [entry for entry in self.transcript[:-2] if entry[0] == "risultati"]
        for entry in old:
            if sum(len(content) for _, content in self.transcript) <= budget:
                break
            entry[1] = OMITTED


class _AdaptiveConversation(Conversation):
    """Parte con le chiamate native e, se al primo turno il server le rifiuta o il modello non
    ne fa, ricomincia con il protocollo testuale."""

    def __init__(self, llm: LLM, native: Conversation, text) -> None:
        self.llm, self.current, self.text, self.settled = llm, native, text, False

    async def next(self, results=None, user_text=None) -> Turn:
        if self.settled:
            return await self.current.next(results, user_text)
        self.settled = True
        try:
            turn = await self.current.next(results, user_text)
        except LLMError as exc:
            if not exc.rejected:
                raise
            self.llm.native_tools = False  # questo server non le accetta: non riprovo più
            turn = Turn("")
        if not turn.tool_calls:
            self.current = self.text()
            turn = await self.current.next()
        return turn


# ------------------------------------------------------------------ Anthropic

# Modelli su cui un rifiuto dei classificatori può essere rilanciato lato server.
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Parametri facoltativi: se un modello li rifiuta si tolgono e si riprova. (nome, indizio nell'errore)
_OPTIONAL = (("fallbacks", "fallback"), ("effort", "effort"), ("cache", "cache_control"))


class AnthropicLLM(LLM):
    def __init__(self, cfg: LLMConfig) -> None:
        super().__init__(cfg)
        import anthropic

        self._anthropic = anthropic
        # Credenziali risolte dall'SDK: ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN o `ant auth login`.
        self.client = anthropic.AsyncAnthropic(max_retries=4, timeout=cfg.timeout)
        self._unsupported: dict[str, set[str]] = {}

    def _error(self, exc) -> LLMError:
        anthropic = self._anthropic
        if isinstance(exc, anthropic.AuthenticationError):
            return LLMError("chiave Anthropic mancante o non valida", exc.status_code)
        if isinstance(exc, anthropic.RateLimitError):
            return LLMError("limite di richieste Anthropic raggiunto", exc.status_code)
        if isinstance(exc, anthropic.APIStatusError):
            return LLMError(f"errore API Anthropic {exc.status_code}: {exc.message}", exc.status_code)
        return LLMError(f"connessione ad Anthropic non riuscita: {exc}", 0)

    async def _create(self, *, model: str, kind: str, **kwargs):
        anthropic = self._anthropic
        self._count(kind)
        off = self._unsupported.setdefault(model, set())
        while True:
            request = dict(kwargs)
            config = dict(request.pop("output_config", None) or {})
            if "effort" in off:
                config.pop("effort", None)
            if config:
                request["output_config"] = config
            if "cache" in off:
                request.pop("cache_control", None)
            fallbacks = (self.cfg.refusal_fallbacks and model.startswith(_FALLBACK_MODELS)
                         and "fallbacks" not in off)
            try:
                if fallbacks:
                    response = await self.client.beta.messages.create(
                        model=model, betas=[_FALLBACK_BETA], fallbacks="default", **request)
                else:
                    response = await self.client.messages.create(model=model, **request)
                break
            except anthropic.BadRequestError as exc:
                used = {"fallbacks": fallbacks, "effort": "effort" in config, "cache": "cache_control" in request}
                dropped = next((name for name, hint in _OPTIONAL
                                if used[name] and hint in str(exc.message).lower()), None)
                if dropped is None:
                    raise self._error(exc) from exc
                off.add(dropped)  # questo modello non lo accetta: si riprova senza
            except anthropic.APIError as exc:
                raise self._error(exc) from exc
        if response.stop_reason == "refusal":
            raise LLMError("il modello ha rifiutato la richiesta (stop_reason: refusal)")
        return response

    @staticmethod
    def _text(response) -> str:
        return "".join(block.text for block in response.content if block.type == "text").strip()

    async def complete(self, *, model, system, prompt, effort="", kind="") -> str:
        response = await self._create(
            model=model, kind=kind, max_tokens=16000, system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort} if effort else None,
        )
        if response.stop_reason == "max_tokens":
            raise LLMError("risposta troncata (max_tokens)")
        return self._text(response)

    async def complete_json(self, *, model, system, prompt, schema, effort="", kind="") -> dict:
        output_config: dict = {"format": {"type": "json_schema", "schema": schema}}
        if effort:
            output_config["effort"] = effort
        try:
            response = await self._create(
                model=model, kind=kind, max_tokens=16000, system=system,
                messages=[{"role": "user", "content": prompt}], output_config=output_config,
            )
        except LLMError as exc:
            if not exc.rejected:
                raise
            return await super().complete_json(model=model, system=system, prompt=prompt,
                                               schema=schema, effort=effort, kind=kind)
        return parse_json(self._text(response))

    def _native_conversation(self, *, model, system, tools, user, effort) -> Conversation:
        return _AnthropicConversation(self, model, system, tools, user, effort)

    async def list_models(self) -> list[dict]:
        try:
            return [{"id": m.id, "context": getattr(m, "max_input_tokens", 0) or 0}
                    async for m in self.client.models.list()]
        except self._anthropic.APIError as exc:
            raise self._error(exc) from exc


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

        response = await self.llm._create(
            model=self.model, kind="agent", max_tokens=16000, system=self.system,
            tools=self.tools, messages=self.messages,
            cache_control={"type": "ephemeral"},  # il prefisso della conversazione si riusa a ogni passo
            output_config={"effort": self.effort} if self.effort else None,
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

# Dove i vari server dichiarano la finestra di contesto di un modello nell'elenco /models.
_CONTEXT_FIELDS = ("context_length", "context_window", "max_model_len", "max_context_length")


class OpenAICompatLLM(LLM):
    def __init__(self, cfg: LLMConfig) -> None:
        super().__init__(cfg)
        import httpx

        self._httpx = httpx
        key = os.environ.get(cfg.api_key_env or "", "")
        self.http = httpx.AsyncClient(
            base_url=cfg.base_url.rstrip("/"), timeout=cfg.timeout,
            headers={"Authorization": f"Bearer {key}"} if key else {},
        )
        self._logprobs_ok = True
        self._judge_mode = 0

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _chat(self, body: dict, kind: str) -> dict:
        self._count(kind)
        last: LLMError | None = None
        for attempt in range(4):
            try:
                response = await self.http.post("/chat/completions", json=body)
            except self._httpx.HTTPError as exc:
                last = LLMError(f"il modello su {self.cfg.base_url} non risponde: {exc!r}", 0)
            else:
                if response.status_code == 200:
                    return response.json()
                last = LLMError(f"errore {response.status_code} dal modello: {response.text[:300]}",
                                response.status_code)
                if last.rejected:
                    raise last
            await asyncio.sleep(min(2 ** attempt, 20))
        raise last  # type: ignore[misc]

    @staticmethod
    def _content(data: dict) -> str:
        return strip_thinking(data["choices"][0]["message"].get("content") or "")

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
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "output", "schema": schema, "strict": True},
            },
            **self._effort(effort),
        }
        try:
            return parse_json(self._content(await self._chat(body, kind)))
        except LLMError as exc:
            if exc.unavailable:
                raise  # server spento o in errore: ripetere la richiesta non serve
            # il server non conosce response_format, o il modello non l'ha rispettato
            return await super().complete_json(model=model, system=system, prompt=prompt,
                                               schema=schema, effort=effort, kind=kind)

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
                if exc.unavailable:
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

    def _native_conversation(self, *, model, system, tools, user, effort) -> Conversation:
        return _OpenAIConversation(self, model, system, tools, user, self._effort(effort))

    async def list_models(self) -> list[dict]:
        try:
            response = await self.http.get("/models")
        except self._httpx.HTTPError as exc:
            raise LLMError(f"il server {self.cfg.base_url} non risponde: {exc!r}") from exc
        if response.status_code != 200:
            raise LLMError(f"errore {response.status_code}: {response.text[:200]}", response.status_code)
        models = []
        for item in response.json().get("data", []):
            if isinstance(item, dict) and item.get("id"):
                meta = item.get("meta") if isinstance(item.get("meta"), dict) else {}
                context = meta.get("n_ctx") or next((item[f] for f in _CONTEXT_FIELDS if item.get(f)), 0)
                models.append({"id": item["id"], "context": int(context or 0)})
        return models


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
        self._trim()
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

    def _trim(self) -> None:
        """Con una finestra di contesto piccola, i risultati più vecchi lasciano il posto."""
        budget = self.llm.cfg.context_tokens * 3
        if not budget:
            return
        for message in self.messages[:-2]:
            if sum(len(str(m.get("content") or "")) for m in self.messages) <= budget:
                break
            if message.get("role") == "tool":
                message["content"] = OMITTED


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

    def _native_conversation(self, *, model, system, tools, user, effort) -> Conversation:
        return _MockConversation(self, user)

    async def list_models(self) -> list[dict]:
        return [{"id": "demo", "context": 0}]


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
    backends = {"anthropic": AnthropicLLM, "openai": OpenAICompatLLM, "mock": MockLLM}
    if cfg.provider not in backends:
        raise ValueError(f"llm.provider sconosciuto: {cfg.provider!r}")
    return backends[cfg.provider](cfg)
