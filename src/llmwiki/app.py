"""Mette insieme i pezzi.

Wiki: uno spazio aperto (archivio, modelli, indicizzatore, agente).
Hub:  ciò che il server tiene acceso; permette di cambiare spazio o impostazioni senza
      riavviare l'applicazione.
"""

from __future__ import annotations

import asyncio
import json
import os

from . import apphome, nli
from .agent import Answer, WikiAgent
from .config import Config
from .indexer import Indexer
from .llm import LLM, make_llm
from .store import Store
from .tools import WikiTools
from .verify import Citation

SECRET_NAMES = ("ANTHROPIC_API_KEY", "OPENAI_API_KEY")


class Wiki:
    def __init__(self, cfg: Config, llm: LLM | None = None, judge: nli.NliJudge | None = None) -> None:
        self.cfg = cfg
        self.store = Store(cfg.docs_dir, cfg.wiki_dir)
        self.llm = llm or make_llm(cfg.llm)
        self.tools = WikiTools(self.store)
        self.indexer = Indexer(cfg, self.store, self.llm)
        if judge is None and cfg.verify.judge != "llm" and nli.installed():
            judge = nli.NliJudge()
        self.agent = WikiAgent(cfg, self.tools, self.llm, judge if cfg.verify.judge != "llm" else None)

    async def ask(self, question: str, folder: str = "") -> Answer:
        return await self.agent.ask(question, folder)

    async def verify(self, doc: str, start_line: int, end_line: int, claim: str) -> Citation:
        citation = Citation(id=1, doc=doc, start_line=start_line, end_line=end_line, claim=claim)
        return await self.agent.verifier.check(citation)

    async def aclose(self) -> None:
        await self.llm.aclose()
        self.store.close()


def load_secrets() -> None:
    """Le chiavi API inserite dall'app stanno in un file dell'utente, fuori dagli spazi (che
    possono finire in cartelle condivise). Una variabile d'ambiente già impostata vince."""
    path = apphome.home() / "secrets.json"
    if not path.exists():
        return
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    for name in SECRET_NAMES:
        if stored.get(name) and not os.environ.get(name):
            os.environ[name] = stored[name]


def save_secret(name: str, value: str) -> None:
    if name not in SECRET_NAMES:
        raise ValueError(f"chiave non prevista: {name!r}")
    path = apphome.home() / "secrets.json"
    stored = {}
    if path.exists():
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            stored = {}
    if value:
        stored[name] = value
        os.environ[name] = value
    else:
        stored.pop(name, None)
        os.environ.pop(name, None)
    path.write_text(json.dumps(stored), encoding="utf-8")


class Hub:
    def __init__(self, wiki: Wiki, registry: apphome.Registry | None = None) -> None:
        self.wiki = wiki
        self.registry = registry  # presente solo nell'app desktop, che gestisce più spazi
        self.download = nli.Download()
        self._judge: nli.NliJudge | None = wiki.agent.verifier.nli
        self._lock = asyncio.Lock()
        self._running = False
        self.quit = None  # impostata dall'app desktop: chiude l'applicazione

    async def start(self) -> None:
        self._running = True
        await self.wiki.indexer.start()

    async def stop(self) -> None:
        self._running = False
        await self.wiki.indexer.stop()
        await self.wiki.aclose()

    def judge(self) -> nli.NliJudge | None:
        """Il decision model resta caricato una volta sola, anche cambiando spazio."""
        if self._judge is None and nli.installed():
            self._judge = nli.NliJudge()
        return self._judge

    def refresh_judge(self) -> None:
        """Appena il modello finisce di scaricarsi entra in uso, senza riavvii."""
        verifier = self.wiki.agent.verifier
        if verifier.nli is None and self.wiki.cfg.verify.judge != "llm" and nli.installed():
            verifier.nli = self.judge()

    async def replace(self, cfg: Config) -> None:
        """Riapre lo spazio con una nuova configurazione (o apre un altro spazio)."""
        async with self._lock:
            old = self.wiki
            await old.indexer.stop()
            await old.aclose()
            try:
                self.wiki = Wiki(cfg, judge=self.judge())
            except Exception:
                self.wiki = Wiki(old.cfg, judge=self.judge())  # configurazione non valida: resta la vecchia
                raise
            finally:
                if self._running:
                    await self.wiki.indexer.start()

    async def switch_space(self, space_id: str) -> dict:
        if self.registry is None:
            raise ValueError("gli spazi sono disponibili solo nell'app desktop")
        space = self.registry.get(space_id)
        if space is None:
            raise ValueError(f"spazio inesistente: {space_id!r}")
        await self.replace(Config.load(os.path.join(space["path"], "wiki.toml")))
        self.registry.set_active(space_id)
        return space
