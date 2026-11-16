"""Configurazione di uno spazio: il file wiki.toml nella sua cartella.

I valori predefiniti e il significato di ogni impostazione stanno qui, in un posto solo: il
file su disco viene sempre scritto da `Config.save()`.
"""

from __future__ import annotations

import json
import logging
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

LOOPBACK = frozenset({"127.0.0.1", "localhost", "::1"})
SECTIONS = ("llm", "index", "ocr", "verify", "agent", "server")
# Una riga di spiegazione per sezione, scritta nel file per chi lo apre a mano.
NOTES = {
    "llm": "provider: anthropic | openai (qualunque server compatibile: Strata, Ollama, LM Studio) | mock",
    "index": "concurrency: richieste al modello in parallelo; fanout: elementi riassunti da ogni nodo",
    "ocr": "mode: auto | text (testo del PDF) | ocr; kind: minicpm | server (altro OCR) | tesseract",
    "verify": "judge: auto | nli | llm; threshold: confidenza minima per accettare una citazione",
    "agent": "max_steps: letture al massimo per domanda; explorers: sotto-agenti in parallelo",
    "server": "host 0.0.0.0 espone l'app in rete (serve almeno un utente in [server.users])",
}


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    agent_model: str = "claude-opus-5-5"      # naviga e risponde
    summary_model: str = "claude-opus-5-5"    # schede, sintesi e mappe (il grosso dei token)
    judge_model: str = "claude-haiku-5-5"     # sì/no sulle citazioni quando decide il modello linguistico
    base_url: str = "http://localhost:11434/v1"  # solo provider "openai"
    api_key_env: str = "OPENAI_API_KEY"          # solo provider "openai"
    agent_effort: str = "high"
    summary_effort: str = "medium"
    judge_effort: str = "low"
    # Solo provider "openai": manda *_effort al server come `reasoning_effort` (none, low,
    # medium, high). Con i modelli locali che "pensano": meno ragionamento, più velocità.
    send_reasoning_effort: bool = False
    # Come l'agente usa gli strumenti: "auto" prova le chiamate native del modello e passa da
    # solo a un protocollo testuale se non funzionano; "native" e "text" lo forzano.
    tool_mode: str = "auto"
    # Finestra di contesto del modello in token; 0 = non nota (nessun limite applicato).
    # Con i modelli locali piccoli evita di mandare più testo di quanto ne leggano.
    context_tokens: int = 0
    refusal_fallbacks: bool = True  # solo Claude: un rifiuto dei classificatori viene rilanciato lato server
    timeout: float = 600.0


@dataclass
class IndexConfig:
    concurrency: int = 8
    fanout: int = 8
    chunk_chars: int = 24000     # i documenti più lunghi vengono letti a pezzi, in parallelo
    watch_seconds: float = 20.0  # ogni quanto il server ricontrolla la cartella dei documenti


@dataclass
class OcrConfig:
    # Come leggere i PDF: "auto" prende il testo che il file contiene e, se non ce n'è (una
    # scansione, appunti a mano), passa all'OCR; "text" solo il testo del file; "ocr" sempre l'OCR.
    # Un documento può avere il suo modo (colonna `method` di state.db), che vince su questo.
    mode: str = "auto"
    # "minicpm": MiniCPM-OCR gestito dall'app (minicpm.py); "server": un altro OCR acceso su un
    # server con API OpenAI; "tesseract": Tesseract installato
    kind: str = "minicpm"
    llama_server: str = ""  # kind "minicpm": un llama-server.exe già installato, al posto di scaricarlo
    base_url: str = ""      # kind "server"
    model: str = ""         # kind "server"
    api_key_env: str = ""   # kind "server": variabile con la chiave, se il server la chiede
    path: str = ""          # kind "tesseract": percorso di tesseract.exe
    language: str = "ita+eng"  # kind "tesseract": lingue installate da usare
    dpi: int = 200          # risoluzione a cui le pagine diventano immagini


@dataclass
class VerifyConfig:
    enabled: bool = True
    # "auto": decision model NLI se installato, poi il modello linguistico sui casi dubbi;
    # "nli": solo NLI; "llm": solo modello linguistico (logprob se il server li espone)
    judge: str = "auto"
    threshold: float = 0.6
    context_lines: int = 20       # righe attorno alla citazione mostrate al ricontrollo
    max_passage_lines: int = 150  # una citazione più lunga viene tagliata


@dataclass
class AgentConfig:
    max_steps: int = 24
    explorers: int = 4
    explorer_steps: int = 12


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    # true: chi si collega dal computer stesso non ha bisogno di token e può amministrare.
    # Va messo a false se davanti al server c'è un reverse proxy sulla stessa macchina.
    trust_loopback: bool = True
    users: dict[str, str] = field(default_factory=dict)  # nome -> token personale


@dataclass
class Config:
    root: Path
    docs_dir: Path
    wiki_dir: Path
    llm: LLMConfig = field(default_factory=LLMConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    ocr: OcrConfig = field(default_factory=OcrConfig)
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    path: Path | None = None

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> Config:
        cfg_path = Path(path or "wiki.toml").resolve()
        if not cfg_path.exists():
            return cls.from_dict({}, cfg_path.parent)
        # utf-8-sig: Blocco note e PowerShell salvano spesso con il BOM in testa
        data = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))
        return cls.from_dict(data, cfg_path.parent, cfg_path)

    @classmethod
    def from_dict(cls, data: dict, root: Path, path: Path | None = None) -> Config:
        paths = data.get("paths", {})
        cfg = cls(
            root=root,
            docs_dir=(root / paths.get("docs", "data/docs")).resolve(),
            wiki_dir=(root / paths.get("wiki", "data/wiki")).resolve(),
            path=path,
        )
        for section in SECTIONS:
            target = getattr(cfg, section)
            known = {f.name for f in fields(target)}
            for key, value in data.get(section, {}).items():
                if key in known:
                    setattr(target, key, value)
                else:  # scritta da una versione più recente, o un refuso: si ignora, non si blocca
                    logging.getLogger("llmwiki.config").warning(
                        "wiki.toml: impostazione sconosciuta [%s].%s ignorata", section, key)
        return cfg

    def to_toml(self) -> str:
        def value(v) -> str:
            if isinstance(v, bool):
                return "true" if v else "false"
            if isinstance(v, (int, float)):
                return repr(v)
            return json.dumps(str(v), ensure_ascii=False)

        def relative(target: Path) -> str:
            try:
                return target.relative_to(self.root).as_posix()
            except ValueError:
                return target.as_posix()

        lines = ["# Impostazioni di questo spazio. Si modificano dall'app (scheda Impostazioni)",
                 "# oppure a mano; i percorsi sono relativi a questo file.", "",
                 "[paths]", f"docs = {value(relative(self.docs_dir))}",
                 f"wiki = {value(relative(self.wiki_dir))}"]
        for section in SECTIONS:
            target = getattr(self, section)
            lines += ["", f"# {NOTES[section]}", f"[{section}]"]
            lines += [f"{f.name} = {value(getattr(target, f.name))}"
                      for f in fields(target) if f.name != "users"]
        lines += ["", "# Un token per persona: nome = \"token\"", "[server.users]"]
        lines += [f"{json.dumps(name)} = {value(token)}" for name, token in self.server.users.items()]
        return "\n".join(lines) + "\n"

    def save(self) -> None:
        self.path = self.path or self.root / "wiki.toml"
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(self.to_toml(), encoding="utf-8")
        os.replace(tmp, self.path)
