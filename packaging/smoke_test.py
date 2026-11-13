"""Collaudo dell'app impacchettata: la avvia in una cartella dati usa e getta e ne prova le
funzioni principali. Lo esegue packaging/build.ps1 dopo ogni build.

  uv run python packaging/smoke_test.py [percorso di LLMWiki.exe]
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).parent.parent
DOC = ("# Contratto\n\n## Consegne\nLa consegna avviene entro 30 giorni dalla data dell'ordine.\n\n"
       "## Penali\nIn caso di ritardo è prevista una penale del 2% del valore dell'ordine per ogni "
       "settimana di ritardo.\n")


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "LLMWiki" / "LLMWiki.exe"
    if not exe.is_file():
        print(f"eseguibile non trovato: {exe}")
        return 2
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="llmwiki-collaudo-", ignore_cleanup_errors=True) as home:
        env = dict(os.environ, LLMWIKI_HOME=home)
        # uno spazio già pronto con il modello finto: il collaudo non dipende da modelli veri
        setup = ("from llmwiki import apphome; from llmwiki.config import Config; "
                 "t = Config.from_dict({'llm': {'provider': 'mock'}, 'verify': {'judge': 'llm'}}, apphome.home()); "
                 "apphome.Registry().add('Collaudo', template=t)")
        subprocess.run([sys.executable, "-c", setup], env=env, check=True, cwd=ROOT / "src")
        process = subprocess.Popen([str(exe), "--no-window", "--no-tray", "--port", str(port)], env=env)
        checks: list[tuple[str, bool]] = []
        try:
            client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=60)
            status = None
            for _ in range(120):
                try:
                    status = client.get("/api/status").json()
                    break
                except httpx.HTTPError:
                    if process.poll() is not None:
                        break
                    time.sleep(0.5)
            checks.append(("si avvia e risponde", bool(status)))
            if status:
                client.post("/api/upload", data={"folder": "contratti"},
                            files=[("files", ("acme.md", DOC.encode(), "text/markdown"))])
                for _ in range(100):
                    status = client.get("/api/status").json()
                    if status["ready"] == 1 and not status["busy"]:
                        break
                    time.sleep(0.2)
                checks.append(("indicizza un documento caricato", status["ready"] == 1 and status["error"] == 0))
                good = client.post("/api/verify", json={
                    "doc": "contratti/acme.md", "start_line": 7, "end_line": 7,
                    "claim": "prevista una penale del 2% per ogni settimana di ritardo"}).json()
                bad = client.post("/api/verify", json={
                    "doc": "contratti/acme.md", "start_line": 4, "end_line": 4,
                    "claim": "prevista una penale del 5% per ogni settimana di ritardo"}).json()
                checks.append(("conferma una citazione giusta", good.get("status") in ("verified", "rechecked")))
                checks.append(("segnala una citazione sbagliata", bad.get("status") == "warning"))
                with client.stream("POST", "/api/ask/stream", json={"question": "penale ritardo"}) as response:
                    events = [json.loads(line) for line in response.iter_lines() if line]
                checks.append(("risponde con avanzamento in diretta",
                               events[0]["type"] == "step" and events[-1]["type"] == "answer"
                               and bool(events[-1]["answer"]["citations"])))
                checks.append(("ricorda la cronologia", len(client.get("/api/history").json()["items"]) == 1))
                tools = client.post("/mcp", headers={"Accept": "application/json, text/event-stream"},
                                    json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}).json()
                checks.append(("espone gli strumenti MCP", len(tools["result"]["tools"]) >= 9))
                settings = client.get("/api/admin/settings").json()
                checks.append(("apre le impostazioni", settings["desktop"] is True))
                page = client.get("/").text
                checks.append(("serve l'interfaccia", "LLMWiki" in page and "ask/stream" in page))
                client.post("/api/admin/quit")
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    pass
                checks.append(("si chiude a comando", process.poll() is not None))
        finally:
            if process.poll() is None:
                process.kill()
        log = Path(home) / "logs" / "llmwiki.log"
        crashed = log.exists() and "Traceback" in log.read_text(encoding="utf-8", errors="replace")
        checks.append(("nessun errore nel log", not crashed))
    for name, ok in checks:
        print(f"  {'ok ' if ok else 'NO '} {name}")
    failed = [name for name, ok in checks if not ok]
    print("collaudo superato" if not failed else f"collaudo NON superato: {', '.join(failed)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
