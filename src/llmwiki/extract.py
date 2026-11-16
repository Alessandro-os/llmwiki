"""Da file a righe di testo numerabili.

Tutto il resto del sistema ragiona per (documento, intervallo di righe): è quello che
l'agente legge, cita, e che il fact-checking va a riprendere.
"""

from __future__ import annotations

import io
import logging
import textwrap
from html.parser import HTMLParser
from pathlib import Path

TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".xml",
    ".yaml", ".yml", ".log", ".ini", ".toml", ".tex",
}
SUPPORTED = TEXT_EXT | {".html", ".htm", ".pdf", ".docx"}
MAX_LINE = 240
# pypdf avvisa a ogni lettura di PDF un po' irregolari ("wrong pointing object", "fontTools is
# required…"): il testo esce lo stesso e il registro dell'app si riempiva di righe inutili.
logging.getLogger("pypdf").setLevel(logging.ERROR)


class ExtractError(Exception):
    pass


class NoTextError(ExtractError):
    """Il file non contiene testo (una scansione, appunti a mano): nel modo automatico si passa all'OCR."""


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


NO_TEXT = ("nessun testo estraibile: se è una scansione o sono appunti scritti a mano, scegli "
           "l'OCR in Impostazioni → Lettura dei documenti")


class PageCache:
    """Le pagine già lette dall'OCR, una per file. Se l'OCR si spegne a pagina 80 di 100 (o
    l'app viene chiusa), alla ripresa si riparte da lì: a 30-50 secondi a pagina sul processore,
    ricominciare da capo voleva dire rifare un'ora di lavoro."""

    def __init__(self, folder: Path) -> None:
        self.folder, self.hits = folder, 0  # hits: pagine ritrovate già lette (per la stima del tempo)

    def get(self, number: int) -> str | None:
        try:
            text = (self.folder / f"{number:05d}.txt").read_text(encoding="utf-8")
        except OSError:
            return None
        self.hits += 1
        return text

    def put(self, number: int, text: str) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        tmp = self.folder / f"{number:05d}.tmp"
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(self.folder / f"{number:05d}.txt")


def extract_lines(path: Path, ocr=None, on_page=None, pages: PageCache | None = None) -> list[str]:
    """Con `ocr` (un `ocr.Ocr`) le pagine dei PDF si leggono come immagini; `on_page(fatte,
    totali)` segue l'avanzamento pagina per pagina; `pages` ricorda le pagine già lette."""
    ext = path.suffix.lower()
    if ext == ".pdf" and ocr is not None:
        raw = _pdf_ocr(path, ocr, on_page or (lambda done, total: None), pages)
    elif ext == ".pdf":
        raw = _pdf(path)
    elif ext == ".docx":
        raw = _docx(path)
    elif ext in (".html", ".htm"):
        raw = _html(_read_text(path))
    elif ext in TEXT_EXT:
        raw = _read_text(path)
    else:
        raise ExtractError(f"formato non supportato: {ext}")
    lines = _normalize(raw)
    if not any(line.strip() and not line.startswith("=== Pagina") for line in lines):
        raise NoTextError(NO_TEXT)
    return lines


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    # UTF-16 solo se c'è il BOM: senza, quasi qualunque sequenza di byte "si decodifica"
    # in UTF-16 e un file Windows-1252 diventerebbe una fila di ideogrammi.
    encodings = ["utf-16"] if data[:2] in (b"\xff\xfe", b"\xfe\xff") else []
    for enc in [*encodings, "utf-8-sig", "cp1252"]:
        try:
            return data.decode(enc)
        except UnicodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts, has_text = [], False
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        has_text = has_text or bool(text.strip())
        parts.append(f"=== Pagina {number} ===\n{text}")
    if not has_text:  # solo immagini: senza questo controllo resterebbero i soli numeri di pagina
        raise NoTextError(NO_TEXT)
    return "\n\n".join(parts)


def _pdf_ocr(path: Path, ocr, on_page, pages: PageCache | None = None) -> str:
    """Ogni pagina diventa un'immagine (pypdfium2: pypdf sa leggere il testo ma non disegnare le
    pagine) e l'OCR ne legge il testo. Una pagina alla volta: poca memoria anche con libri lunghi."""
    import pypdfium2

    document = pypdfium2.PdfDocument(str(path))
    try:
        total, parts = len(document), []
        on_page(0, total)  # il totale si sa subito: l'avanzamento può partire dalla prima pagina
        for number in range(total):
            text = pages.get(number) if pages else None
            if text is None:
                image = document[number].render(scale=ocr.dpi / 72).to_pil()
                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                text = ocr.read(buffer.getvalue())
                if pages:
                    pages.put(number, text)
            parts.append(f"=== Pagina {number + 1} ===\n{text}")
            on_page(number + 1, total)
    finally:
        document.close()
    return "\n\n".join(parts)


def _docx(path: Path) -> str:
    import docx

    document = docx.Document(str(path))
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text.strip() for cell in row.cells))
    return "\n".join(parts)


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
    SKIP = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.out: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.out.append(data)


def _html(text: str) -> str:
    parser = _HTMLText()
    parser.feed(text)
    return "".join(parser.out)


def _normalize(raw: str) -> list[str]:
    """Righe corte (così gli intervalli citati sono stretti) e senza muri di righe vuote."""
    lines: list[str] = []
    blank = 0
    for line in raw.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = line.rstrip().replace("\x00", "")
        if not line.strip():
            blank += 1
            if blank <= 1 and lines:
                lines.append("")
            continue
        blank = 0
        if len(line) > MAX_LINE:
            lines.extend(
                textwrap.wrap(line, width=MAX_LINE, break_long_words=False, break_on_hyphens=False)
                or [line]
            )
        else:
            lines.append(line)
    while lines and not lines[-1]:
        lines.pop()
    return lines


def numbered(lines: list[str], start: int = 1) -> str:
    """Formato mostrato ai modelli: `N| testo`."""
    return "\n".join(f"{start + i}| {line}" for i, line in enumerate(lines))
