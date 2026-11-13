"""Riga di comando: llmwiki init | index | ask | serve | mcp | status | user add."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import secrets
import sys
from pathlib import Path

from .config import DEFAULT_TOML, Config

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="llmwiki", description="LLM wiki ad albero di riassunti")
    parser.add_argument("--config", "-c", help="percorso di wiki.toml (default: ./wiki.toml)")
    parser.add_argument("--verbose", "-v", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="crea wiki.toml e le cartelle dei dati")
    p_init.add_argument("--provider", choices=["anthropic", "openai", "mock"], default="anthropic")

    sub.add_parser("index", help="indicizza i documenti nuovi o modificati e aggiorna l'albero")
    sub.add_parser("status", help="stato dell'indice")

    p_ask = sub.add_parser("ask", help="fa una domanda alla wiki")
    p_ask.add_argument("question")
    p_ask.add_argument("--folder", default="", help="cartella da cui partire")
    p_ask.add_argument("--json", action="store_true", help="risposta completa in JSON")

    p_serve = sub.add_parser("serve", help="avvia il server condiviso (web, API e MCP su /mcp)")
    p_serve.add_argument("--host")
    p_serve.add_argument("--port", type=int)

    sub.add_parser("mcp", help="server MCP su stdio (per client che lanciano un processo locale)")

    sub.add_parser("app", help="avvia l'app desktop (spazi, finestra, icona nell'area di notifica)")

    p_model = sub.add_parser("model", help="decision model per la verifica delle citazioni")
    model_sub = p_model.add_subparsers(dest="model_command", required=True)
    model_sub.add_parser("install", help="scarica il decision model")
    model_sub.add_parser("status", help="mostra se è installato")

    p_user = sub.add_parser("user", help="gestione utenti del server")
    user_sub = p_user.add_subparsers(dest="user_command", required=True)
    p_add = user_sub.add_parser("add", help="crea un token per un utente")
    p_add.add_argument("name")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr,
    )

    from .app import load_secrets

    load_secrets()
    if args.command == "init":
        return _init(args)
    if args.command == "model":
        return _model(None, args)
    if args.command == "app":
        from .desktop import main as desktop_main

        return desktop_main([])
    cfg = Config.load(args.config)
    if cfg.path is None:
        print("wiki.toml non trovato: esegui prima `llmwiki init`.", file=sys.stderr)
        return 2
    try:
        return {
            "index": _index, "status": _status, "ask": _ask, "serve": _serve, "mcp": _mcp,
            "user": _user,
        }[args.command](cfg, args)
    except KeyboardInterrupt:
        return 130


def _init(args) -> int:
    path = Path(args.config or "wiki.toml").resolve()
    if path.exists():
        print(f"{path} esiste già: non lo tocco.")
    else:
        text = DEFAULT_TOML
        if args.provider == "mock":
            text = text.replace('provider = "anthropic"', 'provider = "mock"')
        elif args.provider == "openai":
            text = text.replace('provider = "anthropic"', 'provider = "openai"')
            for key in ("base_url", "api_key_env", "agent_model", "summary_model", "judge_model"):
                text = text.replace(f"# {key} = ", f"{key} = ")
            text = re.sub(r'^(agent|summary|judge)_model = "claude[^\n]*\n', "", text, flags=re.M)
        path.write_text(text, encoding="utf-8")
        print(f"Creato {path}")
    cfg = Config.load(path)
    cfg.docs_dir.mkdir(parents=True, exist_ok=True)
    cfg.wiki_dir.mkdir(parents=True, exist_ok=True)
    print(f"Documenti: {cfg.docs_dir}\nWiki:      {cfg.wiki_dir}")
    print("Metti i documenti nella cartella dei documenti, poi `llmwiki index` o `llmwiki serve`.")
    return 0


def _wiki(cfg: Config):
    from .app import Wiki

    return Wiki(cfg)


def _index(cfg: Config, _args) -> int:
    async def run() -> dict:
        wiki = _wiki(cfg)
        try:
            return await wiki.indexer.run_once()
        finally:
            await wiki.aclose()

    status = asyncio.run(run())
    print(f"Documenti pronti: {status['ready']} su {status['total']} · nodi dell'albero: "
          f"{status['nodes']} · errori: {status['error']}")
    print(f"Chiamate al modello: {status['llm_calls'] or 'nessuna (tutto già aggiornato)'}")
    if status["error"]:
        from .store import Store

        store = Store(cfg.docs_dir, cfg.wiki_dir)
        for row in store.all_docs():
            if row["status"] == "error":
                print(f"  ! {row['path']}: {row['error']}")
        store.close()
        return 1
    return 0


def _status(cfg: Config, _args) -> int:
    from .store import Store

    store = Store(cfg.docs_dir, cfg.wiki_dir)
    counts = store.counts()
    print(json.dumps(counts, ensure_ascii=False, indent=2))
    for row in store.all_docs():
        if row["status"] == "error":
            print(f"! {row['path']}: {row['error']}")
    store.close()
    return 0


def _ask(cfg: Config, args) -> int:
    async def run():
        wiki = _wiki(cfg)
        try:
            return await wiki.ask(args.question, args.folder)
        finally:
            await wiki.aclose()

    answer = asyncio.run(run())
    if args.json:
        print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(answer.render())
    return 0


def _serve(cfg: Config, args) -> int:
    import uvicorn

    from .server import create_app

    if args.host:
        cfg.server.host = args.host
    if args.port:
        cfg.server.port = args.port
    if cfg.server.host not in LOOPBACK and not cfg.server.users:
        print(
            f"Rifiuto di ascoltare su {cfg.server.host} senza utenti: chiunque in rete potrebbe "
            "leggere i documenti.\nCrea almeno un token con `llmwiki user add <nome>`.",
            file=sys.stderr,
        )
        return 2
    app = create_app(_wiki(cfg))
    print(f"llmwiki su http://{cfg.server.host}:{cfg.server.port}  (MCP: /mcp)")
    uvicorn.run(app, host=cfg.server.host, port=cfg.server.port, log_level="warning")
    return 0


def _mcp(cfg: Config, _args) -> int:
    from .app import Hub
    from .mcp_server import build_mcp

    build_mcp(Hub(_wiki(cfg))).run("stdio")
    return 0


def _model(_cfg, args) -> int:
    from . import nli

    download = nli.Download()
    if args.model_command == "status":
        print(json.dumps(download.status(), ensure_ascii=False, indent=2))
        return 0
    if nli.installed():
        print(f"Decision model già installato in {nli.model_dir()}")
        return 0
    print(f"Scarico {nli.REPO} ({nli.TOTAL_BYTES / 1e9:.1f} GB, licenza {nli.LICENSE}) in {nli.model_dir()} ...")
    status = download.run_blocking()
    if status["status"] != "ready":
        print(f"Scaricamento non riuscito: {status['error']}", file=sys.stderr)
        return 1
    print("Decision model installato.")
    return 0


def _user(cfg: Config, args) -> int:
    name = args.name
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        print("Nome utente: solo lettere, cifre, _ e -.", file=sys.stderr)
        return 2
    if name in cfg.server.users:
        print(f"L'utente {name!r} esiste già.", file=sys.stderr)
        return 2
    token = secrets.token_urlsafe(24)
    line = f'{name} = "{token}"'
    text = cfg.path.read_text(encoding="utf-8-sig")
    tables = re.findall(r"^\[([^\]]+)\]\s*$", text, flags=re.M)
    if tables and tables[-1] == "server.users":
        cfg.path.write_text(text.rstrip("\n") + "\n" + line + "\n", encoding="utf-8")
        print(f"Utente {name!r} aggiunto a {cfg.path}. Riavvia il server per applicarlo.")
    else:
        print(f"Aggiungi questa riga sotto [server.users] in {cfg.path}:\n  {line}")
    print(f"Token (da dare a {name}, non verrà mostrato di nuovo):\n  {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
