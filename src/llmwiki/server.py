"""Server: interfaccia web, API REST e MCP (su /mcp) dalla stessa porta.

Due livelli di accesso:
- chi usa la wiki (domande, lettura, caricamento): dal computer stesso senza formalità, dalla
  rete con un token personale;
- chi la amministra (/api/admin: modelli, spazi, utenti): solo dal computer su cui gira.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import fields, replace
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel

from . import __version__, apphome
from .app import PROVIDERS, Hub, Wiki, add_user, detect_local_servers, detect_ocr, save_secret
from .config import LOOPBACK, Config
from .extract import SUPPORTED
from .icon import icon_bytes
from .llm import LLMError, make_llm
from .mcp_server import build_mcp
from .ocr import make_ocr
from .ocr_local import catalog as ocr_catalog
from .ocr import probe as probe_ocr
from .store import METHODS, norm_path, sha_file
from .tools import ToolError

log = logging.getLogger("llmwiki.server")
WEB_DIR = Path(__file__).parent / "web"
PUBLIC_PATHS = {"/", "/favicon.ico", "/icon.png"}
# Le impostazioni che si possono cambiare dall'interfaccia; le altre solo a mano nel file.
EDITABLE = {
    "llm": {"provider", "base_url", "api_key_env", "agent_model", "summary_model", "judge_model",
            "send_reasoning_effort", "agent_effort", "summary_effort", "tool_mode", "context_tokens"},
    "index": {"concurrency", "fanout"},
    "ocr": {"mode", "kind", "name", "prompt", "strips", "folders", "model_path", "mmproj_path", "llama_server",
            "base_url", "model", "api_key_env", "start_command", "path", "language"},
    "verify": {"enabled", "judge", "threshold"},
    "server": {"host", "port"},
}
CASTS = {"bool": bool, "int": int, "float": float, "str": lambda value: str(value).strip()}


class AskBody(BaseModel):
    question: str
    folder: str = ""
    history: list[dict] = []  # scambi precedenti [{question, answer}] per gli approfondimenti


class VerifyBody(BaseModel):
    doc: str
    start_line: int
    end_line: int
    claim: str


async def _reject(send, status: int, message: str) -> None:
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json")]})
    await send({"type": "http.response.body", "body": json.dumps({"error": message}).encode()})


class AccessMiddleware:
    """Stabilisce chi sta chiamando (`request.state.user`, `request.state.local`) e respinge
    chi non ha titolo, prima che la richiesta arrivi alle rotte o al server MCP."""

    def __init__(self, app, hub: Hub) -> None:
        self.app, self.hub = app, hub

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        server = self.hub.wiki.cfg.server
        headers = dict(scope["headers"])
        host_header = headers.get(b"host", b"").decode()
        client = (scope.get("client") or ("", 0))[0]
        # "Dal computer stesso" vale solo se anche l'indirizzo richiesto è locale: così una
        # pagina web malevola non può passare per il browser dell'utente (DNS rebinding).
        local = (server.trust_loopback and client in LOOPBACK
                 and urlsplit("//" + host_header).hostname in LOOPBACK)
        origin = headers.get(b"origin", b"").decode()
        if (origin and scope["method"] not in ("GET", "HEAD", "OPTIONS")
                and urlsplit(origin).netloc != host_header):
            return await _reject(send, 403, "richiesta da un'altra origine")

        user = "locale" if local else ""
        if scope["path"].startswith("/api/admin"):
            if not local:
                return await _reject(send, 403, "l'amministrazione è possibile solo dal computer su cui gira l'app")
        elif not local and scope["path"] not in PUBLIC_PATHS:
            header = headers.get(b"authorization", b"")
            supplied = header[7:].strip() if header[:7].lower() == b"bearer " else b""
            for name, token in server.users.items():
                if token and hmac.compare_digest(token.encode(), supplied):
                    user = name
            if not user:
                return await _reject(send, 401, "token mancante o non valido")
        scope.setdefault("state", {}).update(local=local, user=user)
        await self.app(scope, receive, send)


def apply_settings(cfg: Config, patch: dict) -> None:
    """Applica a `cfg` le impostazioni arrivate dall'interfaccia, rifiutando ciò che non è
    modificabile o non ha senso. Non salva: lo fa chi chiama, se tutto è andato bene."""
    for section, values in patch.items():
        if section not in EDITABLE or not isinstance(values, dict):
            raise ValueError(f"sezione non modificabile: {section!r}")
        target = getattr(cfg, section)
        kinds = {f.name: f.type for f in fields(target)}
        for key, value in values.items():
            if key not in EDITABLE[section]:
                raise ValueError(f"impostazione non modificabile: {section}.{key}")
            setattr(target, key, CASTS[kinds[key]](value))
    if cfg.llm.provider not in ("anthropic", "openai", "mock"):
        raise ValueError("provider: anthropic, openai oppure mock")
    if cfg.llm.tool_mode not in ("auto", "native", "text"):
        raise ValueError("llm.tool_mode: auto, native oppure text")
    if cfg.verify.judge not in ("auto", "nli", "llm"):
        raise ValueError("verify.judge: auto, nli oppure llm")
    if not 0 < cfg.verify.threshold < 1:
        raise ValueError("la soglia deve stare tra 0 e 1")
    if not 1 <= cfg.index.concurrency <= 64 or not 2 <= cfg.index.fanout <= 64:
        raise ValueError("parallelismo tra 1 e 64, ampiezza dei gruppi tra 2 e 64")
    if cfg.ocr.mode not in ("auto", "text", "ocr") or cfg.ocr.kind not in ("", "local", "server", "tesseract"):
        raise ValueError("ocr.mode: auto, text oppure ocr; ocr.kind: local, server oppure tesseract")
    if not 0 <= cfg.ocr.strips <= 12:
        raise ValueError("ocr.strips: da 0 (pagina intera) a 12")
    if cfg.server.host not in LOOPBACK and not cfg.server.users:
        raise ValueError("per condividere in rete crea prima almeno un utente")


def _saved_keys() -> dict:
    """Per ogni fornitore, se la sua chiave è già disponibile (mai il valore)."""
    return {p["key"]: bool(os.environ.get(p["key"])) for p in PROVIDERS if p["key"]}


def _settings(hub: Hub) -> dict:
    cfg = hub.wiki.cfg
    hub.refresh_judge()
    return {
        "version": __version__,
        **{section: {name: getattr(getattr(cfg, section), name) for name in names}
           for section, names in EDITABLE.items()},
        "users": sorted(cfg.server.users),
        "providers": PROVIDERS,
        "keys": _saved_keys(),
        "judge_model": hub.download.status(),
        "ocr_catalog": ocr_catalog(),
        "ocr_folder": str(apphome.home() / "ocr"),
        "active_judge": hub.wiki.agent.verifier.judge_name,
        "docs_dir": str(cfg.docs_dir),
        "config_file": str(cfg.path or ""),
        "desktop": hub.registry is not None,
    }


def _wiki_routes(app: FastAPI, hub: Hub) -> None:
    """Uso della wiki: lettura, ricerca, caricamento, domande."""

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (WEB_DIR / "index.html").read_text(encoding="utf-8")

    # L'icona della finestra: la finestra è un browser in modalità app, e senza favicon Windows
    # le dà l'icona del browser anche nella barra delle applicazioni.
    @app.get("/favicon.ico")
    async def favicon() -> Response:
        return Response(icon_bytes("ico"), media_type="image/x-icon")

    @app.get("/icon.png")
    async def icon_png() -> Response:
        return Response(icon_bytes("png"), media_type="image/png")

    @app.get("/api/status")
    async def status(request: Request) -> dict:
        hub.refresh_judge()
        wiki = hub.wiki
        info = wiki.indexer.status()
        info.update(
            version=__version__, provider=wiki.cfg.llm.provider, model=wiki.cfg.llm.agent_model,
            judge=wiki.agent.verifier.judge_name, local=request.state.local,
            auth=bool(wiki.cfg.server.users),
        )
        if hub.registry is not None:
            active = hub.registry.active()
            info["space"] = active["id"] if active else ""
            info["spaces"] = [{"id": s["id"], "name": s["name"]} for s in hub.registry.spaces]
        if hub.updater is not None and request.state.local:
            info["update"] = hub.updater.status()
        return info

    @app.get("/api/folder")
    async def folder(path: str = "") -> dict:
        return hub.wiki.tools.list_folder(path)

    @app.get("/api/node")
    async def node(id: str) -> dict:
        return hub.wiki.tools.read_node(id)

    @app.get("/api/summary")
    async def summary(doc: str) -> dict:
        text = hub.wiki.tools.read_summary(doc)
        row = hub.wiki.store.get_doc(norm_path(doc))
        read = {key: row[key] for key in ("model", "seconds", "read_at", "ocr", "method")} if row else {}
        return {"doc": doc, "text": text, "read": read}

    @app.get("/api/document")
    async def document(doc: str, start: int = 1, end: int = 0) -> dict:
        return {"doc": doc, "text": hub.wiki.tools.read_document(doc, start, end)}

    @app.get("/api/search")
    async def search(q: str, folder: str = "", limit: int = 10) -> dict:
        return hub.wiki.tools.search(q, folder, limit)

    @app.post("/api/upload")
    async def upload(files: list[UploadFile] = File(...), folder: str = Form(""),
                     method: str = Form("")) -> dict:
        """`method`: come leggerli ("" = come dice lo spazio, "auto", "text", "ocr")."""
        if method not in METHODS:
            raise ValueError(f"modo di lettura non valido: {method!r}")
        wiki = hub.wiki
        saved, rejected = [], []
        for item in files:
            name = Path(item.filename or "").name
            if Path(name).suffix.lower() not in SUPPORTED:
                rejected.append({"file": name, "reason": "formato non supportato"})
                continue
            relative = norm_path(f"{folder}/{name}")
            target = wiki.store.doc_file(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_name(target.name + ".upload")
            with tmp.open("wb") as handle:
                while block := await item.read(1 << 20):
                    handle.write(block)
            os.replace(tmp, target)
            if method:  # il documento entra subito in coda con il suo modo di lettura
                stat = target.stat()
                wiki.store.upsert_pending(relative, sha_file(target), stat.st_size, stat.st_mtime)
                wiki.store.set_method(relative, method)
            saved.append(relative)
        if saved:
            wiki.indexer.trigger()  # parte subito, anche se un'indicizzazione è già in corso
        return {"saved": saved, "rejected": rejected}

    @app.post("/api/ask")
    async def ask(body: AskBody, request: Request) -> dict:
        if not body.question.strip():
            raise HTTPException(400, "domanda vuota")
        hub.refresh_judge()
        answer = await hub.wiki.ask(body.question.strip(), body.folder, history=body.history,
                                    user=request.state.user)
        return answer.to_dict()

    @app.post("/api/ask/stream")
    async def ask_stream(body: AskBody, request: Request) -> StreamingResponse:
        """Come /api/ask, ma racconta i passi mentre avvengono: una riga JSON per evento
        (step, verifying, answer, error). Chiudere la connessione ferma l'agente."""
        if not body.question.strip():
            raise HTTPException(400, "domanda vuota")
        hub.refresh_judge()
        wiki, user = hub.wiki, request.state.user
        queue: asyncio.Queue = asyncio.Queue()

        async def run() -> None:
            try:
                answer = await wiki.ask(body.question.strip(), body.folder, history=body.history,
                                        on_event=queue.put_nowait, user=user)
                queue.put_nowait({"type": "answer", "answer": answer.to_dict()})
            except (LLMError, ToolError, ValueError) as exc:
                queue.put_nowait({"type": "error", "error": str(exc)})
            except Exception as exc:
                log.exception("domanda non riuscita")
                queue.put_nowait({"type": "error", "error": f"errore interno: {exc!r}"})
            finally:
                queue.put_nowait(None)

        task = asyncio.create_task(run())

        async def events():
            try:
                while True:
                    try:  # asyncio.timeout: wait_for di Python 3.11 può perdere la chiusura
                        async with asyncio.timeout(15):
                            item = await queue.get()
                    except TimeoutError:
                        yield '{"type": "ping"}\n'  # tiene viva la connessione nelle attese lunghe
                        continue
                    if item is None:
                        break
                    yield json.dumps(item, ensure_ascii=False) + "\n"
            finally:
                task.cancel()  # se chi ha chiesto se ne va, il modello smette di lavorare

        return StreamingResponse(events(), media_type="application/x-ndjson",
                                 headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})

    @app.post("/api/verify")
    async def verify(body: VerifyBody) -> dict:
        hub.refresh_judge()
        citation = await hub.wiki.verify(body.doc, body.start_line, body.end_line, body.claim)
        return citation.to_dict()

    @app.get("/api/history")
    async def history(request: Request, limit: int = 30) -> dict:
        return {"items": hub.wiki.store.list_history(request.state.user, limit)}

    @app.delete("/api/history")
    async def clear_history(request: Request) -> dict:
        hub.wiki.store.clear_history(request.state.user)
        return {"items": []}


def _admin_routes(app: FastAPI, hub: Hub) -> None:
    """Amministrazione: raggiungibile solo dal computer dell'app (lo garantisce il middleware)."""

    def registry():
        if hub.registry is None:
            raise ValueError("gli spazi sono disponibili solo nell'app desktop")
        return hub.registry

    @app.get("/api/admin/settings")
    async def get_settings() -> dict:
        return _settings(hub)

    @app.post("/api/admin/settings")
    async def set_settings(patch: dict) -> dict:
        current = hub.wiki.cfg
        cfg = Config.load(current.path) if current.path else current
        apply_settings(cfg, patch)
        cfg.save()
        await hub.replace(cfg)
        if "ocr" in patch:  # cambiato il modo di leggere i PDF: chi non si leggeva riprova
            hub.wiki.store.retry_errors()
            hub.wiki.indexer.trigger()
        return _settings(hub)

    @app.get("/api/admin/detect")
    async def detect() -> dict:
        return {"servers": await detect_local_servers()}

    @app.post("/api/admin/models")
    async def models(body: dict) -> dict:
        """Modelli offerti dal fornitore indicato nel modulo (non ancora salvato)."""
        llm_cfg = replace(hub.wiki.cfg.llm, **{
            key: str(body.get(key, "")).strip() for key in ("provider", "base_url", "api_key_env")})
        client = make_llm(llm_cfg)
        try:
            return {"models": await client.list_models()}
        finally:
            await client.aclose()

    @app.post("/api/admin/test-model")
    async def test_model() -> dict:
        """Prova il modello salvato e dice che cosa sa fare."""
        return await hub.wiki.llm.probe(hub.wiki.cfg.llm.agent_model)

    @app.post("/api/admin/secret")
    async def secret(body: dict) -> dict:
        save_secret(str(body.get("name", "")), str(body.get("value", "")).strip())
        await hub.replace(hub.wiki.cfg)  # il client del modello va ricreato con la nuova chiave
        return {"keys": _saved_keys()}

    @app.post("/api/admin/model/download")
    async def model_download() -> dict:
        hub.download.start()
        return hub.download.status()

    @app.get("/api/admin/errors")
    async def errors() -> dict:
        return {"errors": [{"doc": row["path"], "error": row["error"]}
                           for row in hub.wiki.store.all_docs() if row["status"] == "error"]}

    @app.post("/api/admin/retry-errors")
    async def retry_errors() -> dict:
        hub.wiki.store.retry_errors()
        hub.wiki.indexer.trigger()
        return hub.wiki.indexer.status()

    @app.post("/api/admin/open-folder")
    async def open_folder() -> dict:
        folder = hub.wiki.cfg.docs_dir
        if sys.platform == "win32":
            os.startfile(folder)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(folder)])
        return {"opened": str(folder)}

    @app.post("/api/admin/quit")
    async def quit_app() -> dict:
        if hub.quit is None:
            raise ValueError("questo server si ferma da chi lo ha avviato")
        asyncio.get_running_loop().call_later(0.3, hub.quit)  # il tempo di rispondere
        return {"quitting": True}

    @app.post("/api/admin/users")
    async def create_user(body: dict) -> dict:
        name = str(body.get("name", "")).strip()
        return {"name": name, "token": add_user(hub.wiki.cfg, name)}

    @app.delete("/api/admin/users/{name}")
    async def delete_user(name: str) -> dict:
        server = hub.wiki.cfg.server
        if name not in server.users:
            raise ValueError(f"utente inesistente: {name!r}")
        del server.users[name]
        if not server.users and server.host not in LOOPBACK:
            server.host = "127.0.0.1"  # senza utenti non si resta esposti in rete
        hub.wiki.cfg.save()
        return {"users": sorted(server.users)}

    @app.post("/api/admin/spaces")
    async def add_space(body: dict) -> dict:
        space = registry().add(str(body.get("name", "")), body.get("path") or None,
                               template=hub.wiki.cfg)
        await hub.switch_space(space["id"])
        return space

    @app.post("/api/admin/spaces/switch")
    async def switch_space(body: dict) -> dict:
        return await hub.switch_space(str(body.get("id", "")))

    @app.delete("/api/admin/spaces/{space_id}")
    async def remove_space(space_id: str) -> dict:
        spaces = registry()
        if len(spaces.spaces) <= 1:
            raise ValueError("non si può togliere l'unico spazio")
        was_active = (spaces.active() or {}).get("id") == space_id
        spaces.remove(space_id)
        if was_active:
            await hub.switch_space(spaces.active()["id"])
        return {"spaces": spaces.spaces}


def _reading_routes(app: FastAPI, hub: Hub) -> None:
    """Fermare e riprendere la lettura, aggiornare l'app: solo dal computer dell'app."""

    @app.post("/api/admin/index/pause")
    async def pause_reading() -> dict:
        await hub.wiki.indexer.pause()
        return hub.wiki.indexer.status()

    @app.post("/api/admin/index/resume")
    async def resume_reading() -> dict:
        hub.wiki.indexer.resume()
        return hub.wiki.indexer.status()

    @app.post("/api/admin/doc-method")
    async def doc_method(body: dict) -> dict:
        """Rilegge un documento con il modo indicato ("Rileggi con…" nella sua scheda)."""
        path = norm_path(str(body.get("doc", "")))
        if hub.wiki.store.get_doc(path) is None:
            raise ToolError(f"documento non trovato: {path}")
        hub.wiki.store.set_method(path, str(body.get("method", "")))
        hub.wiki.indexer.trigger()
        return {"doc": path, "method": hub.wiki.store.get_doc(path)["method"]}

    @app.post("/api/admin/update")
    async def update_app() -> dict:
        """Scarica e installa la versione nuova; poi l'app si chiude e l'installatore la riapre."""
        if hub.updater is None or hub.quit is None:
            raise ValueError("l'aggiornamento è disponibile solo nell'app desktop")
        hub.updater.start(hub.quit)
        return hub.updater.status()


def _ocr_routes(app: FastAPI, hub: Hub) -> None:
    """Cercare e provare gli OCR: solo dal computer dell'app."""

    @app.get("/api/admin/ocr/detect")
    async def ocr_detect(folders: str | None = None) -> dict:
        """`folders`: le cartelle scritte nella pagina, anche se non ancora salvate."""
        return {"found": await detect_ocr(hub.wiki.cfg.ocr.folders if folders is None else folders)}

    @app.post("/api/admin/ocr/test")
    async def ocr_test() -> dict:
        """Prova l'OCR salvato con l'immagine di prova."""
        engine = make_ocr(hub.wiki.cfg.ocr)
        if engine is None:
            return {"ok": False, "error": "nessun OCR collegato", "text": "", "seconds": 0}
        try:
            return dict(await asyncio.to_thread(probe_ocr, engine), name=engine.name)
        finally:
            engine.close()


def create_app(wiki_or_hub: Wiki | Hub) -> FastAPI:
    hub = wiki_or_hub if isinstance(wiki_or_hub, Hub) else Hub(wiki_or_hub)
    mcp = build_mcp(hub)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        host=hub.wiki.cfg.server.host,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            await hub.start()
            try:
                yield
            finally:
                await hub.stop()

    app = FastAPI(title="LLMWiki", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(AccessMiddleware, hub=hub)
    for error, status in ((ToolError, 404), (ValueError, 400), (LLMError, 502)):
        app.add_exception_handler(
            error, lambda _request, exc, status=status: JSONResponse({"error": str(exc)}, status_code=status))
    _wiki_routes(app, hub)
    _admin_routes(app, hub)
    _reading_routes(app, hub)
    _ocr_routes(app, hub)
    app.mount("/", mcp_app)  # il server MCP risponde su /mcp: va montato dopo le rotte dell'API
    return app
