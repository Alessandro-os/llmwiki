"""Aggiornamenti dell'app: GitHub finto, nessuna rete vera."""

from __future__ import annotations

import hashlib
import time

import httpx
import pytest

from llmwiki import update
from llmwiki.update import Updater, parse_version

INSTALLER = b"MZ installatore finto della 0.5.1"


def fake_github(tag="v0.5.1", digest=None, body=INSTALLER, fail=False):
    digest = digest if digest is not None else "sha256:" + hashlib.sha256(body).hexdigest()

    def handler(request: httpx.Request) -> httpx.Response:
        if fail:
            raise httpx.ConnectError("rete assente", request=request)
        if request.url.path.endswith("/releases/latest"):
            version = tag.lstrip("v")
            asset = {"name": f"LLMWiki-{version}-setup.exe", "size": len(body), "digest": digest,
                     "browser_download_url": f"https://github.com/x/releases/download/{tag}/LLMWiki-{version}-setup.exe"}
            return httpx.Response(200, json={"tag_name": tag, "assets": [asset]})
        return httpx.Response(200, content=body)

    return lambda: httpx.Client(transport=httpx.MockTransport(handler))


def test_versions_compare_as_numbers():
    assert parse_version("v0.10.0") > parse_version("0.9.9")
    assert parse_version("0.5.1") > parse_version("0.5") > parse_version("0.4.1")
    assert parse_version("prova") == () < parse_version("0.0.1")


def test_new_version_is_offered_only_when_newer_and_verifiable(tmp_path):
    found = Updater("0.5.0", tmp_path, fake_github()).check()
    assert found["status"] == "available" and found["version"] == "0.5.1"
    assert Updater("0.5.1", tmp_path, fake_github()).check()["status"] == "none"
    assert Updater("0.5.0", tmp_path, fake_github(digest="")).check()["status"] == "none"


def test_no_network_means_no_button(tmp_path):
    assert Updater("0.5.0", tmp_path, fake_github(fail=True)).check()["status"] == "none"


def test_update_downloads_verifies_installs_and_quits(tmp_path, monkeypatch):
    launched, quit_calls = [], []
    monkeypatch.setattr(Updater, "launch", staticmethod(launched.append))
    updater = Updater("0.5.0", tmp_path, fake_github())
    updater.check()
    updater.start(lambda: quit_calls.append(True))
    deadline = time.time() + 10
    while not quit_calls and time.time() < deadline:
        time.sleep(0.05)
    assert quit_calls and updater.status()["status"] == "installing"
    assert launched == [tmp_path / "LLMWiki-0.5.1-setup.exe"]
    assert launched[0].read_bytes() == INSTALLER


def test_corrupted_download_is_deleted_and_not_installed(tmp_path, monkeypatch):
    monkeypatch.setattr(Updater, "launch", staticmethod(lambda path: pytest.fail("non va installato")))
    updater = Updater("0.5.0", tmp_path, fake_github(digest="sha256:" + "0" * 64))
    updater.check()
    updater._run(lambda: pytest.fail("l'app non deve chiudersi"))
    assert updater.status()["status"] == "error"
    assert not list(tmp_path.glob("LLMWiki-*"))


def test_used_installers_are_removed_at_startup(tmp_path):
    for name in ("LLMWiki-0.4.1-setup.exe", "LLMWiki-0.5.0-setup.exe", "LLMWiki-0.5.1-setup.exe.part"):
        (tmp_path / name).write_bytes(b"x")
    Updater("0.5.0", tmp_path).cleanup()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["LLMWiki-0.5.1-setup.exe.part"]


def test_update_is_for_the_desktop_app_only(tmp_path):
    from fastapi.testclient import TestClient

    from llmwiki.app import Wiki
    from llmwiki.config import Config
    from llmwiki.server import create_app

    cfg = Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"}}, tmp_path)
    local = {"base_url": "http://127.0.0.1:8765", "client": ("127.0.0.1", 50000)}
    with TestClient(create_app(Wiki(cfg)), **local) as client:
        assert "update" not in client.get("/api/status").json()
        assert client.post("/api/admin/update").status_code == 400
    assert update.LATEST.endswith("/releases/latest")


def test_a_download_already_complete_is_checked_without_asking_again(tmp_path):
    """Scaricato tutto ma interrotto prima del controllo: chiedere "dal byte N in poi" a file
    finito dà 416 a ogni tentativo, e l'aggiornamento non partiva più."""
    from llmwiki.download import fetch_verified

    data = b"installatore" * 100
    target = tmp_path / "file.exe"
    (tmp_path / "file.exe.part").write_bytes(data)

    def handler(request):
        return httpx.Response(416)

    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        fetch_verified(http, "https://example.test/file.exe", target, len(data), hashlib.sha256(data).hexdigest())
    assert target.read_bytes() == data and not (tmp_path / "file.exe.part").exists()
