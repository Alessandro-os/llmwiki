"""Agente di interrogazione: naviga la wiki con gli strumenti e risponde con citazioni."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field

from . import prompts
from .config import Config
from .llm import LLM, LLMError, ToolCall, ToolResult
from .tools import ANSWER_TOOL, DELEGATE_TOOL, NAV_TOOLS, ToolError, WikiTools
from .verify import RECHECKED, VERIFIED, WARNING, Citation, Verifier

MAX_RESULT_CHARS = 60_000
MAX_HISTORY_TURNS = 3
MAX_HISTORY_CHARS = 1800
_NAV_PARAMS = {tool["name"]: set(tool["parameters"]["properties"]) for tool in NAV_TOOLS}
_INT_PARAMS = {"start_line", "end_line", "limit"}
_MARK = {VERIFIED: "✓", RECHECKED: "✓", WARNING: "⚠"}


@dataclass
class Answer:
    question: str
    answer: str
    citations: list[Citation] = field(default_factory=list)
    steps: int = 0
    trace: list[dict] = field(default_factory=list)
    complete: bool = True
    verified: bool = False
    mode: str = "agente"  # "ricerca diretta" se il modello non ha saputo guidare gli strumenti

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "question": self.question,
            "answer": self.answer,
            "citations": [c.to_dict() for c in self.citations],
            "warnings": sum(1 for c in self.citations if c.status == WARNING),
            "steps": self.steps,
            "trace": self.trace,
            "complete": self.complete,
            "verified": self.verified,
            "markdown": self.render(),
        }

    def render(self) -> str:
        """Risposta leggibile: marcatori con l'esito della verifica ed elenco delle fonti."""
        by_id = {c.id: c for c in self.citations}

        def mark(match: re.Match) -> str:
            citation = by_id.get(int(match.group(1)))
            if citation is None:
                return f"[{match.group(1)} ⚠]"
            sign = _MARK.get(citation.status, "")
            return f"[{citation.id} {sign}]" if sign else f"[{citation.id}]"

        text = re.sub(r"\[(\d+)\]", mark, self.answer)
        if not self.citations:
            return text
        rows = ["", "---", "**Fonti**"]
        for c in self.citations:
            sign = _MARK.get(c.status, "·")
            row = f"- [{c.id}] {sign} `{c.doc}` righe {c.start_line}-{c.end_line}"
            if c.confidence is not None:
                row += f" · confidenza {c.confidence:.2f}"
            if c.status == RECHECKED:
                row += " · confermata al ricontrollo"
            if c.status == WARNING:
                row += f" · **non confermata**: {c.note}"
            rows.append(row)
        return text + "\n" + "\n".join(rows)


class WikiAgent:
    def __init__(self, cfg: Config, tools: WikiTools, llm: LLM, nli=None) -> None:
        self.cfg, self.tools, self.llm = cfg, tools, llm
        self.verifier = Verifier(cfg, tools, llm, nli)
        self._explorer_slots = asyncio.Semaphore(max(1, cfg.agent.explorers))
        # Un solo risultato non deve riempire la finestra del modello: al più circa un terzo
        # (un token vale 3-4 caratteri), quando la finestra è nota.
        self._result_chars = min(MAX_RESULT_CHARS, cfg.llm.context_tokens or MAX_RESULT_CHARS)

    async def ask(self, question: str, folder: str = "", *, explorer: bool = False,
                  verify: bool | None = None, history: list[dict] | None = None,
                  on_event=None) -> Answer:
        """`history`: scambi precedenti [{question, answer}], per le domande di approfondimento.
        `on_event`: funzione chiamata a ogni passo (per mostrare l'avanzamento in diretta)."""
        emit = on_event or (lambda _event: None)
        system = prompts.AGENT + (prompts.EXPLORER_NOTE if explorer else prompts.AGENT_DELEGATE)
        tool_defs = [*NAV_TOOLS, ANSWER_TOOL] + ([] if explorer else [DELEGATE_TOOL])
        user = question if not folder else f"{question}\n\n(Cartella di partenza: `{folder}`)"
        if history:
            past = "\n\n".join(
                f"Domanda: {str(turn.get('question', ''))[:600]}\n"
                f"Risposta: {str(turn.get('answer', ''))[:MAX_HISTORY_CHARS]}"
                for turn in history[-MAX_HISTORY_TURNS:]
            )
            user = prompts.FOLLOW_UP.format(past=past, question=user)
        max_steps = self.cfg.agent.explorer_steps if explorer else self.cfg.agent.max_steps

        conversation = self.llm.conversation(
            model=self.cfg.llm.agent_model, system=system, tools=tool_defs, user=user,
            effort=self.cfg.llm.agent_effort,
        )
        result = Answer(question=question, answer="")
        turn = await conversation.next()
        nudged = last_chance = False
        while True:
            result.steps += 1
            final = next((call for call in turn.tool_calls if call.name == "answer"), None)
            if final is not None:
                result.answer = str(final.args.get("answer", "")).strip()
                result.citations = _parse_citations(final.args.get("citations"))
                break
            if last_chance or (nudged and not turn.tool_calls):
                # già sollecitato a rispondere e ancora niente `answer`: si tiene il testo che c'è
                result.answer = turn.text or "L'agente non ha prodotto una risposta."
                result.complete = False
                break
            if not turn.tool_calls:
                nudged = True
                turn = await conversation.next(
                    user_text="Consegna la risposta chiamando il tool `answer`, con le citazioni."
                )
                continue
            outputs = await asyncio.gather(
                *(self._execute(call, result, emit, explorer) for call in turn.tool_calls))
            if result.steps >= max_steps:
                last_chance = True
                turn = await conversation.next(
                    list(outputs),
                    user_text="Hai raggiunto il limite di passi: consegna ora la risposta con "
                              "`answer`, usando ciò che hai già letto.",
                )
            else:
                turn = await conversation.next(list(outputs))

        if not result.complete and not explorer:
            await self._direct_answer(question, result, emit)
        should_verify = self.cfg.verify.enabled if verify is None else verify
        if should_verify and result.citations:
            emit({"type": "verifying", "count": len(result.citations)})
            result.citations = await self.verifier.check_all(result.citations)
            result.verified = True
        return result

    async def _direct_answer(self, question: str, result: Answer, emit) -> None:
        """Ripiego per i modelli che non riescono a guidare gli strumenti: l'app cerca da sé i
        passaggi più pertinenti e chiede una risposta fondata solo su quelli. Meno fine della
        navigazione, ma funziona con qualunque modello capace di leggere e scrivere."""
        emit({"type": "step", "tool": "search", "args": {"query": question}, "explorer": False})
        hits = [hit for hit in self.tools.search(question, limit=8)["results"] if hit["kind"] == "text"][:5]
        if not hits:
            return
        passages = "\n\n".join(
            self.tools.read_document(hit["doc"], hit["start_line"], hit["end_line"]) for hit in hits)
        try:
            data = await self.llm.complete_json(
                model=self.cfg.llm.agent_model, system=prompts.GROUNDED,
                prompt=f"Domanda: {question}\n\nPassaggi:\n\n{passages}",
                schema=ANSWER_TOOL["parameters"], effort=self.cfg.llm.agent_effort, kind="agent",
            )
        except LLMError:
            return
        answer = str(data.get("answer", "")).strip()
        if answer:
            result.answer, result.citations = answer, _parse_citations(data.get("citations"))
            result.complete, result.mode = True, "ricerca diretta"

    # ---------------------------------------------------------------- esecuzione dei tool

    async def _execute(self, call: ToolCall, result: Answer, emit, explorer: bool) -> ToolResult:
        entry = {"tool": call.name, "args": call.args, "error": False}
        result.trace.append(entry)
        emit({"type": "step", "tool": call.name, "args": call.args, "explorer": explorer})
        try:
            if call.name == "delegate":
                output = await self._delegate(call.args, emit)
            elif call.name in _NAV_PARAMS:
                args = {k: v for k, v in call.args.items() if k in _NAV_PARAMS[call.name]}
                for key in _INT_PARAMS & set(args):
                    args[key] = int(args[key] or 0)
                output = await asyncio.to_thread(getattr(self.tools, call.name), **args)
            else:
                raise ToolError(f"tool sconosciuto: {call.name!r}")
        except (ToolError, TypeError, ValueError) as exc:
            entry["error"] = True
            return ToolResult(call.id, f"Errore: {exc}", is_error=True)
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        if len(text) > self._result_chars:
            text = text[: self._result_chars] + "\n[... risultato troncato: restringi la richiesta]"
        return ToolResult(call.id, text)

    async def _delegate(self, args: dict, emit=None) -> dict:
        tasks = [t for t in (args.get("tasks") or []) if isinstance(t, dict) and t.get("question")]
        if not tasks:
            raise ToolError("delegate richiede almeno un task con `question`")

        async def run(task: dict) -> dict:
            async with self._explorer_slots:
                try:
                    found = await self.ask(str(task["question"]), str(task.get("folder") or ""),
                                           explorer=True, verify=False, on_event=emit)
                except Exception as exc:  # un esploratore fallito non deve far cadere gli altri
                    return {"question": task["question"], "error": str(exc)}
            return {
                "question": task["question"],
                "findings": found.answer,
                "citations": [
                    {"id": c.id, "doc": c.doc, "start_line": c.start_line,
                     "end_line": c.end_line, "claim": c.claim}
                    for c in found.citations
                ],
            }

        return {"explorers": list(await asyncio.gather(*(run(task) for task in tasks[:8])))}


def _parse_citations(raw) -> list[Citation]:
    citations: list[Citation] = []
    for position, item in enumerate(raw if isinstance(raw, list) else [], 1):
        if not isinstance(item, dict):
            continue
        try:
            citations.append(Citation(
                id=int(item.get("id", position)),
                doc=str(item.get("doc", "")),
                start_line=int(item.get("start_line", 0) or 0),
                end_line=int(item.get("end_line", 0) or 0),
                claim=str(item.get("claim", "")),
            ))
        except (TypeError, ValueError):
            continue
    return citations
