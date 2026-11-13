"""Strumenti di navigazione della wiki.

Sono gli stessi per l'agente interno, per l'API REST e per il server MCP: qui il "grafo" non è
compilato in anticipo, lo percorre chi interroga, saltando da mappa a sintesi a scheda a
documento originale.
"""

from __future__ import annotations

import difflib
import json

from .extract import numbered
from .store import Store, map_id, norm_path

MAX_READ_LINES = 400
MAX_LISTED_DOCS = 60


class ToolError(Exception):
    """Errore da riportare al modello così com'è (percorso sbagliato, documento non pronto...)."""


class WikiTools:
    def __init__(self, store: Store) -> None:
        self.store = store

    # ---------------------------------------------------------------- navigazione

    def list_folder(self, path: str = "") -> dict:
        folder = self._path(path)
        all_children = self.store.folder_children(ready_only=False)
        docs = self.store.docs_in(folder)
        subfolders = sorted(all_children.get(folder, ()))
        if not docs and not subfolders and folder:
            raise ToolError(f"cartella inesistente o vuota: {folder!r}")

        node = self.store.get_node(map_id(folder))
        result: dict = {"folder": folder or "/"}
        if node:
            result["map"] = self.store.node_file(node["id"]).read_text(encoding="utf-8").strip()
            syntheses = [c["ref"] for c in json.loads(node["children"]) if c["kind"] == "node"]
            if syntheses:
                result["syntheses"] = syntheses
        else:
            result["map"] = "(mappa non ancora disponibile: indicizzazione in corso; usa search)"
        result["subfolders"] = subfolders

        ready = [row for row in docs if row["status"] == "ready"]
        listed = [{"doc": row["path"], "title": row["title"], "lines": row["lines"]}
                  for row in ready[:MAX_LISTED_DOCS]]
        result["documents"] = listed
        result["document_count"] = len(docs)
        if len(ready) > len(listed):
            result["note"] = (
                f"elencati {len(listed)} documenti su {len(ready)}: per gli altri apri le sintesi "
                "con read_node oppure usa search"
            )
        waiting = len(docs) - len(ready)
        if waiting:
            result["indexing"] = (
                f"{waiting} documenti di questa cartella non hanno ancora la scheda; "
                "il loro testo è già raggiungibile con search e read_document"
            )
        return result

    def read_node(self, node_id: str) -> dict:
        try:
            row = self.store.get_node((node_id or "").strip())
        except ValueError:
            row = None
        if row is None:
            raise ToolError(f"sintesi inesistente: {node_id!r} (gli id arrivano da list_folder)")
        return {
            "id": row["id"],
            "text": self.store.node_file(row["id"]).read_text(encoding="utf-8").strip(),
            "children": json.loads(row["children"]),
        }

    def read_summary(self, doc: str) -> str:
        path = self.resolve_doc(doc)
        row = self.store.get_doc(path)
        if row["status"] != "ready":
            raise ToolError(
                f"la scheda di {path!r} non è ancora pronta (stato: {row['status']}); "
                "puoi comunque leggere il testo con read_document"
            )
        return self.store.summary_file(path).read_text(encoding="utf-8").strip()

    def read_document(self, doc: str, start_line: int = 1, end_line: int = 0) -> str:
        path = self.resolve_doc(doc)
        lines = self._lines(path)
        total = len(lines)
        start = max(1, int(start_line or 1))
        end = int(end_line or 0) or min(total, start + MAX_READ_LINES - 1)
        end = min(end, total, start + MAX_READ_LINES - 1)
        if start > total:
            raise ToolError(f"{path!r} ha {total} righe; riga iniziale {start} fuori intervallo")
        header = f"[{path} · righe {start}-{end} di {total}]"
        return header + "\n" + numbered(lines[start - 1 : end], start)

    def search(self, query: str, folder: str = "", limit: int = 10) -> dict:
        hits = self.store.search(query or "", self._path(folder), limit or 10)
        results = [
            {
                "doc": hit["path"],
                "kind": "text" if hit["kind"] == "text" else "summary",
                "start_line": hit["start_line"],
                "end_line": hit["end_line"],
                "snippet": hit["snippet"],
            }
            for hit in hits
        ]
        out: dict = {"query": query, "results": results}
        if not results:
            out["note"] = "nessun risultato: prova sinonimi o termini più specifici"
        return out

    def find_documents(self, name: str, limit: int = 8) -> dict:
        """Trova documenti per nome o titolo: serve a seguire un riferimento ("allegato B")."""
        needle = (name or "").lower().strip()
        if not needle:
            raise ToolError("serve un nome da cercare")
        docs = self.store.all_docs()
        scored = []
        for row in docs:
            hay_path, hay_title = row["path"].lower(), row["title"].lower()
            if needle in hay_path or needle in hay_title:
                score = 1.0
            else:
                stem = hay_path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
                score = max(
                    difflib.SequenceMatcher(None, needle, stem).ratio(),
                    difflib.SequenceMatcher(None, needle, hay_title).ratio(),
                )
            if score >= 0.55:
                scored.append((score, row))
        scored.sort(key=lambda pair: -pair[0])
        return {
            "name": name,
            "documents": [
                {"doc": row["path"], "title": row["title"], "status": row["status"]}
                for _, row in scored[:limit]
            ],
        }

    # ---------------------------------------------------------------- supporto

    def passage(self, doc: str, start_line: int, end_line: int) -> tuple[str, int, int, list[str]]:
        """Righe citate, con l'intervallo riportato dentro il documento."""
        path = self.resolve_doc(doc)
        lines = self._lines(path)
        start = max(1, min(int(start_line), len(lines)))
        end = max(start, min(int(end_line), len(lines)))
        return path, start, end, lines

    def resolve_doc(self, doc: str) -> str:
        try:
            path = norm_path(doc)
        except ValueError as exc:
            raise ToolError(str(exc)) from exc
        if path and self.store.get_doc(path):
            return path
        # tolleranza sugli errori di battitura del modello: un solo candidato evidente
        candidates = [row["path"] for row in self.store.all_docs()]
        close = [c for c in candidates if c.lower() == path.lower() or c.endswith("/" + path)]
        if len(close) == 1:
            return close[0]
        near = difflib.get_close_matches(path, candidates, n=3, cutoff=0.6)
        hint = f" Forse: {', '.join(near)}" if near else ""
        raise ToolError(f"documento inesistente: {doc!r}.{hint}")

    def _lines(self, path: str) -> list[str]:
        try:
            return self.store.read_lines(path)
        except FileNotFoundError:
            row = self.store.get_doc(path)
            reason = row["error"] if row and row["error"] else "estrazione del testo in corso"
            raise ToolError(f"testo di {path!r} non disponibile: {reason}") from None

    @staticmethod
    def _path(path: str) -> str:
        try:
            return norm_path(path or "")
        except ValueError as exc:
            raise ToolError(str(exc)) from exc


# Descrizioni mostrate ai modelli (agente interno). I nomi coincidono con i metodi di WikiTools.
NAV_TOOLS: list[dict] = [
    {
        "name": "list_folder",
        "description": (
            "Mostra una cartella della wiki: la sua mappa (riassunto di tutto ciò che contiene), "
            "le sottocartelle, le sintesi di gruppo e i documenti. Usa path vuoto per la radice."
        ),
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Cartella, es. 'contratti/2025'. Vuoto = radice."}},
            "required": ["path"],
        },
    },
    {
        "name": "read_node",
        "description": (
            "Legge una sintesi di gruppo (id come 'contratti::L1-0002', ottenuto da list_folder "
            "o da un'altra sintesi) e l'elenco degli elementi che riassume."
        ),
        "parameters": {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
        },
    },
    {
        "name": "read_summary",
        "description": (
            "Legge la scheda-riassunto di un documento: sintesi, punti chiave con le righe, "
            "entità e riferimenti ad altri documenti."
        ),
        "parameters": {
            "type": "object",
            "properties": {"doc": {"type": "string", "description": "Percorso del documento."}},
            "required": ["doc"],
        },
    },
    {
        "name": "read_document",
        "description": (
            "Legge il testo originale di un documento con le righe numerate. Senza intervallo "
            f"parte dall'inizio; al massimo {MAX_READ_LINES} righe per chiamata. È la fonte da "
            "cui citare."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "doc": {"type": "string"},
                "start_line": {"type": "integer", "description": "Prima riga (da 1)."},
                "end_line": {"type": "integer", "description": "Ultima riga inclusa; 0 = fin dove possibile."},
            },
            "required": ["doc"],
        },
    },
    {
        "name": "search",
        "description": (
            "Ricerca per parole chiave nel testo originale e nelle schede di tutti i documenti "
            "(o di una cartella). Ritorna documento, righe e un estratto. Cerca parole, non "
            "frasi: usa i termini che ti aspetti di trovare nel testo."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "folder": {"type": "string", "description": "Limita a una cartella. Vuoto = tutta la wiki."},
                "limit": {"type": "integer", "description": "Numero massimo di risultati (default 10)."},
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_documents",
        "description": (
            "Trova documenti per nome di file o titolo, anche approssimato. Serve a seguire un "
            "riferimento incontrato in un altro documento (es. 'Allegato B', 'contratto quadro')."
        ),
        "parameters": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
    },
]

ANSWER_TOOL: dict = {
    "name": "answer",
    "description": (
        "Consegna la risposta finale. Nel testo ogni affermazione fattuale porta un marcatore "
        "[n]; per ogni n c'è una citazione con documento, righe e l'affermazione sostenuta."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "answer": {"type": "string", "description": "Risposta in markdown con marcatori [1], [2]..."},
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer", "description": "Il numero n del marcatore [n]."},
                        "doc": {"type": "string", "description": "Percorso del documento."},
                        "start_line": {"type": "integer"},
                        "end_line": {"type": "integer"},
                        "claim": {
                            "type": "string",
                            "description": "L'affermazione che queste righe sostengono, autosufficiente.",
                        },
                    },
                    "required": ["id", "doc", "start_line", "end_line", "claim"],
                },
            },
        },
        "required": ["answer", "citations"],
    },
}

DELEGATE_TOOL: dict = {
    "name": "delegate",
    "description": (
        "Lancia più esploratori in parallelo, ognuno con una sotto-domanda e una cartella di "
        "partenza. Ritorna per ciascuno ciò che ha trovato, con le citazioni. Utile per domande "
        "ampie che toccano aree diverse della wiki."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "tasks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string"},
                        "folder": {"type": "string", "description": "Cartella da cui partire. Vuoto = radice."},
                    },
                    "required": ["question"],
                },
            }
        },
        "required": ["tasks"],
    },
}
