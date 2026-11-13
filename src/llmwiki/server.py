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
import os
import re
import secrets
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import fields
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from . import __version__
from .app import SECRET_NAMES, Hub, Wiki, save_secret
from .config import Config
from .extract import SUPPORTED
from .llm import LLMError
from .mcp_server import build_mcp
from .store import norm_path
from .tools import ToolError

WEB_DIR = Path(__file__).parent / "web"
PUBLIC_PATHS = {"/", "/favicon.ico"}
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
# Server locali che l'app sa riconoscere da sola (tutti con API compatibile OpenAI).
LOCAL_SERVERS = (("Strata / llama.cpp", 8080), ("Ollama", 11434), ("LM Studio", 1234), ("vLLM", 8000))
EDITABLE = {
    "llm": {"provider", "base_url", "agent_model", "summary_model", "judge_model",
            "send_reasoning_effort", "agent_effort", "summary_effort"},
    "index": {"concurrency", "fanout"},
    "verify": {"enabled", "judge", "threshold"},
    "server": {"host", "port"},
}


def _reply(send, status: int, message: str):
    async def run():
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": json.dumps({"error": message}).encode()})
    return run()


class AccessMiddleware:
    def __init__(self, app, hub: Hub) -> None:
        self.app, self.hub = app, hub

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        cfg = self.hub.wiki.cfg
        headers = dict(scope["headers"])
        path, method = scope["path"], scope["method"]
        host = urlsplit("//" + headers.get(b"host", b"").decode()).hostname or ""
        client = (scope.get("client") or ("", 0))[0]
        # "Dal computer stesso" vale solo se anche l'indirizzo richiesto è locale: così una
        # pagina web malevola non può passare per il browser dell'utente (DNS rebinding).
        local = cfg.server.trust_loopback and client in LOOPBACK and host in LOOPBACK
        origin = headers.get(b"origin", b"").decode()
        if origin and method not in ("GET", "HEAD", "OPTIONS"):
            if urlsplit(origin).netloc != headers.get(b"host", b"").decode():
                return await _reply(send, 403, "richiesta da un'altra origine")
        if path.startswith("/api/admin"):
            if not local:
                return await _reply(send, 403, "l'amministrazione è possibile solo dal computer su cui gira l'app")
        elif not local and path not in PUBLIC_PATHS and not path.startswith("/static/"):
            tokens = {token.encode(): name for name, token in cfg.server.users.items() if token}
            header = headers.get(b"authorization", b"")
            supplied = header[7:].strip() if header[:7].lower() == b"bearer " else b""
            user = None
            for token, name in tokens.items():
                if hmac.compare_digest(token, supplied):
                    user = name
            if user is None and (tokens or not cfg.server.trust_loopback or client not in LOOPBACK):
                return await _reply(send, 401, "token mancante o non valido")
        scope.setdefault("state", {})["local"] = local
        await self.app(scope, receive, send)


class AskBody(BaseModel):
    question: str
    folder: str = ""


class VerifyBody(BaseModel):
    doc: str
    start_line: int
    end_line: int
    claim: str


async def detect_local_servers() -> list[dict]:
    import httpx

    async def probe(name: str, port: int) -> dict | None:
        base = f"http://127.0.0.1:{port}/v1"
        try:
            async with httpx.AsyncClient(timeout=1.5) as http:
                data = (await http.get(base + "/models")).json()
            models = [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
        except Exception:
            return None
        return {"name": name, "base_url": base, "models": models} if models else None

    found = await asyncio.gather(*(probe(name, port) for name, port in LOCAL_SERVERS))
    return [item for item in found if item]


def create_app(wiki_or_hub: Wiki | Hub, *, run_indexer: bool = True) -> FastAPI:
    hub = wiki_or_hub if isinstance(wiki_or_hub, Hub) else Hub(wiki_or_hub)
    mcp = build_mcp(hub)
    mcp_app = mcp.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True,
        host=hub.wiki.cfg.server.host,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        async with mcp.session_manager.run():
            if run_indexer:
                await hub.start()
            try:
                yield
            finally:
                await hub.stop()

    app = FastAPI(title="llmwiki", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(AccessMiddleware, hub=hub)
    app.state.hub = hub

    @app.exception_handler(ToolError)
    async def _tool_error(_request, exc: ToolError):
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.exception_handler(LLMError)
    async def _llm_error(_request, exc: LLMError):
        return JSONResponse({"error": f"modello: {exc}"}, status_code=502)

    @app.exception_handler(ValueError)
    async def _value_error(_request, exc: ValueError):
        return JSONResponse({"error": str(exc)}, status_code=400)

    # ------------------------------------------------------------ uso della wiki

    @app.get("/", response_class=HTMLResponse)
    async def index() -> str:
        return (WEB_DIR / "index.html").read_text(encoding="utf-8")

    @app.get("/api/status")
    async def status(request: Request) -> dict:
        hub.refresh_judge()
        wiki = hub.wiki
        info = wiki.indexer.status()
        info.update(
            version=__version__, provider=wiki.cfg.llm.provider, model=wiki.cfg.llm.agent_model,
            judge=wiki.agent.verifier.judge_name, local=bool(request.state.local),
            auth=bool(wiki.cfg.server.users),
        )
        if hub.registry is not None:
            active = hub.registry.active()
            info["space"] = active["id"] if active else ""
            info["spaces"] = [{"id": s["id"], "name": s["name"]} for s in hub.registry.spaces]
        return info

    @app.get("/api/folder")
    async def folder(path: str = "") -> dict:
        return hub.wiki.tools.list_folder(path)

    @app.get("/api/node")
    async def node(id: str) -> dict:
        return hub.wiki.tools.read_node(id)

    @app.get("/api/summary")
    async def summary(doc: str) -> dict:
        return {"doc": doc, "text": hub.wiki.tools.read_summary(doc)}

    @app.get("/api/document")
    async def document(doc: str, start: int = 1, end: int = 0) -> dict:
        return {"doc": doc, "text": hub.wiki.tools.read_document(doc, start, end)}

    @app.get("/api/search")
    async def search(q: str, folder: str = "", limit: int = 10) -> dict:
        return hub.wiki.tools.search(q, folder, limit)

    @app.post("/api/upload")
    async def upload(files: list[UploadFile] = File(...), folder: str = Form("")) -> dict:
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
            saved.append(relative)
        if saved:
            wiki.indexer.trigger()  # parte subito, anche se un'indicizzazione è già in corso
        return {"saved": saved, "rejected": rejected}

    @app.post("/api/ask")
    async def ask(body: AskBody) -> dict:
        if not body.question.strip():
            raise HTTPException(400, "domanda vuota")
        hub.refresh_judge()
        answer = await hub.wiki.ask(body.question.strip(), body.folder)
        return answer.to_dict()

    @app.post("/api/verify")
    async def verify(body: VerifyBody) -> dict:
        hub.refresh_judge()
        citation = await hub.wiki.verify(body.doc, body.start_line, body.end_line, body.claim)
        return citation.to_dict()

    # ------------------------------------------------------------ amministrazione (solo locale)

    def settings_payload() -> dict:
        cfg = hub.wiki.cfg
        hub.refresh_judge()
        return {
            "version": __version__,
            "llm": {name: getattr(cfg.llm, name) for name in EDITABLE["llm"]},
            "index": {name: getattr(cfg.index, name) for name in EDITABLE["index"]},
            "verify": {name: getattr(cfg.verify, name) for name in EDITABLE["verify"]},
            "server": {"host": cfg.server.host, "port": cfg.server.port,
                       "users": sorted(cfg.server.users)},
            "keys": {name: bool(os.environ.get(name)) for name in SECRET_NAMES},
            "judge_model": hub.download.status(),
            "active_judge": hub.wiki.agent.verifier.judge_name,
            "docs_dir": str(cfg.docs_dir),
            "config_file": str(cfg.path) if cfg.path else "",
            "desktop": hub.registry is not None,
        }

    @app.get("/api/admin/settings")
    async def get_settings() -> dict:
        return settings_payload()

    @app.post("/api/admin/settings")
    async def set_settings(patch: dict) -> dict:
        cfg = Config.load(hub.wiki.cfg.path) if hub.wiki.cfg.path else hub.wiki.cfg
        for section, values in patch.items():
            if section not in EDITABLE or not isinstance(values, dict):
                raise ValueError(f"sezione non modificabile: {section!r}")
            target = getattr(cfg, section)
            kinds = {f.name: f.type for f in fields(target)}
            for key, value in values.items():
                if key not in EDITABLE[section]:
                    raise ValueError(f"impostazione non modificabile: {section}.{key}")
                kind = kinds[key]
                if kind == "bool":
                    value = bool(value)
                elif kind == "int":
                    value = int(value)
                elif kind == "float":
                    value = float(value)
                else:
                    value = str(value).strip()
                setattr(target, key, value)
        if cfg.llm.provider not in ("anthropic", "openai", "mock"):
            raise ValueError("provider: anthropic, openai oppure mock")
        if cfg.verify.judge not in ("auto", "nli", "llm"):
            raise ValueError("verify.judge: auto, nli oppure llm")
        if not 0 < cfg.verify.threshold < 1:
            raise ValueError("la soglia deve stare tra 0 e 1")
        if not 1 <= cfg.index.concurrency <= 64 or not 2 <= cfg.index.fanout <= 64:
            raise ValueError("parallelismo tra 1 e 64, ampiezza dei gruppi tra 2 e 64")
        if cfg.server.host not in LOOPBACK and not cfg.server.users:
            raise ValueError("per condividere in rete crea prima almeno un utente")
        cfg.save()
        await hub.replace(cfg)
        return settings_payload()

    @app.get("/api/admin/detect")
    async def detect() -> dict:
        return {"servers": await detect_local_servers()}

    @app.post("/api/admin/test-model")
    async def test_model() -> dict:
        wiki = hub.wiki
        try:
            text = await wiki.llm.complete(
                model=wiki.cfg.llm.agent_model, system="Rispondi con una sola parola.",
                prompt="Scrivi: pronto", kind="test",
            )
        except LLMError as exc:
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "reply": text[:80]}

    @app.post("/api/admin/secret")
    async def secret(body: dict) -> dict:
        save_secret(str(body.get("name", "")), str(body.get("value", "")).strip())
        await hub.replace(hub.wiki.cfg)  # il client del modello va ricreato con la nuova chiave
        return {"keys": {name: bool(os.environ.get(name)) for name in SECRET_NAMES}}

    @app.post("/api/admin/model/download")
    async def model_download() -> dict:
        hub.download.start()
        return hub.download.status()

    @app.post("/api/admin/retry-errors")
    async def retry_errors() -> dict:
        wiki = hub.wiki
        with wiki.store.lock:
            wiki.store.db.execute("UPDATE docs SET status='pending', attempts=0 WHERE status='error'")
        wiki.indexer.trigger()
        return wiki.indexer.status()

    @app.get("/api/admin/errors")
    async def errors() -> dict:
        return {"errors": [{"doc": row["path"], "error": row["error"]}
                           for row in hub.wiki.store.all_docs() if row["status"] == "error"]}

    @app.post("/api/admin/open-folder")
    async def open_folder() -> dict:
        folder = hub.wiki.cfg.docs_dir
        if sys.platform == "win32":
            os.startfile(folder)  # noqa: S606 - apre la cartella dei documenti in Esplora file
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
    async def add_user(body: dict) -> dict:
        name = str(body.get("name", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,40}", name):
            raise ValueError("nome utente: lettere, cifre, _ e - (massimo 40)")
        cfg = hub.wiki.cfg
        if name in cfg.server.users:
            raise ValueError(f"l'utente {name!r} esiste già")
        token = secrets.token_urlsafe(24)
        cfg.server.users[name] = token
        cfg.save()
        return {"name": name, "token": token}

    @app.delete("/api/admin/users/{name}")
    async def delete_user(name: str) -> dict:
        cfg = hub.wiki.cfg
        if name not in cfg.server.users:
            raise ValueError(f"utente inesistente: {name!r}")
        del cfg.server.users[name]
        if not cfg.server.users and cfg.server.host not in LOOPBACK:
            cfg.server.host = "127.0.0.1"  # senza utenti non si resta esposti in rete
        cfg.save()
        return {"users": sorted(cfg.server.users)}

    @app.get("/api/admin/spaces")
    async def spaces() -> dict:
        if hub.registry is None:
            return {"spaces": [], "active": ""}
        active = hub.registry.active()
        return {"spaces": hub.registry.spaces, "active": active["id"] if active else ""}

    @app.post("/api/admin/spaces")
    async def add_space(body: dict) -> dict:
        if hub.registry is None:
            raise ValueError("gli spazi sono disponibili solo nell'app desktop")
        space = hub.registry.add(str(body.get("name", "")), body.get("path") or None,
                                 template=hub.wiki.cfg)
        await hub.switch_space(space["id"])
        return space

    @app.post("/api/admin/spaces/switch")
    async def switch_space(body: dict) -> dict:
        return await hub.switch_space(str(body.get("id", "")))

    @app.delete("/api/admin/spaces/{space_id}")
    async def remove_space(space_id: str) -> dict:
        if hub.registry is None:
            raise ValueError("gli spazi sono disponibili solo nell'app desktop")
        if len(hub.registry.spaces) <= 1:
            raise ValueError("non si può togliere l'unico spazio")
        was_active = (hub.registry.active() or {}).get("id") == space_id
        hub.registry.remove(space_id)
        if was_active:
            await hub.switch_space(hub.registry.active()["id"])
        return {"spaces": hub.registry.spaces}

    # Il server MCP risponde su /mcp: va montato per ultimo, dopo le rotte dell'API.
    app.mount("/", mcp_app)
    return app
