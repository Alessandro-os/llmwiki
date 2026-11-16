"""OCR installati sul computer, che l'app accende da sola: qualunque modello GGUF che vede le
immagini (modello + parte visiva "mmproj"), fatto girare con llama-server di llama.cpp.

L'app non scarica niente. Cerca i file già presenti nelle cartelle consuete (LM Studio, Hugging
Face, la cartella dell'app) e in quelle aggiunte in Impostazioni, li riconosce con il catalogo
(`ocr_catalog.json`: istruzione giusta, lettura a strisce, per che cosa vanno bene) e li propone.
Un OCR che il catalogo non conosce funziona lo stesso, con le impostazioni generiche.

Il catalogo nasce dal confronto del 16/11/2026 su 12 pagine vere (README, "Confronto degli OCR"):
MiniCPM-OCR è il migliore tra gli OCR che non inventano. llama-server parte sulla scheda video se
ha almeno 3 GB liberi (2-3 s a pagina), altrimenti sul processore, senza togliere memoria al
modello che risponde, e si spegne dopo 3 minuti senza pagine da leggere.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from functools import cache
from pathlib import Path

from . import apphome
from .ocr import NO_WINDOW, Ocr, OcrError, ServerOcr

log = logging.getLogger("llmwiki.ocr_local")
GPU_FREE_MB = 3000   # sotto questa memoria libera nella scheda video si usa il processore
IDLE_SECONDS = 180   # spento dopo tre minuti senza pagine da leggere: la memoria torna libera
START_SECONDS = 120
MAX_DEPTH = 6        # quanto scendere nelle cartelle cercando i file


@cache
def catalog() -> dict:
    return json.loads((Path(__file__).with_name("ocr_catalog.json")).read_text(encoding="utf-8"))


def known(model_file: str) -> dict:
    """La voce del catalogo che riconosce questo file, o quella generica."""
    flat = re.sub(r"[-_ .]+", "-", Path(model_file).name.lower())
    for entry in catalog()["ocr"]:
        if any(hint in flat for hint in entry["files"]):
            return entry
    return {"id": "", "name": Path(model_file).stem, "recommended": False, **catalog()["generic"]}


# ---------------------------------------------------------------- ricerca sul computer

def default_folders() -> list[Path]:
    home = Path.home()
    local = Path(os.environ.get("LOCALAPPDATA") or home / "AppData" / "Local")
    return [apphome.home() / "ocr", home / ".lmstudio" / "models", home / ".cache" / "lm-studio" / "models",
            home / ".cache" / "huggingface" / "hub", local / "llama.cpp"]


def _walk(root: Path, pattern: str):
    """I file che corrispondono a `pattern`, senza scendere oltre MAX_DEPTH livelli."""
    if not root.is_dir():
        return
    base = len(root.parts)
    for folder, subfolders, files in os.walk(root, followlinks=True):
        if len(Path(folder).parts) - base >= MAX_DEPTH:
            subfolders[:] = []
        subfolders[:] = [s for s in subfolders if not s.startswith(".") or s in (".cache", ".lmstudio")]
        for name in files:
            if re.fullmatch(pattern, name, re.I):
                yield Path(folder) / name


def find_models(folders: list[Path]) -> list[dict]:
    """Coppie modello + parte visiva (mmproj) nella stessa cartella: un modello che vede le
    immagini. I file di bozza per l'accelerazione (draft, dspark) non sono modelli da usare."""
    found, seen = [], set()
    for root in folders:
        for mmproj in _walk(root, r".*mmproj.*\.gguf"):
            folder = mmproj.parent
            for model in sorted(folder.glob("*.gguf")):
                name = model.name.lower()
                if "mmproj" in name or "draft" in name or "dspark" in name or model in seen:
                    continue
                seen.add(model)
                entry = known(model.name)
                found.append({"kind": "local", "name": entry["name"], "model_path": str(model),
                              "mmproj_path": str(mmproj), "prompt": entry["prompt"], "strips": entry["strips"],
                              "recommended": entry.get("recommended", False), "good_for": entry["good_for"],
                              "known": bool(entry["id"]), "size_gb": round(model.stat().st_size / 1e9, 2)})
    return sorted(found, key=lambda item: (not item["recommended"], not item["known"], item["name"]))


def find_llama_servers(folders: list[Path]) -> list[str]:
    """llama-server.exe nel PATH, installato con winget, o nelle cartelle indicate."""
    places = [shutil.which("llama-server") or ""]
    winget = Path(os.environ.get("LOCALAPPDATA") or "") / "Microsoft" / "WinGet" / "Packages"
    places += [str(p) for p in winget.glob("ggml.llamacpp*/llama-server.exe")] if winget.is_dir() else []
    for root in folders:
        places += [str(p) for p in _walk(root, r"llama-server(\.exe)?")]
    unique: list[str] = []
    for place in places:
        if place and Path(place).is_file() and os.path.normcase(place) not in map(os.path.normcase, unique):
            unique.append(place)
    return unique


# ---------------------------------------------------------------- l'OCR acceso dall'app

def free_gpu_mb() -> int | None:
    """Memoria libera della scheda video NVIDIA; None se non si sa (altre marche: si prova)."""
    try:
        done = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        return int(done.stdout.split()[0]) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class LocalOcr(Ocr):
    """Un OCR GGUF acceso con llama-server quando serve. `name` dice anche dove gira."""

    def __init__(self, server: str, model: str, mmproj: str, prompt: str, parts: int = 0,
                 dpi: int = 200, label: str = "") -> None:
        super().__init__(dpi, parts)
        self.server, self.model, self.mmproj, self.prompt = server, model, mmproj, prompt
        self.label = label or known(model)["name"]
        self.name = self.label
        self._process: subprocess.Popen | None = None
        self._client: ServerOcr | None = None
        self._lock = threading.Lock()
        self._last_used = 0.0
        self._closed = threading.Event()
        threading.Thread(target=self._idle_watch, name="llmwiki-ocr-idle", daemon=True).start()

    def read_piece(self, png: bytes) -> str:
        client = self._ensure()
        self._last_used = time.monotonic()  # a ogni pezzo: lo spegnimento per inattività aspetta
        try:
            return client.read_piece(png)
        finally:
            self._last_used = time.monotonic()

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._stop()

    def _ensure(self) -> ServerOcr:
        with self._lock:
            if self._process and self._process.poll() is None and self._client:
                return self._client
            self._stop()
            missing = [p for p in (self.server, self.model, self.mmproj) if not Path(p).is_file()]
            if missing:
                raise OcrError(f"{self.label}: non trovo {missing[0]}. Impostazioni → Lettura dei documenti "
                               "→ Cerca gli OCR sul computer", unavailable=True)
            free = free_gpu_mb()
            tries = [("processore", ["-ngl", "0", "--no-mmproj-offload", "-t", str(max(2, (os.cpu_count() or 4) // 2))])]
            if free is None or free >= GPU_FREE_MB:  # c'è posto (o non si sa): prima la scheda video
                tries.insert(0, ("scheda video", ["-ngl", "99", "-fa", "on"]))
            for where, extra in tries:
                if self._start(extra):
                    self.name = f"{self.label} ({where})"
                    log.info("%s acceso sul %s", self.label, where)
                    return self._client
            raise OcrError(f"{self.label} non si è acceso: i dettagli sono in logs\\ocr.log", unavailable=True)

    def _start(self, extra: list[str]) -> bool:
        import httpx

        port = _free_port()
        args = [self.server, "-m", self.model, "--mmproj", self.mmproj, *extra, "-c", "8192",
                "--jinja", "--reasoning", "off", "--temp", "0", "--host", "127.0.0.1", "--port", str(port),
                "--alias", "ocr"]
        log_file = (apphome.logs_dir() / "ocr.log").open("ab")
        self._process = subprocess.Popen(args, stdout=log_file, stderr=log_file, creationflags=NO_WINDOW)
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline and self._process.poll() is None:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                    self._client = ServerOcr(f"http://127.0.0.1:{port}/v1", "ocr", dpi=self.dpi, prompt=self.prompt)
                    return True
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
        self._stop()
        return False

    def _stop(self) -> None:
        if self._client:
            self._client.close()
            self._client = None
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._process.kill()
        self._process = None

    def _idle_watch(self) -> None:
        while not self._closed.wait(15):
            with self._lock:
                if self._process and time.monotonic() - self._last_used > IDLE_SECONDS:
                    log.info("%s spento: nessuna pagina da leggere", self.label)
                    self._stop()
