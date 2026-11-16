"""Copia di sicurezza di uno spazio in un solo file zip, e ripristino.

Lo zip è a sua volta uno spazio completo (wiki.toml, `documenti`, `.indice`): ripristinare vuol
dire estrarlo in una cartella nuova e registrarla. Si copia anche l'indice, non solo i
documenti: rifarlo può costare ore di modello. Lo stato (`state.db`) si copia con la funzione
di SQLite fatta per questo, così la copia è coerente anche mentre l'app sta leggendo; le pagine
dell'OCR messe da parte e i file temporanei restano fuori.
"""

from __future__ import annotations

import sqlite3
import time
import zipfile
from dataclasses import replace
from pathlib import Path, PurePosixPath

from . import apphome
from .config import Config
from .store import Store

SKIP = ("state.db", "state.db-wal", "state.db-shm")


def backups_dir() -> Path:
    return apphome.default_spaces_root() / "Copie di sicurezza"


def create(cfg: Config, store: Store, name: str, folder: Path | None = None) -> Path:
    """Scrive `<nome>-<data>.zip` e ne restituisce il percorso."""
    folder = folder or backups_dir()
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{apphome.safe_folder(name)}-{time.strftime('%Y%m%d-%H%M%S')}.zip"
    partial = target.with_name(target.name + ".part")
    state = folder / (target.name + ".db")
    try:
        copy = sqlite3.connect(state)
        try:
            with store.lock:
                store.db.backup(copy)
        finally:
            copy.close()
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("wiki.toml", _portable(cfg).to_toml())
            _add_tree(archive, cfg.docs_dir, apphome.DOCS_NAME)
            _add_tree(archive, cfg.wiki_dir, apphome.INDEX_NAME, skip_top="pages")
            archive.write(state, f"{apphome.INDEX_NAME}/state.db")
        partial.replace(target)
    finally:
        state.unlink(missing_ok=True)
        partial.unlink(missing_ok=True)
    return target


def _portable(cfg: Config) -> Config:
    """Le stesse impostazioni, con le cartelle ai nomi consueti dentro lo zip."""
    root = cfg.root
    return replace(cfg, docs_dir=root / apphome.DOCS_NAME, wiki_dir=root / apphome.INDEX_NAME)


def _add_tree(archive: zipfile.ZipFile, base: Path, prefix: str, skip_top: str = "") -> None:
    for file in sorted(base.rglob("*")):
        relative = file.relative_to(base)
        if not file.is_file() or relative.parts[0] == skip_top or file.name in SKIP \
                or file.suffix in (".tmp", ".upload", ".part"):
            continue
        try:
            archive.write(file, f"{prefix}/{relative.as_posix()}")
        except OSError:  # tolto o bloccato proprio adesso: la copia va avanti con il resto
            continue


def restore(archive_path: Path, target: Path) -> Path:
    """Estrae la copia in `target`, che non deve esistere già: non si sovrascrive mai uno spazio."""
    if not archive_path.is_file():
        raise ValueError(f"non trovo il file {archive_path}")
    if target.exists():
        raise ValueError(f"la cartella {target} esiste già: scegli un altro nome")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            names = archive.namelist()
            if "wiki.toml" not in names:
                raise ValueError("questo zip non è una copia di sicurezza di LLMWiki")
            for name in names:
                parts = PurePosixPath(name).parts
                if name.startswith(("/", "\\")) or ".." in parts or ":" in name:
                    raise ValueError(f"lo zip contiene un percorso non valido: {name!r}")
            target.mkdir(parents=True)
            archive.extractall(target)
    except zipfile.BadZipFile as exc:
        raise ValueError("il file non è uno zip leggibile") from exc
    return target
