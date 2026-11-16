"""MiniCPM-OCR gestito dall'app: si scarica con un clic, si accende quando serve, si spegne da solo.

Scelto il 16/11/2026 tra sei OCR su 12 pagine vere degli appunti (README, "Confronto degli OCR"):
è il migliore tra quelli che non inventano. Sullo stampato è alla pari con Unlimited OCR 2 (27
valori giusti su 32) ma 30 volte più veloce; a mano legge il 45% delle parole controllate a
strisce, contro il 35% di PaddleOCR-VL (che in più si incastra a ripetere) e l'1% di Tesseract.
Strata e gli altri modelli generici che vedono le immagini leggevano di più a mano, ma inventano
frasi e numeri: per un OCR che produce la fonte delle citazioni è il difetto peggiore.

Gira con llama-server (llama.cpp): sulla scheda video se c'è posto (2-3 s a pagina), altrimenti
sul processore (30-50 s a pagina), senza mai togliere memoria al modello che risponde. Le pagine
si leggono a strisce (`ocr.strips`). I file stanno in %LOCALAPPDATA%\\LLMWiki\\ocr\\minicpm-ocr.
"""

from __future__ import annotations

import logging
import os
import shutil
import socket
import subprocess
import threading
import time
import zipfile
from pathlib import Path

from . import apphome
from .download import fetch_verified
from .ocr import NO_WINDOW, Ocr, OcrError, ServerOcr, strips

log = logging.getLogger("llmwiki.minicpm")
NAME = "MiniCPM-OCR"
PROMPT = "Text Recognition:"  # istruzione ufficiale per il testo semplice
REPO, REVISION = "openbmb/MiniCPM-OCR-1.0-gguf", "0133ad8db635210441a55dcf421e25bfb9915142"
MODEL_FILES = {  # nome -> (dimensione in byte, sha256): GGUF ufficiali, Apache-2.0
    "MiniCPM-OCR-1_0-Q8_0.gguf": (811598432, "791486a476bdacb48acb3f31aa3a18dbb5be87e723a4074bcd13a37d61c852e2"),
    "mmproj-model-f16-4x.gguf": (901017536, "ceed82261b3b1380c3165f8b37c10117a50093be1362cbfeeb692fa036444682"),
}
# llama.cpp in versione Vulkan: usa la scheda video di qualunque marca senza le librerie CUDA
# (36 MB invece di 680) e senza scheda gira sul processore. Release b12364, ggml-org (MIT).
LLAMA_ZIP = ("https://github.com/ggml-org/llama.cpp/releases/download/b12364/llama-b12364-bin-win-vulkan-x64.zip",
             38097300, "949d2f245a588a876e9440a66f7fcebfc7b16d7ec7305d972e71dc157fd5d7b0")
TOTAL_BYTES = sum(size for size, _ in MODEL_FILES.values()) + LLAMA_ZIP[1]
GPU_FREE_MB = 3000   # sotto questa memoria libera nella scheda video si usa il processore
IDLE_SECONDS = 180   # spento dopo tre minuti senza pagine da leggere: la memoria torna libera
START_SECONDS = 120


def engine_dir() -> Path:
    return apphome.home() / "ocr" / "minicpm-ocr"


def server_path(directory: Path, configured: str = "") -> Path | None:
    """Il llama-server da usare: quello indicato in Impostazioni, oppure quello scaricato."""
    if configured and Path(configured).is_file():
        return Path(configured)
    found = sorted((directory / "programma").rglob("llama-server.exe")) if (directory / "programma").is_dir() else []
    return found[0] if found else None


def installed(directory: Path | None = None, configured: str = "") -> bool:
    directory = directory or engine_dir()
    try:
        files = all((directory / n).is_file() and (directory / n).stat().st_size == s
                    for n, (s, _) in MODEL_FILES.items())
    except OSError:
        return False
    return files and server_path(directory, configured) is not None


class Install:
    """Scaricamento del modello e di llama.cpp, riprendibile e con le impronte controllate."""

    def __init__(self, directory: Path | None = None, configured_server: str = "", client=None) -> None:
        self.directory = directory or engine_dir()
        self.configured_server = configured_server
        self._client = client  # per i test: crea un httpx.Client finto
        self.state = {"status": "ready" if installed(self.directory, configured_server) else "missing",
                      "done": 0, "total": TOTAL_BYTES, "error": ""}
        self._lock = threading.Lock()

    def status(self, configured_server: str | None = None) -> dict:
        """Rifà il controllo dei file a ogni richiesta (nelle Impostazioni può cambiare il
        llama-server indicato), tranne mentre sta scaricando."""
        if configured_server is not None:
            self.configured_server = configured_server
        if self.state["status"] != "downloading" and installed(self.directory, self.configured_server):
            self.state.update(status="ready", error="")
        elif self.state["status"] == "ready":
            self.state["status"] = "missing"
        return dict(self.state, name=NAME, path=str(self.directory))

    def start(self) -> None:
        with self._lock:
            if self.state["status"] in ("downloading", "ready"):
                return
            self.state.update(status="downloading", done=0, error="")
        threading.Thread(target=self._run, name="llmwiki-minicpm-download", daemon=True).start()

    def _run(self) -> None:
        import httpx

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            done = 0
            http_client = self._client() if self._client else httpx.Client(
                follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0))
            with http_client as http:
                for name, (size, sha) in MODEL_FILES.items():
                    target = self.directory / name
                    if not (target.is_file() and target.stat().st_size == size):
                        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{name}"
                        fetch_verified(http, url, target, size, sha,
                                       lambda n, base=done: self.state.__setitem__("done", base + n))
                    done += size
                if server_path(self.directory, self.configured_server) is None:
                    self._program(http, done)
            self.state.update(status="ready", done=TOTAL_BYTES)
        except Exception as exc:  # rete assente, disco pieno, file corrotto: lo stato lo racconta
            log.warning("scaricamento di MiniCPM-OCR non riuscito: %s", exc)
            self.state.update(status="error", error=str(exc)[:300])

    def _program(self, http, base: int) -> None:
        url, size, sha = LLAMA_ZIP
        archive = self.directory / "llama.cpp.zip"
        fetch_verified(http, url, archive, size, sha, lambda n: self.state.__setitem__("done", base + n))
        program = self.directory / "programma"
        shutil.rmtree(program, ignore_errors=True)
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(program)
        archive.unlink()


def free_gpu_mb() -> int | None:
    """Memoria libera della scheda video NVIDIA; None se non si sa (altre marche: si prova)."""
    try:
        done = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                              capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW)
        return int(done.stdout.split()[0]) if done.returncode == 0 and done.stdout.strip() else None
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class ManagedOcr(Ocr):
    """L'OCR che l'app accende da sola. `name` dice anche dove gira, per la scheda del documento."""

    def __init__(self, directory: Path | None = None, configured_server: str = "", dpi: int = 200) -> None:
        super().__init__(dpi)
        self.directory = directory or engine_dir()
        self.configured_server = configured_server
        self.name = NAME
        self._process: subprocess.Popen | None = None
        self._client: ServerOcr | None = None
        self._lock = threading.Lock()
        self._last_used = 0.0
        self._closed = threading.Event()
        threading.Thread(target=self._idle_watch, name="llmwiki-minicpm-idle", daemon=True).start()

    def read(self, png: bytes) -> str:
        client = self._ensure()
        texts, pieces = [], strips(png)
        for number, piece in enumerate(pieces):
            self._last_used = time.monotonic()  # a ogni striscia: lo spegnimento per inattività aspetta
            self.page_fraction = number / len(pieces)
            texts.append(client.read(piece))
        self._last_used, self.page_fraction = time.monotonic(), 0.0
        return "\n".join(texts)

    def close(self) -> None:
        self._closed.set()
        with self._lock:
            self._stop()

    # ---------------------------------------------------------------- avvio e spegnimento

    def _ensure(self) -> ServerOcr:
        with self._lock:
            if self._process and self._process.poll() is None and self._client:
                return self._client
            self._stop()
            program = server_path(self.directory, self.configured_server)
            if program is None or not installed(self.directory, self.configured_server):
                raise OcrError("MiniCPM-OCR non è scaricato: Impostazioni → Lettura dei documenti → Scarica",
                               unavailable=True)
            free = free_gpu_mb()
            tries = [("processore", self._cpu_args())]
            if free is None or free >= GPU_FREE_MB:  # c'è posto (o non si sa): prima la scheda video
                tries.insert(0, ("scheda video", ["-ngl", "99", "-fa", "on"]))
            for where, extra in tries:
                if self._start(program, extra):
                    self.name = f"{NAME} ({where})"
                    log.info("MiniCPM-OCR acceso sul %s", where)
                    return self._client
            raise OcrError("MiniCPM-OCR non si è acceso: i dettagli sono nel log", unavailable=True)

    @staticmethod
    def _cpu_args() -> list[str]:
        threads = max(2, (os.cpu_count() or 4) // 2)
        return ["-ngl", "0", "--no-mmproj-offload", "-t", str(threads)]

    def _start(self, program: Path, extra: list[str]) -> bool:
        import httpx

        port = _free_port()
        args = [str(program), "-m", str(self.directory / "MiniCPM-OCR-1_0-Q8_0.gguf"),
                "--mmproj", str(self.directory / "mmproj-model-f16-4x.gguf"), *extra,
                "-c", "8192", "--jinja", "--reasoning", "off", "--temp", "0",
                "--host", "127.0.0.1", "--port", str(port), "--alias", "minicpm-ocr"]
        log_file = (apphome.logs_dir() / "minicpm-ocr.log").open("ab")
        self._process = subprocess.Popen(args, stdout=log_file, stderr=log_file, creationflags=NO_WINDOW)
        deadline = time.monotonic() + START_SECONDS
        while time.monotonic() < deadline and self._process.poll() is None:
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=2).status_code == 200:
                    self._client = ServerOcr(f"http://127.0.0.1:{port}/v1", "minicpm-ocr", dpi=self.dpi,
                                             prompt=PROMPT)
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
                    log.info("MiniCPM-OCR spento: nessuna pagina da leggere")
                    self._stop()
