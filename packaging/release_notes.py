"""Scrive il testo della pagina di una versione su GitHub: come si installa, le novità "per chi
la usa" prese da CHANGELOG.md (unica fonte) e le impronte SHA-256 dei file. Lo usa
`.github/workflows/release.yml`.

  uv run python packaging/release_notes.py <versione> <file di uscita> <file da pubblicare>...
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
REPO = "https://github.com/Alessandro-os/llmwiki/blob/main"


def user_notes(changelog: str, version: str) -> str:
    """La parte "Per chi la usa" della versione indicata."""
    section = re.search(rf"^## {re.escape(version)} ·.*?\n(.*?)(?=^## |\Z)", changelog, re.S | re.M)
    if section is None:
        raise SystemExit(f"CHANGELOG.md non ha la versione {version}")
    notes = re.search(r"Per chi la usa:\n(.*?)(?=^Per chi sviluppa:|\Z)", section.group(1), re.S | re.M)
    return (notes.group(1) if notes else section.group(1)).strip()


def body(version: str, files: list[Path]) -> str:
    sums = "\n".join(f"{hashlib.sha256(file.read_bytes()).hexdigest()}  {file.name}" for file in files)
    return (f"Scaricate **LLMWiki-{version}-setup.exe** e apritelo. Chi ha già una versione precedente la "
            "installa sopra, oppure usa il tasto Aggiorna dentro l'app: documenti, spazi e impostazioni restano.\n\n"
            f"## Novità\n\n{user_notes((ROOT / 'CHANGELOG.md').read_text(encoding='utf-8'), version)}\n\n"
            f"Elenco completo: [CHANGELOG.md]({REPO}/CHANGELOG.md).\n\n## Impronte SHA-256\n\n```\n{sums}\n```\n")


def main() -> int:
    version, output, *files = sys.argv[1:]
    sys.path.insert(0, str(ROOT / "src"))
    from llmwiki import __version__

    if version != __version__:
        raise SystemExit(f"l'etichetta dice {version}, il codice {__version__}: non pubblico")
    Path(output).write_text(body(version, [Path(file) for file in files]), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
