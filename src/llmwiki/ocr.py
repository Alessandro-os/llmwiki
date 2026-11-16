"""OCR: leggere le pagine come immagini, con qualunque OCR.

Come per i modelli, l'app non dipende da un OCR preciso. Due tipi, dietro la stessa interfaccia
(`Ocr.read`: immagine PNG -> testo):

- **server**: un modello che legge immagini, servito con l'API compatibile OpenAI. Per esempio
  Unlimited OCR o DeepSeek-OCR con SGLang o vLLM, oppure un modello con la vista su llama.cpp,
  Ollama, LM Studio. È la strada dei modelli grandi e precisi (formule, tabelle, scrittura a mano).
- **tesseract**: il programma Tesseract installato sul computer. Leggero, va anche senza scheda
  video, ma con le formule e la scrittura a mano rende molto meno.

Un OCR si considera funzionante solo se legge davvero un'immagine di prova (`probe`): un server
che risponde ma non vede le immagini, o un programma rotto, non viene proposto.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .config import OcrConfig
from .llm import strip_thinking

log = logging.getLogger("llmwiki.ocr")
TEST_TEXT = "CARNOT 1824"
PROMPT = ("Trascrivi tutto il testo di questa pagina, esattamente com'è e nell'ordine di lettura. "
          "Scrivi solo il testo trascritto, senza commenti. Le formule scrivile in LaTeX.")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # niente finestre nere su Windows


class OcrError(Exception):
    """`unavailable`: l'OCR non c'è in questo momento (spento, non collegato): il documento
    aspetta invece di finire in errore, come quando il modello è spento."""

    def __init__(self, message: str, unavailable: bool = False) -> None:
        super().__init__(message)
        self.unavailable = unavailable


class Ocr:
    name = "OCR"

    def __init__(self, dpi: int = 200) -> None:
        self.dpi = dpi

    def read(self, png: bytes) -> str:
        raise NotImplementedError

    def close(self) -> None:
        pass


class ServerOcr(Ocr):
    def __init__(self, base_url: str, model: str, api_key: str = "", dpi: int = 200,
                 timeout: float = 600.0, transport=None) -> None:
        import httpx

        super().__init__(dpi)
        self.name = model
        self.base_url, self.model = base_url.rstrip("/"), model
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._http = httpx.Client(timeout=timeout, headers=headers, transport=transport)

    def read(self, png: bytes) -> str:
        import httpx

        image = "data:image/png;base64," + base64.b64encode(png).decode("ascii")
        body = {"model": self.model, "temperature": 0, "max_tokens": 4096, "messages": [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": image}},
                                         {"type": "text", "text": PROMPT}]}]}
        try:
            response = self._http.post(self.base_url + "/chat/completions", json=body)
        except httpx.HTTPError as exc:
            raise OcrError(f"l'OCR su {self.base_url} non risponde ({exc.__class__.__name__})",
                           unavailable=True) from exc
        if response.status_code >= 500 or response.status_code in (408, 409, 429):
            raise OcrError(f"l'OCR su {self.base_url} è occupato o spento ({response.status_code})",
                           unavailable=True)
        if response.status_code >= 400:
            raise OcrError(f"l'OCR ha rifiutato la pagina ({response.status_code}): {response.text[:200]}")
        try:
            content = response.json()["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise OcrError("l'OCR ha risposto in un formato che non conosco") from exc
        return clean_text(strip_thinking(content))

    def close(self) -> None:
        self._http.close()


# Gli OCR "di layout" scrivono dove sta ogni blocco: Unlimited OCR `text[45, 79, 512, 133]Testo`,
# DeepSeek-OCR `<|ref|>text<|/ref|><|det|>[[45, 79, 512, 133]]<|/det|>`. Per citare serve solo
# il testo: con le coordinate la somiglianza al testo vero scendeva da 0,93 a 0,78 (misura 16/11).
# Unlimited OCR aggiunge anche segnali di struttura (`<PAGE><BLOCK>…<FORK>`), che vanno tolti
# prima delle coordinate: altrimenti `<BLOCK>text[…]` non comincia la riga e le coordinate restano.
_BOX_TAGS = re.compile(r"<\|ref\|>.*?<\|/ref\|>|<\|det\|>.*?<\|/det\|>|<(?:PAGE|BLOCK|FORK)>", re.S)
_BOX_PREFIX = re.compile(r"^[a-z_]+\[\d+(?:,\s*\d+){3}\]", re.M)


def clean_text(text: str) -> str:
    return _BOX_PREFIX.sub("", _BOX_TAGS.sub("", text)).strip()


class TesseractOcr(Ocr):
    def __init__(self, path: str, language: str = "ita+eng", dpi: int = 200) -> None:
        super().__init__(dpi)
        self.path, self.language = path, language
        self.name = f"Tesseract ({language})"

    def read(self, png: bytes) -> str:
        try:
            done = subprocess.run([self.path, "stdin", "stdout", "-l", self.language], input=png,
                                  capture_output=True, timeout=300, creationflags=NO_WINDOW)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise OcrError(f"Tesseract non parte ({exc}): cercalo di nuovo in Impostazioni → "
                           "Lettura dei documenti", unavailable=True) from exc
        if done.returncode != 0:
            raise OcrError("Tesseract non è riuscito a leggere la pagina: "
                           + done.stderr.decode("utf-8", "replace")[-300:])
        return done.stdout.decode("utf-8", "replace")


def make_ocr(cfg: OcrConfig) -> Ocr | None:
    """L'OCR collegato nelle impostazioni, o None se non ce n'è uno."""
    if cfg.kind == "server" and cfg.base_url and cfg.model:
        key = os.environ.get(cfg.api_key_env, "") if cfg.api_key_env else ""
        return ServerOcr(cfg.base_url, cfg.model, key, cfg.dpi)
    if cfg.kind == "tesseract" and cfg.path:
        return TesseractOcr(cfg.path, cfg.language, cfg.dpi)
    return None


# ---------------------------------------------------------------- prova e ricerca

def sample_image() -> bytes:
    """Un'immagine con una scritta nota: chi la legge, sa fare OCR."""
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (720, 180), "white")
    ImageDraw.Draw(image).text((40, 50), TEST_TEXT, fill="black", font=ImageFont.load_default(size=72))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def probe(ocr: Ocr) -> dict:
    """Legge l'immagine di prova: {ok, text, seconds, error}."""
    started = time.monotonic()
    try:
        text = ocr.read(sample_image())
    except OcrError as exc:
        return {"ok": False, "text": "", "seconds": round(time.monotonic() - started, 1), "error": str(exc)}
    seen = text.upper().replace(" ", "")
    ok = "CARNOT" in seen or "1824" in seen
    return {"ok": ok, "text": text.strip()[:200], "seconds": round(time.monotonic() - started, 1),
            "error": "" if ok else "risponde, ma non legge il testo dell'immagine di prova"}


def tesseract_places() -> list[str]:
    places = [shutil.which("tesseract") or ""]
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"),
                     os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
            if base:
                places.append(os.path.join(base, "Tesseract-OCR", "tesseract.exe"))
    seen: list[str] = []
    for place in places:
        if place and Path(place).is_file() and os.path.normcase(place) not in map(os.path.normcase, seen):
            seen.append(place)
    return seen


def tesseract_languages(path: str) -> list[str]:
    try:
        done = subprocess.run([path, "--list-langs"], capture_output=True, timeout=30, creationflags=NO_WINDOW)
    except (OSError, subprocess.TimeoutExpired):
        return []
    lines = done.stdout.decode("utf-8", "replace").splitlines()
    return [line.strip() for line in lines[1:] if line.strip()]


def find_tesseract() -> list[dict]:
    """Ogni Tesseract installato che legge davvero l'immagine di prova."""
    found = []
    for path in tesseract_places():
        languages = tesseract_languages(path)
        chosen = "+".join(code for code in ("ita", "eng") if code in languages)
        if not chosen:
            continue
        result = probe(TesseractOcr(path, chosen))
        note = "" if "ita" in languages else "manca la lingua italiana: le lettere accentate vengono peggio"
        found.append({"kind": "tesseract", "name": f"Tesseract ({chosen})", "path": path,
                      "language": chosen, "ok": result["ok"], "seconds": result["seconds"],
                      "note": note, "error": result["error"]})
    return found
