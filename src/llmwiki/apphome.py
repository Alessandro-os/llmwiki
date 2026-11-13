"""Cartella dell'applicazione e registro degli spazi.

Tutto ciò che l'app scrive fuori dagli spazi sta in un posto solo:

  %LOCALAPPDATA%\\LLMWiki\\app.json     spazi conosciuti, spazio attivo, porta
  %LOCALAPPDATA%\\LLMWiki\\models\\      decision model
  %LOCALAPPDATA%\\LLMWiki\\logs\\        log dell'app desktop

Uno *spazio* è una cartella autonoma (Studio, Lavoro, Azienda...) con il suo wiki.toml, i suoi
documenti e il suo indice: si può copiare o spostare intera.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

from .config import Config

DOCS_NAME = "documenti"
INDEX_NAME = ".indice"


def home() -> Path:
    override = os.environ.get("LLMWIKI_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "LLMWiki"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "llmwiki"
    base.mkdir(parents=True, exist_ok=True)
    return base


def models_dir() -> Path:
    return home() / "models"


def logs_dir() -> Path:
    path = home() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_spaces_root() -> Path:
    if os.environ.get("LLMWIKI_HOME"):  # installazione portatile: tutto sotto la stessa cartella
        return home() / "spazi"
    documents = Path.home() / "Documents"
    return (documents if documents.is_dir() else Path.home()) / "LLMWiki"


class Registry:
    """Elenco degli spazi, salvato in app.json."""

    def __init__(self) -> None:
        self.path = home() / "app.json"
        self.data: dict = {"version": 1, "port": 8765, "active": "", "spaces": []}
        if self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError):
                pass  # registro illeggibile: si riparte da vuoto, gli spazi su disco restano intatti

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    @property
    def spaces(self) -> list[dict]:
        return self.data["spaces"]

    def get(self, space_id: str) -> dict | None:
        return next((s for s in self.spaces if s["id"] == space_id), None)

    def active(self) -> dict | None:
        return self.get(self.data.get("active", "")) or (self.spaces[0] if self.spaces else None)

    def set_active(self, space_id: str) -> dict:
        space = self.get(space_id)
        if space is None:
            raise ValueError(f"spazio inesistente: {space_id!r}")
        self.data["active"] = space_id
        self.save()
        return space

    def add(self, name: str, path: str | os.PathLike | None = None,
            template: Config | None = None) -> dict:
        """Crea uno spazio nuovo, oppure registra una cartella che contiene già un wiki.toml."""
        name = name.strip()
        if not name:
            raise ValueError("serve un nome per lo spazio")
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "spazio"
        space_id, n = slug, 2
        while self.get(space_id):
            space_id, n = f"{slug}-{n}", n + 1
        folder = Path(path).expanduser() if path else default_spaces_root() / _safe_folder(name)
        folder = folder.resolve()
        if any(Path(s["path"]) == folder for s in self.spaces):
            raise ValueError(f"la cartella {folder} è già uno spazio")
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / "wiki.toml").exists():
            cfg = Config.from_dict({"paths": {"docs": DOCS_NAME, "wiki": INDEX_NAME}}, folder)
            if template is not None:  # il nuovo spazio parte con gli stessi modelli di quello attuale
                cfg.llm, cfg.index, cfg.verify, cfg.agent = (
                    template.llm, template.index, template.verify, template.agent)
            cfg.path = folder / "wiki.toml"
            cfg.save()
        cfg = Config.load(folder / "wiki.toml")
        cfg.docs_dir.mkdir(parents=True, exist_ok=True)
        space = {"id": space_id, "name": name, "path": str(folder)}
        self.spaces.append(space)
        if not self.data.get("active"):
            self.data["active"] = space_id
        self.save()
        return space

    def remove(self, space_id: str) -> None:
        """Toglie lo spazio dall'elenco. La cartella con documenti e indice non viene toccata."""
        if self.get(space_id) is None:
            raise ValueError(f"spazio inesistente: {space_id!r}")
        self.data["spaces"] = [s for s in self.spaces if s["id"] != space_id]
        if self.data.get("active") == space_id:
            self.data["active"] = self.spaces[0]["id"] if self.spaces else ""
        self.save()


def _safe_folder(name: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", name).strip(" .")
    return cleaned or "Spazio"
