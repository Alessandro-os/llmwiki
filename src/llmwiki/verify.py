"""Fact-checking delle citazioni.

Per ogni citazione si confrontano due testi: l'affermazione scritta dall'agente e le righe del
documento indicate come fonte.

  1. Giudici veloci, uno dopo l'altro finché uno conferma: il decision model NLI (se
     installato), poi un sì/no del modello linguistico. Sopra soglia la citazione è confermata.
  2. Sotto soglia, ricontrollo: il modello rilegge il passaggio con un po' di contesto attorno
     e, se trova il fatto poco più in là, corregge le righe citate.
  3. Se fallisce anche quello, la citazione resta ma con un avviso (il triangolino).
"""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass

from . import prompts
from .config import Config
from .extract import numbered
from .llm import LLM, LLMError
from .tools import ToolError, WikiTools

VERIFIED = "verified"    # confermata da un giudice veloce
RECHECKED = "rechecked"  # confermata al ricontrollo
WARNING = "warning"      # non confermata: mostrare l'avviso

RECHECK_SCHEMA = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "reason": {"type": "string"},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
    },
    "required": ["supported", "reason", "start_line", "end_line"],
    "additionalProperties": False,
}


@dataclass
class Citation:
    id: int
    doc: str
    start_line: int
    end_line: int
    claim: str
    status: str = "unverified"
    confidence: float | None = None
    method: str = ""
    note: str = ""
    passage: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class Verifier:
    def __init__(self, cfg: Config, tools: WikiTools, llm: LLM, nli=None) -> None:
        self.cfg, self.tools, self.llm = cfg, tools, llm
        self.nli = nli  # NliJudge, se il decision model dedicato è installato
        self._slots = asyncio.Semaphore(8)

    @property
    def judge_name(self) -> str:
        return "nli" if self.nli is not None else "llm"

    async def check_all(self, citations: list[Citation]) -> list[Citation]:
        return list(await asyncio.gather(*(self.check(c) for c in citations)))

    async def check(self, c: Citation) -> Citation:
        async with self._slots:
            if not c.claim.strip():
                return _warn(c, "citazione senza affermazione da verificare")
            try:
                path, start, end, lines = self.tools.passage(c.doc, c.start_line, c.end_line)
            except (ToolError, ValueError, TypeError) as exc:
                return _warn(c, f"fonte non trovata: {exc}")
            end = min(end, start + self.cfg.verify.max_passage_lines - 1)
            c.doc, c.start_line, c.end_line = path, start, end
            c.passage = "\n".join(lines[start - 1 : end])
            # I giudici sanno anche di che documento si tratta: l'agente scrive "la policy
            # smart working prevede...", e quel contesto nelle sole righe citate spesso manca.
            row = self.tools.store.get_doc(path)
            title = (row["title"] if row else "") or path

            judges = [self._nli] if self.nli is not None else []
            if self.nli is None or self.cfg.verify.judge != "nli":
                judges.append(self._llm_judge)
            for judge in judges:
                await judge(c, title, len(lines))
                if c.confidence is not None and c.confidence >= self.cfg.verify.threshold:
                    c.status = VERIFIED
                    return c
            return await self._recheck(c, lines)

    async def _nli(self, c: Citation, title: str, _total: int) -> None:
        """Decine di millisecondi sulla CPU. Non accetta citazioni sbagliate, ma ne respinge
        alcune giuste se lunghe o riformulate: per questo dopo c'è un secondo giudice."""
        try:
            c.confidence = await asyncio.to_thread(self.nli.score, c.claim, c.passage, f"Documento: {title}.")
            c.method = "nli"
        except Exception as exc:  # modello illeggibile o corrotto: decide il giudice successivo
            c.note = f"decision model non disponibile ({exc!r})"

    async def _llm_judge(self, c: Citation, title: str, total: int) -> None:
        """Sì/no del modello linguistico, con i logprob se il server li espone."""
        whole = ": l'intero documento" if c.start_line == 1 and c.end_line == total else ""
        premise = f"Documento: {title} (righe {c.start_line}-{c.end_line} di {total}{whole}).\n{c.passage}"
        try:
            c.confidence, method = await self.llm.judge(
                model=self.cfg.llm.judge_model, claim=c.claim, passage=premise)
            c.method = f"{c.method}+{method}".lstrip("+")
        except LLMError as exc:
            c.note = f"giudice non disponibile ({exc})"

    async def _recheck(self, c: Citation, lines: list[str]) -> Citation:
        first = max(1, c.start_line - self.cfg.verify.context_lines)
        last = min(len(lines), c.end_line + self.cfg.verify.context_lines)
        header = f"(righe citate: {c.start_line}-{c.end_line}; il documento ha {len(lines)} righe)"
        try:
            verdict = await self.llm.complete_json(
                model=self.cfg.llm.agent_model, system=prompts.RECHECK,
                prompt=prompts.judge_prompt(c.claim, f"{header}\n{numbered(lines[first - 1 : last], first)}"),
                schema=RECHECK_SCHEMA, effort="medium", kind="recheck",
            )
        except LLMError as exc:
            return _warn(c, f"ricontrollo non riuscito: {exc}")
        reason = str(verdict.get("reason", ""))
        if verdict.get("supported") is not True:
            return _warn(c, reason or "il passaggio citato non supporta l'affermazione")
        c.status, c.method, c.note = RECHECKED, f"{c.method}+recheck".lstrip("+"), reason[:300]
        start, end = _as_int(verdict.get("start_line")), _as_int(verdict.get("end_line"))
        if first <= start <= end <= last:  # il ricontrollo ha indicato le righe giuste
            c.start_line, c.end_line = start, end
            c.passage = "\n".join(lines[start - 1 : end])
        return c


def _warn(c: Citation, note: str) -> Citation:
    c.status, c.note = WARNING, note[:300]
    return c


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
