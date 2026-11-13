"""Prove end-to-end con il provider mock: nessuna chiamata di rete, nessun token speso."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from llmwiki.app import Wiki
from llmwiki.config import Config
from llmwiki.server import create_app
from llmwiki.store import norm_path
from llmwiki.verify import RECHECKED, VERIFIED, WARNING

CONTRACT = """\
# Contratto di fornitura Acme

## Art. 7 · Consegne
La consegna avviene entro 30 giorni dalla data dell'ordine.

## Art. 9 · Penali
In caso di ritardo è prevista una penale del 2% del valore dell'ordine per ogni
settimana di ritardo, fino a un massimo del 10%.
"""


def make_cfg(tmp_path: Path, **index) -> Config:
    data = {
        "llm": {"provider": "mock"},
        "index": {"fanout": 4, "concurrency": 6, **index},
        # judge "llm": i test non devono dipendere dal decision model installato sul PC
        "verify": {"context_lines": 2, "judge": "llm", "threshold": 0.75},
    }
    return Config.from_dict(data, tmp_path)


def write_docs(cfg: Config, folder: str, count: int, start: int = 0) -> None:
    target = cfg.docs_dir / folder
    target.mkdir(parents=True, exist_ok=True)
    for n in range(start, start + count):
        (target / f"nota_{n:03d}.md").write_text(
            f"# Nota {n}\n\nArgomento numero {n}: il progetto Zefiro{n} ha un budget di {1000 + n} euro.\n",
            encoding="utf-8",
        )


def test_tree_is_built_and_updates_incrementally(tmp_path):
    cfg = make_cfg(tmp_path)
    write_docs(cfg, "progetti", 20)
    (cfg.docs_dir / "contratti").mkdir(parents=True)
    (cfg.docs_dir / "contratti" / "acme.md").write_text(CONTRACT, encoding="utf-8")

    async def scenario():
        wiki = Wiki(cfg)
        status = await wiki.indexer.run_once()
        assert status["ready"] == 21 and status["error"] == 0
        # 20 documenti con fanout 4: 5 sintesi di primo livello; al secondo livello le prime 4
        # si fondono in una sintesi, la quinta resta da sola e sale così com'è.
        folder = wiki.tools.list_folder("progetti")
        assert folder["syntheses"] == ["progetti::L2-0000", "progetti::L1-0004"]
        assert len(wiki.tools.read_node("progetti::L1-0000")["children"]) == 4
        assert wiki.tools.list_folder("")["subfolders"] == ["contratti", "progetti"]
        first = dict(wiki.llm.calls)
        assert first["doc"] == 21 and first["node"] == 6 and first["map"] == 3

        # Nulla è cambiato: nessuna chiamata al modello.
        await wiki.indexer.run_once()
        assert wiki.llm.calls == first

        # Un documento in più tocca un solo ramo: la sua scheda, una sintesi, le 2 mappe sopra.
        # Le altre 20 schede e 6 sintesi non vengono rigenerate.
        write_docs(cfg, "progetti", 1, start=20)
        await wiki.indexer.run_once()
        delta = {k: wiki.llm.calls[k] - first[k] for k in first}
        assert delta == {"doc": 1, "node": 1, "map": 2}

        # Documento rimosso: sparisce da indice e ricerca.
        (cfg.docs_dir / "contratti" / "acme.md").unlink()
        await wiki.indexer.run_once()
        assert wiki.store.get_doc("contratti/acme.md") is None
        assert wiki.tools.search("penale ritardo")["results"] == []
        assert wiki.tools.list_folder("")["subfolders"] == ["progetti"]
        await wiki.aclose()

    asyncio.run(scenario())


def test_documents_index_in_parallel_and_can_be_added_meanwhile(tmp_path):
    cfg = make_cfg(tmp_path)
    write_docs(cfg, "a", 12)

    async def scenario():
        wiki = Wiki(cfg)
        wiki.llm.delay = 0.2
        await wiki.indexer.start()
        await asyncio.sleep(0.3)  # indicizzazione in corso
        assert wiki.indexer.status()["busy"]
        write_docs(cfg, "b", 3)   # nuovi documenti a metà lavoro
        wiki.indexer.trigger()
        loop = asyncio.get_running_loop()
        started = loop.time()
        while wiki.indexer.status()["busy"] or wiki.indexer.status()["ready"] < 15:
            await asyncio.sleep(0.1)
            assert loop.time() - started < 20
        elapsed = loop.time() - started
        # 15 schede + nodi da 0,2 s l'una: in serie sarebbero oltre 4 s
        assert elapsed < 3.5
        assert wiki.tools.list_folder("")["subfolders"] == ["a", "b"]
        await wiki.indexer.stop()
        await wiki.aclose()

    asyncio.run(scenario())


def test_long_document_is_summarized_in_chunks(tmp_path):
    cfg = make_cfg(tmp_path, chunk_chars=2000)
    cfg.docs_dir.mkdir(parents=True, exist_ok=True)
    body = "\n".join(f"Riga {n}: il valore registrato è {n * 3}." for n in range(400))
    (cfg.docs_dir / "lungo.txt").write_text(body, encoding="utf-8")

    async def scenario():
        wiki = Wiki(cfg)
        status = await wiki.indexer.run_once()
        assert status["ready"] == 1
        assert wiki.llm.calls["chunk"] > 3 and wiki.llm.calls["doc"] == 1
        assert "Riga 399" in wiki.tools.read_document("lungo.txt", 400, 400)
        await wiki.aclose()

    asyncio.run(scenario())


def test_ask_returns_verified_citations(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg.docs_dir / "contratti").mkdir(parents=True)
    (cfg.docs_dir / "contratti" / "acme.md").write_text(CONTRACT, encoding="utf-8")

    async def scenario():
        wiki = Wiki(cfg)
        await wiki.indexer.run_once()
        answer = await wiki.ask("penale ritardo settimana")
        assert answer.citations and answer.verified
        assert all(c.status == VERIFIED for c in answer.citations)
        assert answer.citations[0].doc == "contratti/acme.md"
        assert "✓" in answer.render()

        # Citazione giusta: le righe dell'art. 9 sostengono la frase.
        good = await wiki.verify("contratti/acme.md", 7, 8,
                                 "prevista una penale del 2% per ogni settimana di ritardo")
        assert good.status == VERIFIED

        # Citazione sbagliata (l'esempio della slide): si cita l'art. 7, che parla d'altro.
        bad = await wiki.verify("contratti/acme.md", 3, 4,
                                "È prevista una penale del 5% per ogni settimana di ritardo")
        assert bad.status == WARNING and bad.confidence < cfg.verify.threshold

        # Righe leggermente sbagliate: il ricontrollo con più contesto la recupera.
        near = await wiki.verify("contratti/acme.md", 6, 6,
                                 "prevista una penale del 2% per ogni settimana di ritardo")
        assert near.status == RECHECKED

        missing = await wiki.verify("contratti/inesistente.md", 1, 2, "qualcosa")
        assert missing.status == WARNING
        await wiki.aclose()

    asyncio.run(scenario())


def test_paths_cannot_escape_the_wiki(tmp_path):
    for bad in ("../segreto.txt", "a/../../b", "C:/Windows/win.ini", "a\\..\\b"):
        with pytest.raises(ValueError):
            norm_path(bad)
    assert norm_path("\\contratti\\acme.md/") == "contratti/acme.md"


def test_server_upload_ask_and_auth(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.server.users = {"anna": "token-di-anna"}
    wiki = Wiki(cfg)
    auth = {"Authorization": "Bearer token-di-anna"}
    with TestClient(create_app(wiki)) as client:
        assert client.get("/").status_code == 200
        assert client.get("/api/status").status_code == 401
        assert client.get("/api/status", headers={"Authorization": "Bearer sbagliato"}).status_code == 401
        assert client.post("/mcp", json={}).status_code == 401

        response = client.post(
            "/api/upload", headers=auth, data={"folder": "contratti"},
            files=[("files", ("acme.md", CONTRACT.encode(), "text/markdown")),
                   ("files", ("virus.exe", b"x", "application/octet-stream"))],
        )
        assert response.json()["saved"] == ["contratti/acme.md"]
        assert response.json()["rejected"][0]["file"] == "virus.exe"
        assert client.post("/api/upload", headers=auth, data={"folder": "../fuori"},
                           files=[("files", ("a.md", b"x", "text/markdown"))]).status_code == 400

        for _ in range(100):
            status = client.get("/api/status", headers=auth).json()
            if status["ready"] == 1 and not status["busy"]:
                break
            import time
            time.sleep(0.1)
        assert status["ready"] == 1

        folder = client.get("/api/folder", params={"path": "contratti"}, headers=auth).json()
        assert folder["documents"][0]["doc"] == "contratti/acme.md"
        answer = client.post("/api/ask", headers=auth, json={"question": "penale ritardo"}).json()
        assert answer["citations"] and answer["warnings"] == 0
        assert client.get("/api/document", params={"doc": "nope.md"}, headers=auth).status_code == 404
    wiki.store.close()


def test_mcp_over_http_with_token(tmp_path):
    cfg = make_cfg(tmp_path)
    cfg.server.users = {"anna": "token-di-anna"}
    (cfg.docs_dir / "contratti").mkdir(parents=True)
    (cfg.docs_dir / "contratti" / "acme.md").write_text(CONTRACT, encoding="utf-8")
    wiki = Wiki(cfg)
    headers = {"Authorization": "Bearer token-di-anna",
               "Accept": "application/json, text/event-stream"}

    def rpc(client, method, params, request_id=1):
        response = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        assert response.status_code == 200, response.text
        return response.json()["result"]

    with TestClient(create_app(wiki), base_url="http://127.0.0.1:8765") as client:
        for _ in range(100):
            if client.get("/api/status", headers=headers).json()["ready"] == 1:
                break
            import time
            time.sleep(0.1)
        rpc(client, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
        names = {tool["name"] for tool in rpc(client, "tools/list", {}, 2)["tools"]}
        assert {"wiki_list_folder", "wiki_search", "wiki_read_document", "wiki_verify_citation",
                "wiki_ask"} <= names
        found = rpc(client, "tools/call", {"name": "wiki_search",
                                           "arguments": {"query": "penale ritardo"}}, 3)
        assert "contratti/acme.md" in found["content"][0]["text"]
        # un errore previsto arriva al modello con il suo messaggio, non come crash opaco
        wrong = rpc(client, "tools/call", {"name": "wiki_read_document",
                                           "arguments": {"doc": "contratti/acne.md"}}, 4)
        assert wrong["isError"] and "contratti/acme.md" in wrong["content"][0]["text"]
    wiki.store.close()
