"""Aggiornamento dell'app dalle versioni pubblicate su GitHub.

All'avvio l'app desktop chiede a GitHub l'ultima versione pubblicata. Se è più nuova, nella
pagina principale compare il tasto Aggiorna: scarica l'installatore, ne controlla l'impronta
SHA-256 (GitHub la pubblica per ogni file), lo avvia in modo silenzioso e chiude l'app.
L'installatore cancella i file della versione vecchia, copia i nuovi e riapre l'app; al
riavvio l'app toglie l'installatore scaricato. Documenti, spazi, impostazioni e modelli non si
toccano. Senza rete, o se GitHub non risponde, il tasto semplicemente non compare.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from . import __version__, apphome
from .download import fetch_verified

log = logging.getLogger("llmwiki.update")
REPO = "Alessandro-os/llmwiki"
LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
INSTALLER = "LLMWiki-{version}-setup.exe"
SILENT = ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]


def parse_version(text: str) -> tuple[int, ...]:
    """'v0.10.2' -> (0, 10, 2). Una versione che non si legge vale () e non è mai più nuova."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", (text or "").strip())
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def updates_dir() -> Path:
    return apphome.home() / "aggiornamenti"


class Updater:
    def __init__(self, current: str = __version__, directory: Path | None = None,
                 client: Callable | None = None) -> None:
        self.current = current
        self.directory = directory or updates_dir()
        self._client = client  # per i test: crea un httpx.Client finto
        self.state = {"status": "none", "version": "", "done": 0, "total": 0, "error": ""}
        self._asset: dict = {}
        self._lock = threading.Lock()

    def status(self) -> dict:
        return dict(self.state, current=self.current)

    def _http(self):
        import httpx

        if self._client:
            return self._client()
        return httpx.Client(follow_redirects=True, timeout=httpx.Timeout(15.0, read=120.0),
                            headers={"User-Agent": "LLMWiki", "Accept": "application/vnd.github+json"})

    # ---------------------------------------------------------------- controllo

    def check(self) -> dict:
        """Chiede a GitHub l'ultima versione. Qualunque problema lascia lo stato a "none"."""
        try:
            with self._http() as http:
                response = http.get(LATEST)
                response.raise_for_status()
                release = response.json()
        except Exception as exc:  # rete assente, GitHub lento, repository non raggiungibile
            log.info("controllo degli aggiornamenti non riuscito: %s", exc)
            return self.status()
        version = str(release.get("tag_name", "")).lstrip("v")
        asset = next((a for a in release.get("assets", [])
                      if a.get("name") == INSTALLER.format(version=version)), None)
        digest = str((asset or {}).get("digest") or "")
        if parse_version(version) <= parse_version(self.current) or not digest.startswith("sha256:"):
            return self.status()  # niente di nuovo, o un file che non si può verificare
        self._asset = {"url": asset["browser_download_url"], "size": int(asset["size"]),
                       "sha256": digest.removeprefix("sha256:"), "name": asset["name"]}
        self.state.update(status="available", version=version, total=self._asset["size"])
        return self.status()

    def check_in_background(self) -> None:
        self.cleanup()
        threading.Thread(target=self.check, name="llmwiki-update-check", daemon=True).start()

    def cleanup(self) -> None:
        """Toglie gli installatori già usati: quelli di versioni non più nuove di questa."""
        if not self.directory.is_dir():
            return
        for file in self.directory.glob("LLMWiki-*-setup.exe*"):
            found = re.match(r"LLMWiki-(.+)-setup\.exe", file.name)
            if found and parse_version(found.group(1)) <= parse_version(self.current):
                file.unlink(missing_ok=True)

    # ---------------------------------------------------------------- scaricamento e installazione

    def start(self, quit_app: Callable[[], None]) -> None:
        """Scarica, controlla e installa, in sottofondo. L'app si chiude e l'installatore la riapre."""
        with self._lock:
            if self.state["status"] not in ("available", "error") or not self._asset:
                return
            self.state.update(status="downloading", done=0, error="")
        threading.Thread(target=self._run, args=(quit_app,), name="llmwiki-update", daemon=True).start()

    def _run(self, quit_app: Callable[[], None]) -> None:
        try:
            installer = self.download()
            self.state["status"] = "installing"
            self.launch(installer)
        except Exception as exc:
            log.warning("aggiornamento non riuscito: %s", exc)
            self.state.update(status="error", error=str(exc)[:300])
            return
        quit_app()

    def download(self) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / self._asset["name"]
        with self._http() as http:
            fetch_verified(http, self._asset["url"], target, self._asset["size"], self._asset["sha256"],
                           lambda done: self.state.__setitem__("done", done))
        self.state["done"] = self._asset["size"]
        return target

    @staticmethod
    def launch(installer: Path) -> None:
        if sys.platform != "win32":
            raise RuntimeError("l'aggiornamento automatico c'è solo su Windows")
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen([str(installer), *SILENT], creationflags=flags, close_fds=True)
