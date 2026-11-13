"""Da file a righe di testo numerabili.

Tutto il resto del sistema ragiona per (documento, intervallo di righe): è quello che
l'agente legge, cita, e che il fact-checking va a riprendere.
"""

from __future__ import annotations

import textwrap
from html.parser import HTMLParser
from pathlib import Path

TEXT_EXT = {
    ".txt", ".md", ".markdown", ".rst", ".csv", ".tsv", ".json", ".xml",
    ".yaml", ".yml", ".log", ".ini", ".toml", ".tex",
}
SUPPORTED = TEXT_EXT | {".html", ".htm", ".pdf", ".docx"}
MAX_LINE = 240


class ExtractError(Exception):
    pass


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED


def extract_lines(path: Path) -> list[str]:
    ext = path.suffix.lower()
    if ext == ".pdf":
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
    if not any(line.strip() for line in lines):
        raise ExtractError("nessun testo estraibile (se è una scansione serve un OCR)")
    return lines


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeError:
            continue
    return data.decode("latin-1", errors="replace")


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    parts = []
    for number, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ""
        parts.append(f"=== Pagina {number} ===\n{text}")
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
