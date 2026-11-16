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
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import prompts
from .config import Config
from .extract import ExtractError, NoTextError, extract_lines, is_supported, numbered
from .llm import LLM, LLMError
from .ocr import OcrError, make_ocr
from .store import Store, map_id, node_id, sha_file, sha_text

log = logging.getLogger("llmwiki.indexer")
TREE_INTERVAL = 600.0  # secondi
RETRY_SECONDS = 60.0   # attesa prima di riprovare quando il modello non risponde


@dataclass
class Item:
    """Un figlio di un nodo: scheda di documento, sintesi, o mappa di sottocartella."""

    kind: str  # "doc" | "node" | "map"
    ref: str   # percorso del documento oppure id del nodo
    sha: str
    title: str = ""

    def as_child(self) -> dict:
        return {"kind": self.kind, "ref": self.ref, "title": self.title}


@dataclass
class Progress:
    """Avanzamento di un documento in lettura. È indicativo: i passi previsti sono l'estrazione
    più le chiamate al modello note in quel momento (per un documento lungo si conoscono solo
    dopo averlo diviso in parti, e le condensazioni si aggiungono quando servono)."""

    model: str
    started: float = field(default_factory=time.monotonic)
    done: int = 0
    total: int = 2  # estrazione + una chiamata, finché non si sa di più
    ocr: str = ""     # l'OCR che legge le pagine, se il documento passa dall'OCR
    pages: int = 0    # pagine da leggere con l'OCR (ognuna è un passo)
    stopped: bool = False  # lettura interrotta: l'OCR, che gira in un thread, smette alla pagina dopo
    phase: str = "text"    # "text" mentre si legge il testo, "card" mentre il modello scrive la scheda

    engine: object = None  # l'OCR in uso: dice quanta parte della pagina corrente ha letto

    def percent(self) -> int:
        part = getattr(self.engine, "page_fraction", 0.0) if self.pages and self.done < self.pages else 0.0
        return min(99, round(100 * (self.done + part) / max(1, self.total)))

    def seconds(self) -> float:
        return time.monotonic() - self.started


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
        self.waiting = ""       # perché l'indicizzazione è ferma in attesa del modello
        self._resume_at = 0.0   # prima di questo istante non si avviano nuove schede
        self.paused = False     # fermata dall'utente: non parte nulla finché non riprende
        self.waiting_ocr = False  # l'attesa riguarda l'OCR, non il modello
        self.ocr = make_ocr(cfg.ocr)  # anche nel modo "text": un documento può chiedere l'OCR
        self.reading: dict[str, Progress] = {}
        self.last_done: dict = {}
        self._tree_task: asyncio.Task | None = None
        store.reset_stuck()

    @property
    def model_name(self) -> str:
        return "demo" if self.cfg.llm.provider == "mock" else self.cfg.llm.summary_model

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

    async def pause(self) -> None:
        """Ferma la lettura: le schede in corso si interrompono e i documenti tornano in coda,
        così come l'aggiornamento dell'albero. Vale finché l'app resta aperta."""
        self.paused = True
        running = [*self._tasks.values()]
        if self._tree_task and not self._tree_task.done():
            running.append(self._tree_task)
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)

    def resume(self) -> None:
        self.paused = False
        self._dirty.set()
        self.trigger()

    async def _watch_loop(self) -> None:
        while True:
            try:
                await self.scan()
            except Exception as exc:  # la sorveglianza non deve morire per un file illeggibile
                log.exception("scansione fallita")
                self.last_error = f"scansione: {exc}"
            # asyncio.timeout e non wait_for: in Python 3.11 wait_for perde la chiusura se arriva
            # nello stesso istante della richiesta di rilettura, e lo spazio non si chiude più.
            try:
                async with asyncio.timeout(self.cfg.index.watch_seconds):
                    await self._rescan.wait()
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
            while self.paused:
                await asyncio.sleep(1.0)
            self._dirty.clear()
            self._tree_task = asyncio.create_task(self.build_tree())
            try:
                await self._tree_task
            except asyncio.CancelledError:
                if not self.paused or asyncio.current_task().cancelling():
                    raise  # chiusura dell'app, non una pausa
                self._dirty.set()  # fermato dall'utente: si rifà alla ripresa
            except LLMError as exc:
                if not exc.unavailable:
                    log.exception("aggiornamento dell'albero fallito")
                    self.last_error = f"albero: {exc}"
                    continue
                self.waiting = str(exc)  # modello spento: si riprova più tardi, da dove si era
                await asyncio.sleep(RETRY_SECONDS)
                self._dirty.set()
            except Exception as exc:
                log.exception("aggiornamento dell'albero fallito")
                self.last_error = f"albero: {exc}"

    def status(self) -> dict:
        counts = self.store.counts()
        counts["building_tree"] = self.building
        counts["busy"] = bool(self._tasks) or self.building or self._dirty.is_set()
        counts["last_error"] = self.last_error
        counts["waiting"] = self.waiting
        counts["llm_calls"] = dict(self.llm.calls)
        counts["paused"] = self.paused
        counts["reader"] = self.model_name  # chi legge i documenti ("model" è chi risponde)
        counts["waiting_ocr"] = self.waiting_ocr
        counts["text_waiting"] = self.store.text_waiting()
        counts["reading"] = [
            {"path": path, "percent": p.percent(), "seconds": round(p.seconds()), "model": p.model,
             "ocr": p.ocr, "phase": p.phase, "page": min(p.done + 1, p.pages), "pages": p.pages}
            for path, p in list(self.reading.items())
        ]
        counts["last_done"] = self.last_done
        return counts

    # ---------------------------------------------------------------- scansione

    async def scan(self) -> None:
        changed, removed = await asyncio.to_thread(self._scan_fs)
        # Un file spostato o rinominato (stesso contenuto, percorso nuovo) si porta dietro
        # testo e scheda: riordinare le cartelle non costa chiamate al modello.
        gone = {row["sha"]: row["path"] for row in map(self.store.get_doc, removed)
                if row and row["status"] == "ready"}
        for path, sha, size, mtime in changed:
            old = gone.pop(sha, None)
            if old and self.store.get_doc(path) is None:
                self.store.move_doc(old, path, size, mtime)
                removed.remove(old)
                self._dirty.set()
            else:
                self.store.upsert_pending(path, sha, size, mtime)
        for path in removed:
            task = self._tasks.pop(path, None)
            if task:
                task.cancel()
            self.store.delete_doc(path)
        if removed:
            self._dirty.set()
        if self.paused or asyncio.get_running_loop().time() < self._resume_at:
            return  # fermata dall'utente, o il modello non rispondeva: si aspetta
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
            row = known.get(path)
            try:
                stat = file.stat()
                if row and row["size"] == stat.st_size and row["mtime"] == stat.st_mtime:
                    continue
                sha = sha_file(file)
            except OSError as exc:
                # in uso da un altro programma, o sparito a metà: si riprova al prossimo giro,
                # e intanto gli altri file si leggono lo stesso
                log.warning("file %s non leggibile ora: %s", path, exc)
                continue
            if row and row["sha"] == sha:
                self.store.touch_doc(path, stat.st_size, stat.st_mtime)
                continue
            changed.append((path, sha, stat.st_size, stat.st_mtime))
        return changed, [path for path in known if path not in seen]

    # ---------------------------------------------------------------- scheda del documento

    async def _call(self, system: str, prompt: str, kind: str, doc: str = "") -> str:
        async with self._llm_slots:
            text = await self.llm.complete(
                model=self.cfg.llm.summary_model, system=system, prompt=prompt,
                effort=self.cfg.llm.summary_effort, kind=kind,
            )
        if not text.strip():
            raise LLMError("il modello ha restituito un testo vuoto")
        self._step(doc)
        return text.strip()

    def _step(self, doc: str, more: int = 0) -> None:
        """Un passo fatto (o `more` passi in più previsti) nella lettura di `doc`."""
        progress = self.reading.get(doc)
        if progress:
            progress.total += more
            progress.done += 0 if more else 1

    async def _index_doc(self, path: str) -> None:
        async with self._doc_slots:
            self.reading[path] = progress = Progress(self.model_name)
            try:
                await self._read_doc(path, progress)
            except asyncio.CancelledError:
                # fermata dall'utente o chiusura dell'app: il documento torna in coda
                progress.stopped = True
                self.store.set_status(path, "pending")
                raise
            except OcrError as exc:
                if exc.unavailable:  # OCR spento o non collegato: si aspetta, come per il modello
                    log.warning("OCR non disponibile, %s resta in coda: %s", path, exc)
                    self.store.set_status(path, "pending")
                    self.waiting, self.waiting_ocr = str(exc), True
                    self._resume_at = asyncio.get_running_loop().time() + RETRY_SECONDS
                else:
                    log.warning("documento %s non letto dall'OCR: %s", path, exc)
                    self.store.set_status(path, "error", str(exc), bump=True)
            except LLMError as exc:
                if exc.unavailable:
                    # Il modello non risponde: il documento torna in coda e si riprova tra poco.
                    # Non è un errore del documento, e non deve restare segnato come tale.
                    log.warning("modello non raggiungibile, %s resta in coda: %s", path, exc)
                    self.store.set_status(path, "pending")
                    self.waiting, self.waiting_ocr = str(exc), False
                    self._resume_at = asyncio.get_running_loop().time() + RETRY_SECONDS
                else:
                    log.warning("documento %s non indicizzato: %s", path, exc)
                    self.store.set_status(path, "error", str(exc), bump=True)
            except (ExtractError, OSError, ValueError) as exc:
                log.warning("documento %s non indicizzato: %s", path, exc)
                self.store.set_status(path, "error", str(exc), bump=True)
            except Exception as exc:
                log.exception("errore inatteso su %s", path)
                self.store.set_status(path, "error", repr(exc), bump=True)
            finally:
                self.reading.pop(path, None)

    async def _read_doc(self, path: str, progress: Progress) -> None:
        row = self.store.get_doc(path)
        sha, method = row["sha"], row["method"]
        self.store.set_status(path, "indexing")
        how = method or self.cfg.ocr.mode
        lines = self._saved_text(path, row, how)
        if lines is None:
            lines = await self._extract(path, self.store.doc_file(path), progress)
            self.store.write_atomic(self.store.text_file(path), "\n".join(lines))
            # Da qui il documento è già cercabile e leggibile, anche senza scheda.
            await asyncio.to_thread(self.store.index_text, path, lines)
            self.store.set_text(path, len(lines), sha, how, progress.ocr)
        else:
            progress.ocr = row["ocr"]
        if not progress.pages:
            self._step(path)
        progress.phase = "card"
        body = await self._summarize(path, lines)
        row = self.store.get_doc(path)
        if row is None or row["sha"] != sha or row["method"] != method:
            # modificato o cancellato mentre il modello lo leggeva: questa scheda descrive un
            # testo che non c'è più. Lo stesso se nel frattempo è stato chiesto un altro modo di
            # lettura ("Rileggi con l'OCR"): il documento è già tornato in coda e si rilegge.
            if row is None:
                self.store.delete_doc(path)
            self._rescan.set()
            return
        summary = f"<!-- documento: {path} · righe: {len(lines)} -->\n{body}\n"
        self.store.write_atomic(self.store.summary_file(path), summary)
        await asyncio.to_thread(self.store.index_summary, path, body)
        seconds = progress.seconds()
        self.store.set_ready(path, title_of(body, path), sha_text(summary), progress.model, seconds,
                             progress.ocr)
        self.last_done = {"path": path, "seconds": round(seconds), "model": progress.model, "ocr": progress.ocr}
        if progress.ocr or not self.waiting_ocr:  # un file senza OCR non dice che l'OCR è tornato
            self.waiting, self.waiting_ocr = "", False
        self._dirty.set()

    def _saved_text(self, path: str, row, how: str) -> list[str] | None:
        """Il testo già letto in un tentativo precedente, se file e modo di lettura sono gli
        stessi: quando il modello non risponde il documento torna in coda, e senza questo a ogni
        tentativo si rileggeva il PDF da capo (con l'OCR, minuti di lavoro ogni volta)."""
        if not row["text_sha"] or row["text_sha"] != row["sha"] or row["text_method"] != how:
            return None
        try:
            return self.store.read_lines(path)
        except OSError:
            return None

    async def _extract(self, path: str, file: Path, progress: Progress) -> list[str]:
        """Il modo scelto per il documento vince su quello dello spazio. L'OCR legge solo i PDF:
        nel modo automatico solo quelli senza testo (scansioni, appunti a mano)."""
        row = self.store.get_doc(path)
        method = (row["method"] if row else "") or self.cfg.ocr.mode
        pdf = file.suffix.lower() == ".pdf"
        if pdf and method == "ocr":
            return await self._extract_ocr(file, progress)
        try:
            return await asyncio.to_thread(extract_lines, file)
        except NoTextError:
            if not pdf or method != "auto":
                raise
            return await self._extract_ocr(file, progress)

    async def _extract_ocr(self, file: Path, progress: Progress) -> list[str]:
        if self.ocr is None:
            raise OcrError("Nessun OCR collegato: Impostazioni → Lettura dei documenti",
                           unavailable=True)
        progress.ocr, progress.engine = self.ocr.name, self.ocr
        lines = await asyncio.to_thread(extract_lines, file, self.ocr,
                                        lambda done, total: self._on_page(progress, done, total))
        progress.ocr = self.ocr.name  # ora dice anche dove gira (scheda video o processore)
        return lines

    @staticmethod
    def _on_page(progress: Progress, done: int, total: int) -> None:
        """Ogni pagina letta dall'OCR è un passo. Chiamata dal thread dell'estrazione."""
        if progress.stopped:
            raise OcrError("lettura interrotta")
        if not progress.pages:
            progress.pages = total
            progress.total += total - 1  # l'estrazione contava come un passo solo
        progress.done = done
        if progress.engine:  # dopo la prima pagina il nome dice dove gira (scheda video o processore)
            progress.ocr = progress.engine.name

    async def _summarize(self, path: str, lines: list[str]) -> str:
        """Scrive la scheda. La quantità di testo per richiesta parte dall'impostazione, tiene
        conto della finestra del modello se è nota e, se il modello rifiuta comunque la
        richiesta, si dimezza: un modello con poco contesto legge a pezzi più piccoli."""
        limit = max(2000, self.cfg.index.chunk_chars)
        if self.cfg.llm.context_tokens:
            limit = max(2000, min(limit, self.cfg.llm.context_tokens * 2))
        while True:
            try:
                return await self._summarize_in(path, lines, limit)
            except LLMError as exc:
                if not exc.rejected or exc.status in (401, 403, 404) or limit <= 2000:
                    raise
                limit = max(2000, limit // 2)
                progress = self.reading.get(path)
                if progress:  # si ricomincia a pezzi più piccoli: anche il conto riparte
                    progress.done, progress.total = 1, 2

    async def _summarize_in(self, path: str, lines: list[str], limit: int) -> str:
        header = f"Documento: {path}\n\n"
        if sum(len(line) + 8 for line in lines) <= limit:
            return await self._call(prompts.DOC_SUMMARY, header + numbered(lines), "doc", path)

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

        self._step(path, more=len(chunks))  # una chiamata per parte, più quella finale
        notes = await asyncio.gather(*(
            self._call(
                prompts.CHUNK_NOTES,
                f"Documento: {path} · parte {n + 1} di {len(chunks)} · righe "
                f"{first + 1}-{first + len(part)}\n\n{numbered(part, first + 1)}",
                "chunk", path,
            )
            for n, (first, part) in enumerate(chunks)
        ))
        notes = await self._fit(list(notes), limit, path)
        joined = "\n\n".join(f"## Appunti parte {n + 1}\n{note}" for n, note in enumerate(notes))
        return await self._call(prompts.DOC_FROM_NOTES, header + joined, "doc", path)

    async def _fit(self, notes: list[str], limit: int, path: str = "") -> list[str]:
        """Se gli appunti non stanno in una richiesta, li condensa a gruppi (di nuovo in parallelo)."""
        while len(notes) > 1 and sum(len(note) for note in notes) > limit:
            groups = [notes[i : i + 4] for i in range(0, len(notes), 4)]
            self._step(path, more=sum(len(group) > 1 for group in groups))
            reduced = await asyncio.gather(*(
                self._call(prompts.REDUCE_NOTES, "\n\n---\n\n".join(group), "reduce", path)
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
