"""Configurazione: un file wiki.toml nella radice del progetto."""

from __future__ import annotations

import json
import logging
import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_TOML = '''\
# Configurazione di llmwiki. I percorsi sono relativi a questo file.

[paths]
docs = "data/docs"   # cartella condivisa con i documenti originali
wiki = "data/wiki"   # riassunti, sintesi, mappe e indice (generati)

[llm]
# "anthropic"  -> Claude tramite SDK ufficiale (credenziali: ANTHROPIC_API_KEY o `ant auth login`)
# "openai"     -> qualunque endpoint compatibile OpenAI: Ollama, LM Studio, vLLM, OpenRouter...
# "mock"       -> nessun modello: serve solo per provare la pipeline senza spendere token
provider = "anthropic"
agent_model = "claude-opus-5-5"     # agente che naviga e risponde
summary_model = "claude-opus-5-5"   # riassunti in fase di indicizzazione (il grosso dei token)
judge_model = "claude-haiku-5-5"    # decision model veloce per il fact-checking

# Solo per provider = "openai" (esempio con Ollama in locale):
# base_url = "http://localhost:11434/v1"
# api_key_env = "OPENAI_API_KEY"
# agent_model = "qwen3:14b"
# summary_model = "qwen3:14b"
# judge_model = "qwen3:4b"

[index]
concurrency = 8      # chiamate al modello in parallelo durante l'indicizzazione
fanout = 8           # quanti elementi riassume ogni nodo dell'albero
chunk_chars = 24000  # i documenti più lunghi vengono riassunti a pezzi, in parallelo
watch_seconds = 20   # ogni quanto il server ricontrolla la cartella dei documenti

[verify]
enabled = true
judge = "auto"       # "auto": decision model NLI se installato, altrimenti il modello linguistico
threshold = 0.6      # confidenza minima del decision model per accettare una citazione
context_lines = 20   # righe di contesto in più date al ricontrollo

[agent]
max_steps = 24
explorers = 4        # sotto-agenti in parallelo quando l'agente delega
explorer_steps = 12

[server]
host = "127.0.0.1"   # "0.0.0.0" per renderlo raggiungibile dai colleghi (richiede almeno un utente)
port = 8765

# Un token per utente: `llmwiki user add <nome>` aggiunge una riga qui sotto.
[server.users]
'''


@dataclass
class LLMConfig:
    provider: str = "anthropic"
    agent_model: str = "claude-opus-5-5"
    summary_model: str = "claude-opus-5-5"
    judge_model: str = "claude-haiku-5-5"
    base_url: str = "http://localhost:11434/v1"
    api_key_env: str = "OPENAI_API_KEY"
    agent_effort: str = "high"
    summary_effort: str = "medium"
    judge_effort: str = "low"
    # Solo provider "openai": manda *_effort al server come `reasoning_effort` (none, low,
    # medium, high). Utile con i modelli locali che "pensano": meno ragionamento, più velocità.
    send_reasoning_effort: bool = False
    refusal_fallbacks: bool = True
    timeout: float = 600.0


@dataclass
class IndexConfig:
    concurrency: int = 8
    fanout: int = 8
    chunk_chars: int = 24000
    watch_seconds: float = 20.0


@dataclass
class VerifyConfig:
    enabled: bool = True
    # "auto": decision model NLI se installato, altrimenti il modello linguistico;
    # "nli": solo NLI; "llm": solo modello linguistico (logprob se il server li espone)
    judge: str = "auto"
    threshold: float = 0.6
    context_lines: int = 20
    max_passage_lines: int = 150


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
    users: dict[str, str] = field(default_factory=dict)


@dataclass
class Config:
    root: Path
    docs_dir: Path
    wiki_dir: Path
    llm: LLMConfig = field(default_factory=LLMConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    verify: VerifyConfig = field(default_factory=VerifyConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    path: Path | None = None

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "Config":
        cfg_path = Path(path or os.environ.get("LLMWIKI_CONFIG") or "wiki.toml").resolve()
        data: dict = {}
        if cfg_path.exists():
            # utf-8-sig: Blocco note e PowerShell salvano spesso con il BOM in testa
            data = tomllib.loads(cfg_path.read_text(encoding="utf-8-sig"))
        return cls.from_dict(data, cfg_path.parent, cfg_path if cfg_path.exists() else None)

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
                 "# oppure a mano: i percorsi sono relativi a questo file.", "",
                 "[paths]", f"docs = {value(relative(self.docs_dir))}",
                 f"wiki = {value(relative(self.wiki_dir))}"]
        for section in ("llm", "index", "verify", "agent", "server"):
            lines += ["", f"[{section}]"]
            target = getattr(self, section)
            lines += [f"{f.name} = {value(getattr(target, f.name))}"
                      for f in fields(target) if f.name != "users"]
        lines += ["", "[server.users]"]
        lines += [f"{json.dumps(name)} = {value(token)}" for name, token in self.server.users.items()]
        return "\n".join(lines) + "\n"

    def save(self) -> None:
        if self.path is None:
            self.path = self.root / "wiki.toml"
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(self.to_toml(), encoding="utf-8")
        os.replace(tmp, self.path)

    @classmethod
    def from_dict(cls, data: dict, root: Path, path: Path | None = None) -> "Config":
        paths = data.get("paths", {})
        cfg = cls(
            root=root,
            docs_dir=(root / paths.get("docs", "data/docs")).resolve(),
            wiki_dir=(root / paths.get("wiki", "data/wiki")).resolve(),
            path=path,
        )
        for section in ("llm", "index", "verify", "agent", "server"):
            target = getattr(cfg, section)
            known = {f.name for f in fields(target)}
            for key, value in data.get(section, {}).items():
                if key not in known:
                    # scritta da una versione più recente (o un refuso): si ignora, non si blocca
                    logging.getLogger("llmwiki.config").warning(
                        "wiki.toml: impostazione sconosciuta [%s].%s ignorata", section, key)
                    continue
                setattr(target, key, value)
        return cfg
