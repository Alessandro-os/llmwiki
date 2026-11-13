"""Riga di comando: init, index, ask, serve, mcp, status, user add, model, app."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from . import nli
from .app import Hub, Wiki, add_user, detect_local_servers, load_secrets, use_local_server
from .config import LOOPBACK, Config
from .store import Store


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
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
    p_model.add_argument("action", choices=["install", "status"])
    p_user = sub.add_parser("user", help="gestione utenti del server")
    p_user.add_argument("action", choices=["add"])
    p_user.add_argument("name")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr,
    )
    load_secrets()
    if args.command == "init":
        return _init(args)
    if args.command == "model":
        return _model(args)
    if args.command == "app":
        from .desktop import main as desktop_main

        return desktop_main([])
    cfg = Config.load(args.config)
    if cfg.path is None:
        print("wiki.toml non trovato: esegui prima `llmwiki init`.", file=sys.stderr)
        return 2
    commands = {"index": _index, "status": _status, "ask": _ask, "serve": _serve, "mcp": _mcp,
                "user": _user}
    try:
        return commands[args.command](cfg, args)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _init(args) -> int:
    path = Path(args.config or "wiki.toml").resolve()
    if path.exists():
        print(f"{path} esiste già: non lo tocco.")
    else:
        cfg = Config.from_dict({"llm": {"provider": args.provider}}, path.parent, path)
        if args.provider == "openai":
            servers = asyncio.run(detect_local_servers())
            if servers:
                use_local_server(cfg, servers[0])
                print(f"Collegato a {servers[0]['name']}: {cfg.llm.agent_model}")
            else:
                cfg.llm.agent_model = cfg.llm.summary_model = cfg.llm.judge_model = ""
                print("Nessun server di modelli acceso su questo computer: imposta base_url e i "
                      "tre modelli in wiki.toml.")
        cfg.save()
        print(f"Creato {path}")
    cfg = Config.load(path)
    cfg.docs_dir.mkdir(parents=True, exist_ok=True)
    cfg.wiki_dir.mkdir(parents=True, exist_ok=True)
    print(f"Documenti: {cfg.docs_dir}\nWiki:      {cfg.wiki_dir}")
    print("Metti i documenti nella cartella dei documenti, poi `llmwiki index` o `llmwiki serve`.")
    return 0


def _print_errors(cfg: Config) -> None:
    store = Store(cfg.docs_dir, cfg.wiki_dir)
    for row in store.all_docs():
        if row["status"] == "error":
            print(f"  ! {row['path']}: {row['error']}")
    store.close()


def _index(cfg: Config, _args) -> int:
    async def run() -> dict:
        wiki = Wiki(cfg)
        try:
            return await wiki.indexer.run_once()
        finally:
            await wiki.aclose()

    status = asyncio.run(run())
    print(f"Documenti pronti: {status['ready']} su {status['total']} · nodi dell'albero: "
          f"{status['nodes']} · errori: {status['error']}")
    print(f"Chiamate al modello: {status['llm_calls'] or 'nessuna (tutto già aggiornato)'}")
    if status["error"]:
        _print_errors(cfg)
    return 1 if status["error"] else 0


def _status(cfg: Config, _args) -> int:
    store = Store(cfg.docs_dir, cfg.wiki_dir)
    print(json.dumps(store.counts(), ensure_ascii=False, indent=2))
    store.close()
    _print_errors(cfg)
    return 0


def _ask(cfg: Config, args) -> int:
    async def run():
        wiki = Wiki(cfg)
        try:
            return await wiki.ask(args.question, args.folder)
        finally:
            await wiki.aclose()

    answer = asyncio.run(run())
    print(json.dumps(answer.to_dict(), ensure_ascii=False, indent=2) if args.json else answer.render())
    return 0


def _serve(cfg: Config, args) -> int:
    import uvicorn

    from .server import create_app

    cfg.server.host = args.host or cfg.server.host
    cfg.server.port = args.port or cfg.server.port
    if cfg.server.host not in LOOPBACK and not cfg.server.users:
        print(f"Rifiuto di ascoltare su {cfg.server.host} senza utenti: chiunque in rete potrebbe "
              "leggere i documenti.\nCrea almeno un token con `llmwiki user add <nome>`.",
              file=sys.stderr)
        return 2
    print(f"llmwiki su http://{cfg.server.host}:{cfg.server.port}  (MCP: /mcp)")
    uvicorn.run(create_app(Wiki(cfg)), host=cfg.server.host, port=cfg.server.port, log_level="warning")
    return 0


def _mcp(cfg: Config, _args) -> int:
    from .mcp_server import build_mcp

    build_mcp(Hub(Wiki(cfg))).run("stdio")
    return 0


def _model(args) -> int:
    download = nli.Download()
    if args.action == "status":
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
    token = add_user(cfg, args.name)
    print(f"Utente {args.name!r} aggiunto a {cfg.path}. Riavvia il server per applicarlo.")
    print(f"Token (da dare a {args.name}, non verrà mostrato di nuovo):\n  {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
