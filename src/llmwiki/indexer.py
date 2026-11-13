"""Indicizzazione: riassunti di riassunti, in parallelo.

Due attività indipendenti:

1. Ogni documento nuovo o modificato riceve la sua scheda. Un documento non dipende da nessun
   altro, quindi partono tutti insieme (fino a `index.concurrency`) e se ne possono aggiungere
   altri mentre il lavoro è in corso.
2. L'albero sopra le schede (sintesi di gruppo -> mappa della cartella -> mappa della cartella
   madre) si aggiorna rigenerando solo i nodi i cui figli sono cambiati: ogni nodo ricorda
   l'hash dei figli da cui è stato scritto.

I gruppi sono posizionali (numero d'ordine del documento nella cartella diviso `fanout`), quindi
aggiungere un documento tocca un solo nodo per livello e non rimescola gli altri.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from . import prompts
from .config import Config
from .extract import ExtractError, extract_lines, is_supported, numbered
from .llm import LLM, LLMError
from .store import Store, map_id, node_id, sha_file, sha_text

log = logging.getLogger("llmwiki.indexer")
TREE_INTERVAL = 600.0  # secondi


@dataclass
class Item:
    """Un figlio di un nodo: scheda di documento, sintesi, o mappa di sottocartella."""

    kind: str  # "doc" | "node" | "map"
    ref: str   # percorso del documento oppure id del nodo
    sha: str
    title: str = ""

    def as_child(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "title": self.title}


def title_of(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()[:160] or fallback
    return fallback


class Indexer:
    def __init__(self, cfg: Config, store: Store, llm: LLM) -> None:
        self.cfg, self.store, self.llm = cfg, store, llm
        self.fanout = max(2, cfg.index.fanout)
        self._llm_slots = asyncio.Semaphore(max(1, cfg.index.concurrency))
        self._doc_slots = asyncio.Semaphore(max(1, cfg.index.concurrency))
        self._tasks: dict[str, asyncio.Task] = {}
        self._dirty = asyncio.Event()
        self._rescan = asyncio.Event()
        self._background: list[asyncio.Task] = []
        self.building = False
        self.last_error = ""
        store.reset_stuck()

    # ---------------------------------------------------------------- ciclo di vita

    async def run_once(self) -> dict:
        """Indicizza tutto ciò che c'è da indicizzare e ritorna (uso da riga di comando)."""
        await self.scan()
        while self._tasks:
            await asyncio.gather(*list(self._tasks.values()), return_exceptions=True)
            await asyncio.sleep(0)
        self._dirty.clear()
        await self.build_tree()
        return self.status()

    async def start(self) -> None:
        """Avvia sorveglianza della cartella e aggiornamento dell'albero (uso dal server)."""
        self._dirty.set()
        self._background = [
            asyncio.create_task(self._watch_loop(), name="llmwiki-watch"),
            asyncio.create_task(self._tree_loop(), name="llmwiki-tree"),
        ]

    async def stop(self) -> None:
        for task in [*self._background, *self._tasks.values()]:
            task.cancel()
        await asyncio.gather(*self._background, *self._tasks.values(), return_exceptions=True)
        self._background.clear()

    def trigger(self) -> None:
        self._rescan.set()

    async def _watch_loop(self) -> None:
        while True:
            try:
                await self.scan()
            except Exception as exc:  # la sorveglianza non deve morire per un file illeggibile
                log.exception("scansione fallita")
                self.last_error = f"scansione: {exc}"
            try:
                await asyncio.wait_for(self._rescan.wait(), timeout=self.cfg.index.watch_seconds)
            except TimeoutError:
                pass
            self._rescan.clear()

    async def _tree_loop(self) -> None:
        while True:
            await self._dirty.wait()
            # Si aspetta che la coda delle schede si svuoti: con un modello lento le schede
            # arrivano una alla volta e rifare le mappe a ogni scheda raddoppierebbe il lavoro.
            # Su caricamenti molto grandi l'albero si aggiorna comunque ogni TREE_INTERVAL.
            waited = 0.0
            while self._tasks and waited < TREE_INTERVAL:
                await asyncio.sleep(1.0)
                waited += 1.0
            await asyncio.sleep(1.0)
            self._dirty.clear()
            try:
                await self.build_tree()
            except Exception as exc:
                log.exception("aggiornamento dell'albero fallito")
                self.last_error = f"albero: {exc}"

    def status(self) -> dict:
        counts = self.store.counts()
        counts["building_tree"] = self.building
        counts["busy"] = bool(self._tasks) or self.building or self._dirty.is_set()
        counts["last_error"] = self.last_error
        counts["llm_calls"] = dict(self.llm.calls)
        return counts

    # ---------------------------------------------------------------- scansione

    async def scan(self) -> None:
        changed, removed = await asyncio.to_thread(self._scan_fs)
        for path, sha, size, mtime in changed:
            self.store.upsert_pending(path, sha, size, mtime)
        for path in removed:
            task = self._tasks.pop(path, None)
            if task:
                task.cancel()
            self.store.delete_doc(path)
        if removed:
            self._dirty.set()
        for row in self.store.all_docs():
            if row["status"] == "pending" and row["path"] not in self._tasks:
                task = asyncio.create_task(self._index_doc(row["path"]))
                self._tasks[row["path"]] = task
                task.add_done_callback(lambda _t, p=row["path"]: self._tasks.pop(p, None))

    def _scan_fs(self) -> tuple[list[tuple], list[str]]:
        known = {row["path"]: row for row in self.store.all_docs()}
        seen: set[str] = set()
        changed: list[tuple] = []
        for file in self.store.docs_dir.rglob("*"):
            relative = file.relative_to(self.store.docs_dir)
            if not file.is_file() or not is_supported(file):
                continue
            if any(part.startswith((".", "~$")) for part in relative.parts):
                continue
            path = relative.as_posix()
            seen.add(path)
            stat = file.stat()
            row = known.get(path)
            if row and row["size"] == stat.st_size and row["mtime"] == stat.st_mtime:
                continue
            sha = sha_file(file)
            if row and row["sha"] == sha:
                self.store.touch_doc(path, stat.st_size, stat.st_mtime)
                continue
            changed.append((path, sha, stat.st_size, stat.st_mtime))
        return changed, [path for path in known if path not in seen]

    # ---------------------------------------------------------------- scheda del documento

    async def _call(self, system: str, prompt: str, kind: str) -> str:
        async with self._llm_slots:
            text = await self.llm.complete(
                model=self.cfg.llm.summary_model, system=system, prompt=prompt,
                effort=self.cfg.llm.summary_effort, kind=kind,
            )
        if not text.strip():
            raise LLMError("il modello ha restituito un testo vuoto")
        return text.strip()

    async def _index_doc(self, path: str) -> None:
        async with self._doc_slots:
            self.store.set_status(path, "indexing")
            try:
                lines = await asyncio.to_thread(extract_lines, self.store.doc_file(path))
                self.store.write_atomic(self.store.text_file(path), "\n".join(lines))
                self.store.set_lines(path, len(lines))
                # Da qui il documento è già cercabile e leggibile, anche senza scheda.
                await asyncio.to_thread(self.store.index_text, path, lines)
                body = await self._summarize(path, lines)
                summary = f"<!-- documento: {path} · righe: {len(lines)} -->\n{body}\n"
                self.store.write_atomic(self.store.summary_file(path), summary)
                await asyncio.to_thread(self.store.index_summary, path, body)
                self.store.set_ready(path, title_of(body, path), sha_text(summary))
                self._dirty.set()
            except asyncio.CancelledError:
                raise
            except (ExtractError, LLMError, OSError, ValueError) as exc:
                log.warning("documento %s non indicizzato: %s", path, exc)
                self.store.set_status(path, "error", str(exc), bump=True)
            except Exception as exc:
                log.exception("errore inatteso su %s", path)
                self.store.set_status(path, "error", repr(exc), bump=True)

    async def _summarize(self, path: str, lines: list[str]) -> str:
        limit = max(2000, self.cfg.index.chunk_chars)
        header = f"Documento: {path}\n\n"
        if sum(len(line) + 8 for line in lines) <= limit:
            return await self._call(prompts.DOC_SUMMARY, header + numbered(lines), "doc")

        # Documento lungo: appunti su ogni parte in parallelo, poi una scheda dagli appunti.
        chunks: list[tuple[int, list[str]]] = []
        start, size, current = 0, 0, []
        for index, line in enumerate(lines):
            if current and size + len(line) + 8 > limit:
                chunks.append((start, current))
                start, size, current = index, 0, []
            current.append(line)
            size += len(line) + 8
        if current:
            chunks.append((start, current))

        notes = await asyncio.gather(*(
            self._call(
                prompts.CHUNK_NOTES,
                f"Documento: {path} · parte {n + 1} di {len(chunks)} · righe "
                f"{first + 1}-{first + len(part)}\n\n{numbered(part, first + 1)}",
                "chunk",
            )
            for n, (first, part) in enumerate(chunks)
        ))
        notes = await self._fit(list(notes), limit)
        joined = "\n\n".join(f"## Appunti parte {n + 1}\n{note}" for n, note in enumerate(notes))
        return await self._call(prompts.DOC_FROM_NOTES, header + joined, "doc")

    async def _fit(self, notes: list[str], limit: int) -> list[str]:
        """Se gli appunti non stanno in una richiesta, li condensa a gruppi (di nuovo in parallelo)."""
        while len(notes) > 1 and sum(len(note) for note in notes) > limit:
            groups = [notes[i : i + 4] for i in range(0, len(notes), 4)]
            reduced = await asyncio.gather(*(
                self._call(prompts.REDUCE_NOTES, "\n\n---\n\n".join(group), "reduce")
                if len(group) > 1 else _passthrough(group[0])
                for group in groups
            ))
            if len(reduced) == len(notes):
                break
            notes = list(reduced)
        return notes

    # ---------------------------------------------------------------- albero

    async def build_tree(self) -> None:
        self.building = True
        try:
            children = self.store.folder_children(ready_only=True)
            alive: set[str] = set()
            await self._build_folder("", children, alive)
            self.store.prune_folders(alive)
        finally:
            self.building = False

    async def _build_folder(self, folder: str, children: dict[str, set[str]],
                            alive: set[str]) -> Item | None:
        subfolders = sorted(children.get(folder, ()))
        # Le sottocartelle sono rami indipendenti: si costruiscono in parallelo.
        sub_maps = await asyncio.gather(*(self._build_folder(s, children, alive) for s in subfolders))
        sub_items = [item for item in sub_maps if item]

        docs = self.store.docs_in(folder, ready_only=True)
        current = [(row["seq"], Item("doc", row["path"], row["summary_sha"], row["title"]))
                   for row in docs]
        keep: set[str] = set()
        level = 0
        while len(current) > self.fanout:
            level += 1
            groups: dict[int, list[Item]] = {}
            for index, item in current:
                groups.setdefault(index // self.fanout, []).append(item)
            ordered = sorted(groups.items())
            built = await asyncio.gather(*(
                self._build_node(folder, level, index, members) for index, members in ordered
            ))
            current = [(index, item) for (index, _), item in zip(ordered, built)]
            keep.update(item.ref for _, item in current if item.kind == "node")

        top = [item for _, item in current] + sub_items
        if not top:
            self.store.prune_nodes(folder, set())
            return None
        alive.add(folder)
        item = await self._build_map(folder, top, len(docs))
        keep.add(item.ref)
        self.store.prune_nodes(folder, keep)
        return item

    def _member_text(self, item: Item) -> str:
        if item.kind == "doc":
            label = f"documento `{item.ref}`"
            text = self.store.summary_file(item.ref).read_text(encoding="utf-8")
        else:
            label = ("mappa della sottocartella" if item.kind == "map" else "sintesi") + f" `{item.ref}`"
            text = self.store.node_file(item.ref).read_text(encoding="utf-8")
        return f"### {label}\n{text.strip()}"

    async def _write_node(self, nid: str, folder: str, level: int, index: int, system: str,
                          intro: str, members: list[Item], kind: str, title: str) -> Item:
        children_hash = sha_text("|".join(f"{m.kind}:{m.ref}:{m.sha}" for m in members))
        row = self.store.get_node(nid)
        if row and row["children_hash"] == children_hash and self.store.node_file(nid).exists():
            return Item(kind, nid, row["content_sha"], title)  # figli invariati: niente da rifare
        prompt = intro + "\n\n" + "\n\n".join(self._member_text(member) for member in members)
        text = await self._call(system, prompt, kind)
        content_sha = self.store.put_node(
            nid, folder, level, index, children_hash, text + "\n",
            [member.as_child() for member in members],
        )
        return Item(kind, nid, content_sha, title)

    async def _build_node(self, folder: str, level: int, index: int, members: list[Item]) -> Item:
        if len(members) == 1:
            return members[0]  # un gruppo con un solo elemento non ha bisogno di una sintesi
        nid = node_id(folder, level, index)
        return await self._write_node(
            nid, folder, level, index, prompts.NODE,
            f"Cartella: `{folder or '/'}` · sintesi `{nid}` · {len(members)} elementi", members,
            "node", f"Sintesi di {len(members)} elementi",
        )

    async def _build_map(self, folder: str, members: list[Item], doc_count: int) -> Item:
        nid = map_id(folder)
        return await self._write_node(
            nid, folder, -1, 0, prompts.FOLDER_MAP,
            f"Cartella: `{folder or '/'}` · {doc_count} documenti diretti · {len(members)} elementi",
            members, "map", f"Mappa di {folder or '/'}",
        )


async def _passthrough(value: str) -> str:
    return value
