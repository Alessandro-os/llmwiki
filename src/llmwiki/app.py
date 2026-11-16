"""Mette insieme i pezzi.

Wiki: uno spazio aperto (archivio, modelli, indicizzatore, agente).
Hub:  ciò che il server tiene acceso; permette di cambiare spazio o impostazioni senza
      riavviare l'applicazione.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
from pathlib import Path

from . import apphome, nli, ocr, ocr_local
from .agent import Answer, WikiAgent
from .config import Config
from .indexer import Indexer
from .llm import LLM, make_llm
from .store import Store
from .tools import WikiTools
from .verify import Citation

# Fornitori proposti nelle Impostazioni. Tutti tranne Claude parlano il protocollo di OpenAI,
# quindi aggiungerne uno significa aggiungere una riga: `key` è il nome con cui si salva la chiave.
PROVIDERS = (
    {"id": "locale", "name": "Un modello sul mio computer", "provider": "openai", "base_url": "", "key": ""},
    {"id": "anthropic", "name": "Claude (Anthropic)", "provider": "anthropic", "base_url": "",
     "key": "ANTHROPIC_API_KEY"},
    {"id": "openai", "name": "OpenAI", "provider": "openai", "base_url": "https://api.openai.com/v1",
     "key": "OPENAI_API_KEY"},
    {"id": "gemini", "name": "Google Gemini", "provider": "openai",
     "base_url": "https://generativelanguage.googleapis.com/v1beta/openai", "key": "GEMINI_API_KEY"},
    {"id": "openrouter", "name": "OpenRouter (molti modelli, una chiave)", "provider": "openai",
     "base_url": "https://openrouter.ai/api/v1", "key": "OPENROUTER_API_KEY"},
    {"id": "mistral", "name": "Mistral", "provider": "openai", "base_url": "https://api.mistral.ai/v1",
     "key": "MISTRAL_API_KEY"},
    {"id": "groq", "name": "Groq", "provider": "openai", "base_url": "https://api.groq.com/openai/v1",
     "key": "GROQ_API_KEY"},
    {"id": "altro", "name": "Un altro servizio compatibile OpenAI", "provider": "openai", "base_url": "",
     "key": "LLM_API_KEY"},
)
KEY_NAME = re.compile(r"[A-Z][A-Z0-9_]*_API_KEY")


class Wiki:
    def __init__(self, cfg: Config, llm: LLM | None = None, judge: nli.NliJudge | None = None) -> None:
        self.cfg = cfg
        self.store = Store(cfg.docs_dir, cfg.wiki_dir)
        self.llm = llm or make_llm(cfg.llm)
        self.tools = WikiTools(self.store)
        self.indexer = Indexer(cfg, self.store, self.llm)
        if cfg.verify.judge == "llm":
            judge = None
        elif judge is None and nli.installed():
            judge = nli.NliJudge()
        self.agent = WikiAgent(cfg, self.tools, self.llm, judge)

    async def ask(self, question: str, folder: str = "", *, history: list[dict] | None = None,
                  on_event=None, user: str = "") -> Answer:
        answer = await self.agent.ask(question, folder, history=history, on_event=on_event)
        if user:  # la cronologia è personale: ognuno rivede solo le proprie domande
            self.store.add_history(user, question, answer.to_dict())
        return answer

    async def verify(self, doc: str, start_line: int, end_line: int, claim: str) -> Citation:
        citation = Citation(id=1, doc=doc, start_line=start_line, end_line=end_line, claim=claim)
        return await self.agent.verifier.check(citation)

    async def aclose(self) -> None:
        await self.llm.aclose()
        if self.indexer.ocr:
            self.indexer.ocr.close()
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
    for name, value in stored.items():
        if KEY_NAME.fullmatch(name) and value and not os.environ.get(name):
            os.environ[name] = value


def save_secret(name: str, value: str) -> None:
    if not KEY_NAME.fullmatch(name):
        raise ValueError(f"nome di chiave non valido: {name!r}")
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


def add_user(cfg: Config, name: str) -> str:
    """Crea un utente e restituisce il suo token personale (salvato in wiki.toml)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
        raise ValueError("nome utente: lettere, cifre, _ e - (massimo 40)")
    if name in cfg.server.users:
        raise ValueError(f"l'utente {name!r} esiste già")
    token = secrets.token_urlsafe(24)
    cfg.server.users[name] = token
    cfg.save()
    return token


# Server locali che l'app sa riconoscere da sola (tutti con API compatibile OpenAI): servono
# sia i modelli sia gli OCR che leggono immagini (Unlimited OCR con SGLang, per esempio).
LOCAL_SERVERS = (("Strata / llama.cpp", 8080), ("llama.cpp", 8090), ("Ollama", 11434),
                 ("LM Studio", 1234), ("vLLM", 8000), ("SGLang", 30000), ("SGLang", 10000))
OCR_MODELS_PER_SERVER = 6  # un server con molti modelli li carica uno alla volta per provarli


async def detect_local_servers() -> list[dict]:
    """Modelli accesi su questo computer: [{name, base_url, models}]."""
    import httpx

    async def probe(name: str, port: int) -> dict | None:
        base = f"http://127.0.0.1:{port}/v1"
        try:
            async with httpx.AsyncClient(timeout=1.5) as http:
                data = (await http.get(base + "/models")).json()
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        except Exception:  # porta chiusa, o un servizio che non è un server di modelli
            return None
        return {"name": name, "base_url": base, "models": models} if models else None

    found = await asyncio.gather(*(probe(name, port) for name, port in LOCAL_SERVERS))
    return [server for server in found if server]


async def detect_ocr(extra_folders: str = "") -> list[dict]:
    """Gli OCR sul computer: i modelli GGUF che vedono le immagini (l'app li accende da sola con
    llama-server), i modelli accesi sui server locali che leggono davvero l'immagine di prova,
    e Tesseract. Chi non funziona resta nell'elenco con il motivo."""

    def try_model(server: dict, model: str) -> dict:
        entry = ocr_local.known(model)
        engine = ocr.ServerOcr(server["base_url"], model, timeout=60, prompt=entry["prompt"])
        try:
            result = ocr.probe(engine)
        finally:
            engine.close()
        return {"kind": "server", "name": f"{model} su {server['name']}", "base_url": server["base_url"],
                "model": model, "prompt": entry["prompt"] if entry["id"] else "", "strips": entry["strips"],
                "recommended": entry["recommended"] and result["ok"], "good_for": entry["good_for"],
                "known": bool(entry["id"]),
                "ok": result["ok"], "seconds": result["seconds"], "note": "", "error": result["error"]}

    async def try_server(server: dict) -> list[dict]:
        found = []
        for model in server["models"][:OCR_MODELS_PER_SERVER]:  # uno alla volta per server
            found.append(await asyncio.to_thread(try_model, server, model))
        return found

    servers = await detect_local_servers()
    groups = await asyncio.gather(*(try_server(s) for s in servers), asyncio.to_thread(ocr.find_tesseract),
                                  asyncio.to_thread(find_local_ocr, extra_folders))
    found = [item for group in groups for item in group]
    return sorted(found, key=lambda item: (not item["ok"], not item.get("recommended"), not item.get("known")))


def find_local_ocr(extra_folders: str = "") -> list[dict]:
    """I modelli OCR GGUF nelle cartelle consuete e in quelle aggiunte, ciascuno con il
    llama-server che lo farà girare. Non si accendono qui: costerebbe secondi e memoria per
    ognuno; "Salva e prova" prova quello scelto."""
    folders = ocr_local.default_folders() + [Path(f.strip()) for f in extra_folders.split(";") if f.strip()]
    servers = ocr_local.find_llama_servers(folders)
    found = []
    for item in ocr_local.find_models(folders):
        item.update(llama_server=servers[0] if servers else "", ok=bool(servers), seconds=0,
                    note=f"{item['size_gb']} GB · l'app lo accende quando serve e lo spegne dopo 3 minuti",
                    error="" if servers else "manca llama-server (il programma di llama.cpp che lo fa girare)")
        found.append(item)
    return found


def use_local_server(cfg: Config, server: dict) -> None:
    """Collega la configurazione a un server trovato da `detect_local_servers`."""
    model = server["models"][0]
    cfg.llm.provider, cfg.llm.base_url = "openai", server["base_url"]
    cfg.llm.agent_model = cfg.llm.summary_model = cfg.llm.judge_model = model
    cfg.index.concurrency = 2  # i server locali di solito elaborano una richiesta alla volta


class Hub:
    def __init__(self, wiki: Wiki, registry: apphome.Registry | None = None) -> None:
        self.wiki = wiki
        self.registry = registry  # presente solo nell'app desktop, che gestisce più spazi
        self.download = nli.Download()
        self._judge: nli.NliJudge | None = wiki.agent.verifier.nli
        self._lock = asyncio.Lock()
        self._running = False
        self.quit = None  # impostata dall'app desktop: chiude l'applicazione
        self.updater = None  # solo nell'app desktop: aggiornamenti da GitHub (update.Updater)

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
