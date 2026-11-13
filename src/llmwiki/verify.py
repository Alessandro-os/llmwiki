"""Fact-checking delle citazioni.

Per ogni citazione si confrontano due testi: l'affermazione scritta dall'agente e le righe del
documento indicate come fonte.

  1. Decision model: "il testo supporta la frase?" -> sì/no con una confidenza. Prima il
     modello NLI dedicato (se installato), poi sui casi dubbi un sì/no del modello linguistico.
     Sopra soglia la citazione è confermata.
  2. Sotto soglia, secondo tentativo: il modello rilegge il passaggio con un po' di contesto
     attorno e, se la trova, corregge le righe citate.
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

VERIFIED = "verified"    # confermata dal decision model
RECHECKED = "rechecked"  # confermata al secondo tentativo
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

    async def check(self, citation: Citation) -> Citation:
        async with self._slots:
            return await self._check(citation)

    async def _check(self, c: Citation) -> Citation:
        vcfg = self.cfg.verify
        if not c.claim.strip():
            return self._warn(c, "citazione senza affermazione da verificare")
        try:
            path, start, end, lines = self.tools.passage(c.doc, c.start_line, c.end_line)
        except (ToolError, ValueError, TypeError) as exc:
            return self._warn(c, f"fonte non trovata: {exc}")
        if end - start + 1 > vcfg.max_passage_lines:
            end = start + vcfg.max_passage_lines - 1
        c.doc, c.start_line, c.end_line = path, start, end
        c.passage = "\n".join(lines[start - 1 : end])

        # Il giudice vede anche di che documento si tratta: l'agente scrive "la policy smart
        # working prevede...", e quel contesto nelle sole righe citate spesso non c'è.
        row = self.tools.store.get_doc(path)
        title = (row["title"] if row else "") or path
        premise = f"Documento: {title}.\n{c.passage}"

        # 1a. decision model dedicato (NLI): decine di millisecondi, non accetta citazioni
        #     sbagliate ma ne respinge alcune giuste, soprattutto se lunghe o riformulate
        if self.nli is not None:
            try:
                c.confidence = await asyncio.to_thread(
                    self.nli.score, c.claim, c.passage, f"Documento: {title}.")
                c.method = "nli"
            except Exception as exc:  # modello illeggibile o corrotto: decide il passo dopo
                c.note = f"decision model non disponibile ({exc!r})"
            if c.confidence is not None and c.confidence >= vcfg.threshold:
                c.status = VERIFIED
                return c

        # 1b. sì/no del modello linguistico (con i logprob, se il server li espone)
        if self.nli is None or vcfg.judge != "nli":
            try:
                c.confidence, method = await self.llm.judge(
                    model=self.cfg.llm.judge_model, claim=c.claim, passage=premise
                )
                c.method = (c.method + "+" + method).lstrip("+")
            except LLMError as exc:
                c.note = f"giudice non disponibile ({exc})"
            if c.confidence is not None and c.confidence >= vcfg.threshold:
                c.status = VERIFIED
                return c

        # 2. sotto soglia: ricontrollo con più contesto
        first = max(1, start - vcfg.context_lines)
        last = min(len(lines), end + vcfg.context_lines)
        window = numbered(lines[first - 1 : last], first)
        try:
            verdict = await self.llm.complete_json(
                model=self.cfg.llm.agent_model, system=prompts.RECHECK,
                prompt=prompts.judge_prompt(c.claim, f"(righe citate: {start}-{end})\n{window}"),
                schema=RECHECK_SCHEMA, effort="medium", kind="recheck",
            )
        except LLMError as exc:
            return self._warn(c, f"ricontrollo non riuscito: {exc}")

        if verdict.get("supported") is True:
            c.status = RECHECKED
            c.method = (c.method + "+recheck").lstrip("+")
            new_start, new_end = _as_int(verdict.get("start_line")), _as_int(verdict.get("end_line"))
            if first <= new_start <= new_end <= last:  # il ricontrollo ha trovato le righe giuste
                c.start_line, c.end_line = new_start, new_end
                c.passage = "\n".join(lines[new_start - 1 : new_end])
            c.note = str(verdict.get("reason", ""))[:300]
            return c

        # 3. fallito due volte
        return self._warn(c, str(verdict.get("reason", "")) or "il passaggio citato non supporta l'affermazione")

    @staticmethod
    def _warn(c: Citation, note: str) -> Citation:
        c.status = WARNING
        c.note = note[:300]
        return c


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
