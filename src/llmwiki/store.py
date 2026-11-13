"""Archivio su disco: file markdown leggibili + un piccolo SQLite per stato e ricerca.

  docs/<percorso>                    documenti originali (la cartella condivisa)
  wiki/text/<percorso>.txt           testo estratto, una riga per riga citabile
  wiki/summaries/<percorso>.md       scheda-riassunto del documento
  wiki/tree/<cartella>/L1-0003.md    sintesi di un gruppo di schede (o di sintesi)
  wiki/tree/<cartella>/_map.md       mappa della cartella
  wiki/state.db                      stato dei documenti, nodi dell'albero, indice full-text
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from pathlib import Path, PurePosixPath

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs(
  path TEXT PRIMARY KEY,
  folder TEXT NOT NULL,
  seq INTEGER NOT NULL,
  sha TEXT NOT NULL,
  size INTEGER NOT NULL,
  mtime REAL NOT NULL,
  status TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  lines INTEGER NOT NULL DEFAULT 0,
  summary_sha TEXT NOT NULL DEFAULT '',
  error TEXT NOT NULL DEFAULT '',
  attempts INTEGER NOT NULL DEFAULT 0,
  updated REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS docs_folder ON docs(folder);
CREATE TABLE IF NOT EXISTS nodes(
  id TEXT PRIMARY KEY,
  folder TEXT NOT NULL,
  level INTEGER NOT NULL,
  idx INTEGER NOT NULL,
  children_hash TEXT NOT NULL,
  content_sha TEXT NOT NULL,
  children TEXT NOT NULL,
  updated REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS nodes_folder ON nodes(folder);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
  body, path UNINDEXED, kind UNINDEXED, start_line UNINDEXED, end_line UNINDEXED,
  tokenize='unicode61 remove_diacritics 2'
);
"""

FTS_CHUNK = 30
FTS_OVERLAP = 5
STOPWORDS = {
    "il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "di", "a", "da", "in", "con", "su",
    "per", "tra", "fra", "e", "o", "ma", "che", "chi", "cui", "non", "si", "del", "dello",
    "della", "dei", "degli", "delle", "al", "allo", "alla", "ai", "agli", "alle", "dal", "dalla",
    "nel", "nella", "nei", "nelle", "sul", "sulla", "ci", "sono", "è", "ha", "hanno", "come",
    "quale", "quali", "quanto", "quanti", "cosa", "the", "of", "and", "to", "is", "are", "what",
    "which", "for", "on", "with",
}


def sha_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def norm_path(path: str) -> str:
    """Percorso relativo in stile posix; rifiuta tutto ciò che potrebbe uscire dalla cartella."""
    cleaned = (path or "").replace("\\", "/").strip().strip("/")
    if cleaned in ("", "."):
        return ""
    if ":" in cleaned or "\x00" in cleaned:
        raise ValueError(f"percorso non valido: {path!r}")
    parts = PurePosixPath(cleaned).parts
    if any(part in ("..", ".") for part in parts):
        raise ValueError(f"percorso non valido: {path!r}")
    return "/".join(parts)


def folder_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


def node_id(folder: str, level: int, idx: int) -> str:
    return f"{folder}::L{level}-{idx:04d}"


def map_id(folder: str) -> str:
    return f"{folder}::map"


class Store:
    def __init__(self, docs_dir: Path, wiki_dir: Path) -> None:
        self.docs_dir = docs_dir
        self.wiki_dir = wiki_dir
        self.text_dir = wiki_dir / "text"
        self.summary_dir = wiki_dir / "summaries"
        self.tree_dir = wiki_dir / "tree"
        for directory in (docs_dir, self.text_dir, self.summary_dir, self.tree_dir):
            directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(wiki_dir / "state.db", check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        with self.lock:
            self.db.close()

    # ---------------------------------------------------------------- file

    def doc_file(self, path: str) -> Path:
        return self._inside(self.docs_dir, norm_path(path))

    def text_file(self, path: str) -> Path:
        return self._inside(self.text_dir, norm_path(path) + ".txt")

    def summary_file(self, path: str) -> Path:
        return self._inside(self.summary_dir, norm_path(path) + ".md")

    def node_file(self, nid: str) -> Path:
        folder, _, name = nid.rpartition("::")
        if not re.fullmatch(r"map|L\d+-\d+", name):
            raise ValueError(f"id di nodo non valido: {nid!r}")
        filename = "_map.md" if name == "map" else f"{name}.md"
        folder = norm_path(folder)
        return self._inside(self.tree_dir, f"{folder}/{filename}" if folder else filename)

    @staticmethod
    def _inside(base: Path, relative: str) -> Path:
        target = (base / relative).resolve()
        if not target.is_relative_to(base.resolve()):
            raise ValueError(f"percorso fuori dalla wiki: {relative!r}")
        return target

    @staticmethod
    def write_atomic(target: Path, text: str) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + f".{os.getpid()}.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)

    def read_lines(self, path: str) -> list[str]:
        return self.text_file(path).read_text(encoding="utf-8").split("\n")

    # ---------------------------------------------------------------- documenti

    def get_doc(self, path: str) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute("SELECT * FROM docs WHERE path=?", (path,)).fetchone()

    def all_docs(self) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute("SELECT * FROM docs ORDER BY path").fetchall()

    def docs_in(self, folder: str, ready_only: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM docs WHERE folder=?"
        if ready_only:
            sql += " AND status='ready'"
        with self.lock:
            return self.db.execute(sql + " ORDER BY seq", (folder,)).fetchall()

    def upsert_pending(self, path: str, sha: str, size: int, mtime: float) -> None:
        folder = folder_of(path)
        with self.lock:
            row = self.get_doc(path)
            if row is None:
                seq = self.db.execute(
                    "SELECT COALESCE(MAX(seq), -1) + 1 FROM docs WHERE folder=?", (folder,)
                ).fetchone()[0]
                self.db.execute(
                    "INSERT INTO docs(path, folder, seq, sha, size, mtime, status, updated)"
                    " VALUES(?,?,?,?,?,?, 'pending', ?)",
                    (path, folder, seq, sha, size, mtime, time.time()),
                )
            else:
                self.db.execute(
                    "UPDATE docs SET sha=?, size=?, mtime=?, status='pending', error='',"
                    " attempts=0, updated=? WHERE path=?",
                    (sha, size, mtime, time.time(), path),
                )

    def touch_doc(self, path: str, size: int, mtime: float) -> None:
        with self.lock:
            self.db.execute("UPDATE docs SET size=?, mtime=? WHERE path=?", (size, mtime, path))

    def set_status(self, path: str, status: str, error: str = "", bump: bool = False) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE docs SET status=?, error=?, attempts=attempts+?, updated=? WHERE path=?",
                (status, error[:500], 1 if bump else 0, time.time(), path),
            )

    def set_lines(self, path: str, count: int) -> None:
        with self.lock:
            self.db.execute("UPDATE docs SET lines=? WHERE path=?", (count, path))

    def set_ready(self, path: str, title: str, summary_sha: str) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE docs SET status='ready', error='', title=?, summary_sha=?, updated=?"
                " WHERE path=?",
                (title, summary_sha, time.time(), path),
            )

    def delete_doc(self, path: str) -> None:
        with self.lock:
            self.db.execute("DELETE FROM docs WHERE path=?", (path,))
            self.db.execute("DELETE FROM fts WHERE path=?", (path,))
        for target in (self.text_file(path), self.summary_file(path)):
            target.unlink(missing_ok=True)

    def reset_stuck(self) -> None:
        """Dopo un riavvio: ciò che era a metà torna in coda, gli errori hanno un'altra chance."""
        with self.lock:
            self.db.execute("UPDATE docs SET status='pending' WHERE status='indexing'")
            self.db.execute(
                "UPDATE docs SET status='pending' WHERE status='error' AND attempts < 3"
            )

    def counts(self) -> dict[str, int]:
        with self.lock:
            rows = self.db.execute("SELECT status, COUNT(*) AS n FROM docs GROUP BY status").fetchall()
            nodes = self.db.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        out = {"pending": 0, "indexing": 0, "ready": 0, "error": 0}
        out.update({row["status"]: row["n"] for row in rows})
        out["total"] = sum(out.values())
        out["nodes"] = nodes
        return out

    def folder_children(self, ready_only: bool = True) -> dict[str, set[str]]:
        """cartella -> sottocartelle dirette, ricavato dai documenti presenti."""
        sql = "SELECT DISTINCT folder FROM docs"
        if ready_only:
            sql += " WHERE status='ready'"
        with self.lock:
            folders = [row[0] for row in self.db.execute(sql).fetchall()]
        children: dict[str, set[str]] = {}
        for folder in folders:
            while folder:
                parent = folder_of(folder)
                children.setdefault(parent, set()).add(folder)
                folder = parent
        return children

    # ---------------------------------------------------------------- nodi dell'albero

    def get_node(self, nid: str) -> sqlite3.Row | None:
        with self.lock:
            return self.db.execute("SELECT * FROM nodes WHERE id=?", (nid,)).fetchone()

    def put_node(
        self, nid: str, folder: str, level: int, idx: int, children_hash: str, text: str,
        children: list[dict],
    ) -> str:
        content_sha = sha_text(text)
        self.write_atomic(self.node_file(nid), text)
        with self.lock:
            self.db.execute(
                "INSERT OR REPLACE INTO nodes(id, folder, level, idx, children_hash, content_sha,"
                " children, updated) VALUES(?,?,?,?,?,?,?,?)",
                (nid, folder, level, idx, children_hash, content_sha,
                 json.dumps(children, ensure_ascii=False), time.time()),
            )
        return content_sha

    def prune_nodes(self, folder: str, keep: set[str]) -> None:
        with self.lock:
            rows = self.db.execute("SELECT id FROM nodes WHERE folder=?", (folder,)).fetchall()
            stale = [row["id"] for row in rows if row["id"] not in keep]
            for nid in stale:
                self.db.execute("DELETE FROM nodes WHERE id=?", (nid,))
        for nid in stale:
            self.node_file(nid).unlink(missing_ok=True)

    def prune_folders(self, alive: set[str]) -> None:
        with self.lock:
            folders = [r[0] for r in self.db.execute("SELECT DISTINCT folder FROM nodes").fetchall()]
        for folder in folders:
            if folder not in alive:
                self.prune_nodes(folder, set())

    # ---------------------------------------------------------------- ricerca full-text

    def index_text(self, path: str, lines: list[str]) -> None:
        rows = []
        step = FTS_CHUNK - FTS_OVERLAP
        for start in range(0, max(len(lines), 1), step):
            chunk = lines[start : start + FTS_CHUNK]
            if any(line.strip() for line in chunk):
                rows.append(("\n".join(chunk), path, "text", start + 1, start + len(chunk)))
            if start + FTS_CHUNK >= len(lines):
                break
        self._replace_fts(path, "text", rows)

    def index_summary(self, path: str, summary: str) -> None:
        self._replace_fts(path, "summary", [(summary, path, "summary", 0, 0)])

    def _replace_fts(self, path: str, kind: str, rows: list[tuple]) -> None:
        with self.lock:
            self.db.execute("BEGIN")
            try:
                self.db.execute("DELETE FROM fts WHERE path=? AND kind=?", (path, kind))
                self.db.executemany(
                    "INSERT INTO fts(body, path, kind, start_line, end_line) VALUES(?,?,?,?,?)", rows
                )
                self.db.execute("COMMIT")
            except Exception:
                self.db.execute("ROLLBACK")
                raise

    @staticmethod
    def fts_query(query: str) -> str:
        terms = []
        for token in re.findall(r"\w+", query.lower()):
            if token in STOPWORDS or (len(token) < 3 and not token.isdigit()):
                continue
            if len(token) >= 5 and token.isalpha():
                # prefisso senza l'ultima lettera: penale/penali, fornitore/fornitori...
                terms.append(f'"{token[:-1]}"*')
            else:
                terms.append(f'"{token}"')
        return " OR ".join(dict.fromkeys(terms))

    def search(self, query: str, folder: str = "", limit: int = 10) -> list[dict]:
        match = self.fts_query(query)
        if not match:
            return []
        sql = (
            "SELECT path, kind, start_line, end_line,"
            " snippet(fts, 0, '«', '»', ' … ', 48) AS snippet, bm25(fts) AS rank"
            " FROM fts WHERE fts MATCH ?"
        )
        params: list = [match]
        if folder:
            prefix = folder + "/"
            sql += " AND substr(path, 1, ?) = ?"
            params += [len(prefix), prefix]
        sql += " ORDER BY rank LIMIT ?"
        params.append(max(1, min(int(limit), 50)))
        with self.lock:
            rows = self.db.execute(sql, params).fetchall()
        return [dict(row) for row in rows]
