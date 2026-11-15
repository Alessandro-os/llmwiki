"""Spazi, impostazioni dall'interfaccia, accessi e decision model."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import REAL_MODEL_DIR
from llmwiki import apphome, nli
from llmwiki.app import Hub, Wiki
from llmwiki.config import Config
from llmwiki.server import create_app
from llmwiki.verify import VERIFIED, WARNING

LOCAL = {"base_url": "http://127.0.0.1:8765", "client": ("127.0.0.1", 50000)}
NOTE = "# Carnot\n\nIl rendimento è η = 1 − T_f / T_c e dipende solo dalle due temperature.\n"


def mock_cfg(root) -> Config:
    return Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"}}, root)


def wait_ready(client, count):
    for _ in range(100):
        status = client.get("/api/status").json()
        if status["ready"] == count and not status["busy"]:
            return status
        time.sleep(0.1)
    raise AssertionError(status)


def test_config_roundtrip_keeps_users_and_paths(tmp_path):
    cfg = mock_cfg(tmp_path)
    cfg.server.users = {"anna": "tok-1"}
    cfg.llm.base_url = "http://127.0.0.1:8080/v1"
    cfg.verify.threshold = 0.55
    cfg.save()
    (tmp_path / "wiki.toml").write_text(
        "\ufeff" + (tmp_path / "wiki.toml").read_text(encoding="utf-8"), encoding="utf-8")  # con BOM
    again = Config.load(tmp_path / "wiki.toml")
    assert again.server.users == {"anna": "tok-1"}
    assert again.llm.provider == "mock" and again.llm.base_url == "http://127.0.0.1:8080/v1"
    assert again.verify.threshold == 0.55
    assert again.docs_dir == cfg.docs_dir and again.wiki_dir == cfg.wiki_dir


def test_spaces_settings_and_users_from_the_ui(tmp_path):
    registry = apphome.Registry()
    studio = registry.add("Studio", tmp_path / "Studio", template=mock_cfg(tmp_path))
    hub = Hub(Wiki(Config.load(tmp_path / "Studio" / "wiki.toml")), registry)
    with TestClient(create_app(hub), **LOCAL) as client:
        status = client.get("/api/status").json()
        assert status["local"] and status["space"] == studio["id"] and status["provider"] == "mock"

        # un secondo spazio eredita i modelli del primo e diventa quello attivo
        lavoro = client.post("/api/admin/spaces", json={"name": "Lavoro", "path": str(tmp_path / "Lavoro")}).json()
        assert client.get("/api/status").json()["space"] == lavoro["id"]
        client.post("/api/upload", data={"folder": ""}, files=[("files", ("carnot.md", NOTE.encode(), "text/markdown"))])
        wait_ready(client, 1)
        assert (tmp_path / "Lavoro" / "documenti" / "carnot.md").exists()

        # ogni spazio ha i suoi documenti
        client.post("/api/admin/spaces/switch", json={"id": studio["id"]})
        assert client.get("/api/status").json()["total"] == 0
        assert client.get("/api/search", params={"q": "rendimento"}).json()["results"] == []
        client.post("/api/admin/spaces/switch", json={"id": lavoro["id"]})
        assert client.get("/api/search", params={"q": "rendimento"}).json()["results"]

        # impostazioni: salvate nel wiki.toml dello spazio e applicate senza riavvio
        saved = client.post("/api/admin/settings", json={
            "verify": {"threshold": 0.7}, "index": {"concurrency": 3}}).json()
        assert saved["verify"]["threshold"] == 0.7
        assert Config.load(tmp_path / "Lavoro" / "wiki.toml").index.concurrency == 3
        assert hub.wiki.cfg.index.concurrency == 3
        assert wait_ready(client, 1)["ready"] == 1  # l'indice sopravvive al ricaricamento
        assert client.post("/api/admin/settings", json={"verify": {"threshold": 7}}).status_code == 400
        assert client.post("/api/admin/settings", json={"paths": {"docs": "C:/"}}).status_code == 400
        # niente rete senza utenti
        assert client.post("/api/admin/settings", json={"server": {"host": "0.0.0.0"}}).status_code == 400

        created = client.post("/api/admin/users", json={"name": "anna"}).json()
        assert len(created["token"]) > 20
        assert client.post("/api/admin/users", json={"name": "a b"}).status_code == 400
        assert client.post("/api/admin/settings", json={"server": {"host": "0.0.0.0"}}).status_code == 200
        client.delete("/api/admin/users/anna")
        assert Config.load(tmp_path / "Lavoro" / "wiki.toml").server.host == "127.0.0.1"

        # una pagina di un altro sito non può comandare l'app passando dal browser
        assert client.post("/api/admin/users", json={"name": "eve"},
                           headers={"Origin": "http://sito-malevolo.example"}).status_code == 403
    assert {s["name"] for s in apphome.Registry().spaces} == {"Studio", "Lavoro"}


def test_any_provider_can_be_configured_from_the_ui(tmp_path):
    cfg = mock_cfg(tmp_path)
    cfg.path = tmp_path / "wiki.toml"
    cfg.save()
    with TestClient(create_app(Wiki(cfg)), **LOCAL) as client:
        settings = client.get("/api/admin/settings").json()
        providers = {p["id"]: p for p in settings["providers"]}
        assert {"locale", "anthropic", "openai", "gemini", "openrouter", "altro"} <= set(providers)
        assert all(p["provider"] in ("anthropic", "openai") for p in providers.values())
        assert settings["keys"]["OPENAI_API_KEY"] is False

        # la chiave di un fornitore qualsiasi si salva fuori dallo spazio, e non torna mai indietro
        keys = client.post("/api/admin/secret", json={"name": "OPENROUTER_API_KEY", "value": "sk-finta"}).json()["keys"]
        assert keys["OPENROUTER_API_KEY"] is True and "sk-finta" not in str(keys)
        assert "sk-finta" not in (tmp_path / "wiki.toml").read_text(encoding="utf-8")
        assert client.post("/api/admin/secret", json={"name": "PATH", "value": "x"}).status_code == 400

        # elenco dei modelli del fornitore scelto nel modulo, prima ancora di salvare
        models = client.post("/api/admin/models", json={"provider": "mock", "base_url": "", "api_key_env": ""})
        assert models.json() == {"models": [{"id": "demo", "context": 0}]}
        assert client.post("/api/admin/models", json={"provider": "boh"}).status_code == 400

        saved = client.post("/api/admin/settings", json={"llm": {
            "provider": "openai", "base_url": "https://openrouter.ai/api/v1", "api_key_env": "OPENROUTER_API_KEY",
            "agent_model": "un/modello", "summary_model": "un/modello", "judge_model": "un/modello",
            "context_tokens": 8192, "tool_mode": "text"}}).json()
        assert saved["llm"]["api_key_env"] == "OPENROUTER_API_KEY" and saved["llm"]["context_tokens"] == 8192
        stored = Config.load(tmp_path / "wiki.toml").llm
        assert (stored.provider, stored.tool_mode, stored.context_tokens) == ("openai", "text", 8192)
        assert client.post("/api/admin/settings", json={"llm": {"tool_mode": "magia"}}).status_code == 400

        # la diagnosi dice in chiaro se il modello risponde: qui l'indirizzo non esiste
        report = client.post("/api/admin/settings", json={"llm": {"base_url": "http://127.0.0.1:9/v1"}})
        assert report.status_code == 200


def test_live_progress_history_and_follow_up(tmp_path):
    import json

    cfg = mock_cfg(tmp_path)
    cfg.server.users = {"anna": "token-di-anna"}
    cfg.path = tmp_path / "wiki.toml"
    cfg.save()
    wiki = Wiki(cfg)
    with TestClient(create_app(wiki), **LOCAL) as client:
        client.post("/api/upload", data={"folder": "fisica"},
                    files=[("files", ("carnot.md", NOTE.encode(), "text/markdown"))])
        wait_ready(client, 1)

        # la risposta arriva a eventi: i passi dell'agente, la verifica, poi la risposta
        with client.stream("POST", "/api/ask/stream", json={"question": "rendimento temperature"}) as response:
            events = [json.loads(line) for line in response.iter_lines() if line]
        kinds = [event["type"] for event in events]
        assert kinds[0] == "step" and events[0]["tool"] == "search"
        assert "verifying" in kinds and kinds[-1] == "answer"
        answer = events[-1]["answer"]
        assert answer["citations"] and answer["warnings"] == 0

        # la domanda resta nella cronologia di chi l'ha fatta, e solo nella sua
        items = client.get("/api/history").json()["items"]
        assert [item["question"] for item in items] == ["rendimento temperature"]
        assert items[0]["answer"]["citations"][0]["doc"] == "fisica/carnot.md"

        # approfondimento: gli scambi precedenti accompagnano la nuova domanda
        follow = client.post("/api/ask", json={
            "question": "e da cosa dipende il rendimento?",
            "history": [{"question": "rendimento temperature", "answer": answer["answer"]}]})
        assert follow.status_code == 200 and follow.json()["citations"]
        assert len(client.get("/api/history").json()["items"]) == 2
        assert client.delete("/api/history").json() == {"items": []}
        assert client.get("/api/history").json()["items"] == []
        assert client.post("/api/ask/stream", json={"question": "  "}).status_code == 400
    with TestClient(create_app(Wiki(Config.load(cfg.path))), base_url="http://192.168.1.20:8765",
                    client=("192.168.1.77", 50000)) as remote:
        auth = {"Authorization": "Bearer token-di-anna"}
        remote.post("/api/ask", json={"question": "rendimento"}, headers=auth)
        assert len(remote.get("/api/history", headers=auth).json()["items"]) == 1
    with TestClient(create_app(Wiki(Config.load(cfg.path))), **LOCAL) as client:
        assert client.get("/api/history").json()["items"] == []  # quella di anna non è la mia


def test_admin_is_local_only_and_remote_needs_token(tmp_path):
    cfg = mock_cfg(tmp_path)
    cfg.server.users = {"anna": "token-di-anna"}
    cfg.path = tmp_path / "wiki.toml"
    cfg.save()
    auth = {"Authorization": "Bearer token-di-anna"}
    # stesso server, visto da un altro computer della rete
    with TestClient(create_app(Wiki(cfg)), base_url="http://192.168.1.20:8765",
                    client=("192.168.1.77", 50000)) as remote:
        assert remote.get("/api/status").status_code == 401
        assert remote.get("/api/status", headers=auth).json()["local"] is False
        for path in ("/api/admin/settings", "/api/admin/spaces", "/api/admin/errors"):
            assert remote.get(path, headers=auth).status_code == 403
        assert remote.post("/api/admin/users", json={"name": "eve"}, headers=auth).status_code == 403
    # dal computer stesso, ma con un nome di host non locale (DNS rebinding): non vale come locale
    with TestClient(create_app(Wiki(Config.load(cfg.path))), base_url="http://sito-malevolo.example",
                    client=("127.0.0.1", 50000)) as rebound:
        assert rebound.get("/api/admin/settings").status_code == 403
        assert rebound.get("/api/status").status_code == 401


def test_secret_is_kept_outside_the_space(tmp_path, monkeypatch):
    from llmwiki.app import load_secrets, save_secret

    save_secret("ANTHROPIC_API_KEY", "chiave-finta")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    load_secrets()
    import os
    assert os.environ["ANTHROPIC_API_KEY"] == "chiave-finta"
    assert not list(tmp_path.rglob("secrets.json"))
    assert (apphome.home() / "secrets.json").exists()
    with pytest.raises(ValueError):
        save_secret("PATH", "x")


def test_reading_controls_and_reader_from_the_api(tmp_path):
    """Ferma e Riprendi dal computer dell'app; la scheda dice chi l'ha scritta e in quanto."""
    cfg = mock_cfg(tmp_path)
    cfg.docs_dir.mkdir(parents=True)
    (cfg.docs_dir / "carnot.md").write_text(NOTE, encoding="utf-8")
    with TestClient(create_app(Wiki(cfg)), **LOCAL) as client:
        wait_ready(client, 1)
        read = client.get("/api/summary", params={"doc": "carnot.md"}).json()["read"]
        assert read["model"] == "demo" and read["read_at"] > 0
        assert client.post("/api/admin/index/pause").json()["paused"] is True
        assert client.post("/api/admin/index/resume").json()["paused"] is False
    remote = {"base_url": "http://192.168.1.20:8765", "client": ("192.168.1.30", 50000)}
    with TestClient(create_app(Wiki(cfg)), **remote) as client:
        assert client.post("/api/admin/index/pause").status_code == 403


def test_second_launch_while_the_first_is_starting_does_not_fail(monkeypatch):
    """Installatore e doppio clic insieme: la seconda copia parte quando la prima non risponde
    ancora. Deve aspettarla e uscire senza errori, non contenderle la porta."""
    from llmwiki import desktop

    first = desktop._claim_instance()
    assert first is not None
    answers = iter([False, False, True])  # la prima copia risponde dopo un po'
    monkeypatch.setattr(desktop, "_alive", lambda port: next(answers, True))
    monkeypatch.setattr(desktop, "_setup_logging", lambda: None)
    monkeypatch.setattr(desktop, "_open_hub", lambda registry: pytest.fail("non deve aprire uno spazio"))
    assert desktop._main(["--no-window", "--no-tray"]) == 0
    assert desktop._claim_instance() is None  # finché la prima è aperta, il posto è suo
    first.close()
    again = desktop._claim_instance()
    assert again is not None
    again.close()


def test_unreadable_decision_model_does_not_block_the_app(tmp_path, monkeypatch):
    """Un modello che Windows non lascia leggere (WinError 448 su un collegamento di cartella,
    capitato davvero all'avvio dall'installatore) non deve impedire di aprire lo spazio: si
    verifica con il modello linguistico."""
    real_is_file = Path.is_file

    def is_file(self):
        if nli.NAME in self.parts:
            raise OSError(448, "punto di montaggio non attendibile", str(self))
        return real_is_file(self)

    monkeypatch.setattr(Path, "is_file", is_file)
    assert not nli.installed()

    async def scenario():
        hub = Hub(Wiki(Config.from_dict({"llm": {"provider": "mock"}}, tmp_path)))
        assert hub.wiki.agent.verifier.judge_name == "llm"
        assert hub.download.status()["status"] == "missing"
        await hub.wiki.aclose()

    asyncio.run(scenario())


@pytest.mark.skipif(not nli.installed(REAL_MODEL_DIR), reason="decision model non installato")
def test_decision_model_cascade(tmp_path):
    """Il modello NLI vero accetta la citazione giusta; quella sbagliata scende la cascata
    fino all'avviso."""
    cfg = Config.from_dict({"llm": {"provider": "mock"}, "verify": {"context_lines": 1}}, tmp_path)
    cfg.docs_dir.mkdir(parents=True)
    (cfg.docs_dir / "contratto.md").write_text(
        "# Contratto\n\n## Consegne\nLa consegna avviene entro 30 giorni dalla data dell'ordine.\n\n\n"
        "## Penali\nIn caso di ritardo è prevista una penale del 2% del valore dell'ordine per ogni "
        "settimana di ritardo.\n", encoding="utf-8")
    judge = nli.NliJudge(REAL_MODEL_DIR)

    async def scenario():
        wiki = Wiki(cfg, judge=judge)
        await wiki.indexer.run_once()
        assert wiki.agent.verifier.judge_name == "nli"
        good = await wiki.verify("contratto.md", 7, 7, "La penale per ritardo è del 2% del valore dell'ordine per ogni settimana.")
        assert good.status == VERIFIED and good.method == "nli" and good.confidence > 0.6
        bad = await wiki.verify("contratto.md", 4, 4, "È prevista una penale del 5% per ogni settimana di ritardo.")
        assert bad.status == WARNING and bad.method.startswith("nli+")
        await wiki.aclose()

    asyncio.run(scenario())
    # passaggi più lunghi di 512 token: finestre sovrapposte, basta che una sostenga la frase
    filler = "Questa clausola riguarda aspetti amministrativi generali del rapporto. " * 120
    assert judge.score("La penale è del 2% per ogni settimana di ritardo.",
                       filler + "La penale è del 2% del valore dell'ordine per ogni settimana di ritardo.") > 0.6
