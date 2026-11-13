"""Server MCP: gli stessi strumenti di navigazione, esposti a qualunque client MCP.

Un modello esterno (Claude, oppure un modello locale/open source in LM Studio, Open WebUI,
ecc.) può navigare la wiki da solo con gli strumenti di lettura, spendendo i propri token, e
far verificare le proprie citazioni con `wiki_verify_citation`. In alternativa `wiki_ask`
delega tutto all'agente del server e restituisce la risposta già verificata.
"""

from __future__ import annotations

import functools
import inspect

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError

from .app import Hub
from .llm import LLMError
from .tools import ToolError


def _readable_errors(fn):
    """Gli errori previsti (percorso sbagliato, scheda non pronta, modello non raggiungibile)
    arrivano al modello con il loro messaggio, così può correggersi; il resto resta opaco."""
    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except (ToolError, LLMError) as exc:
                raise MCPToolError(str(exc)) from exc
    else:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                return fn(*args, **kwargs)
            except (ToolError, LLMError) as exc:
                raise MCPToolError(str(exc)) from exc
    return wrapper

INSTRUCTIONS = """\
Wiki documentale aziendale organizzata ad albero: ogni cartella ha una mappa, i documenti sono \
raggruppati in sintesi, ogni documento ha una scheda-riassunto e il testo originale con righe \
numerate. Non c'è un grafo precompilato: i collegamenti si seguono navigando.

Percorso tipico: wiki_list_folder("") per la mappa generale, poi wiki_read_node e \
wiki_read_summary per orientarsi, wiki_search per i termini precisi, wiki_read_document per \
leggere le righe originali prima di citarle, wiki_find_documents per seguire un riferimento a \
un altro documento. Cita sempre documento e righe; wiki_verify_citation controlla che le righe \
citate sostengano davvero l'affermazione. wiki_ask fa svolgere l'intera ricerca all'agente del \
server e ritorna una risposta con citazioni già verificate."""


def build_mcp(hub: Hub) -> MCPServer:
    """Gli strumenti leggono sempre `hub.wiki`: se l'app cambia spazio, MCP lo segue."""
    mcp = MCPServer("llmwiki", instructions=INSTRUCTIONS)

    @mcp.tool()
    @_readable_errors
    def wiki_list_folder(path: str = "") -> dict:
        """Mostra una cartella: mappa (riassunto del contenuto), sottocartelle, sintesi di
        gruppo e documenti. Path vuoto = radice della wiki."""
        return hub.wiki.tools.list_folder(path)

    @mcp.tool()
    @_readable_errors
    def wiki_read_node(node_id: str) -> dict:
        """Legge una sintesi di gruppo (id come 'contratti::L1-0002', da wiki_list_folder) e
        l'elenco degli elementi che riassume."""
        return hub.wiki.tools.read_node(node_id)

    @mcp.tool()
    @_readable_errors
    def wiki_read_summary(doc: str) -> str:
        """Legge la scheda-riassunto di un documento: sintesi, punti chiave con le righe,
        entità e riferimenti ad altri documenti."""
        return hub.wiki.tools.read_summary(doc)

    @mcp.tool()
    @_readable_errors
    def wiki_read_document(doc: str, start_line: int = 1, end_line: int = 0) -> str:
        """Legge il testo originale di un documento con righe numerate (max 400 righe per
        chiamata; end_line 0 = fin dove possibile). È la fonte da cui citare."""
        return hub.wiki.tools.read_document(doc, start_line, end_line)

    @mcp.tool()
    @_readable_errors
    def wiki_search(query: str, folder: str = "", limit: int = 10) -> dict:
        """Ricerca per parole chiave nel testo originale e nelle schede. Ritorna documento,
        righe ed estratto. Funziona anche sui documenti appena caricati."""
        return hub.wiki.tools.search(query, folder, limit)

    @mcp.tool()
    @_readable_errors
    def wiki_find_documents(name: str) -> dict:
        """Trova documenti per nome di file o titolo, anche approssimato: serve a seguire un
        riferimento trovato in un altro documento."""
        return hub.wiki.tools.find_documents(name)

    @mcp.tool()
    @_readable_errors
    async def wiki_verify_citation(doc: str, start_line: int, end_line: int, claim: str) -> dict:
        """Fact-checking di una citazione: controlla se le righe indicate del documento
        sostengono l'affermazione. Stato: verified, rechecked (confermata al secondo
        controllo) oppure warning (non confermata)."""
        hub.refresh_judge()
        citation = await hub.wiki.verify(doc, start_line, end_line, claim)
        return citation.to_dict()

    @mcp.tool()
    @_readable_errors
    async def wiki_ask(question: str, folder: str = "") -> str:
        """Fa cercare la risposta all'agente del server, che naviga la wiki e restituisce una
        risposta in markdown con citazioni verificate (✓ confermata, ⚠ non confermata)."""
        hub.refresh_judge()
        answer = await hub.wiki.ask(question, folder)
        return answer.render()

    @mcp.tool()
    @_readable_errors
    def wiki_status() -> dict:
        """Stato dell'indicizzazione: documenti pronti, in coda, in errore."""
        return hub.wiki.indexer.status()

    return mcp
