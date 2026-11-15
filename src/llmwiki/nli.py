"""Decision model: un piccolo modello NLI che gira sulla CPU in decine di millisecondi.

Riceve il passaggio citato e l'affermazione e restituisce la probabilità che il passaggio
*implichi* l'affermazione. Non è un LLM: non genera testo, classifica. È quello che decide se
una citazione passa o va ricontrollata.

Modello: mDeBERTa-v3 addestrato su 2,7 milioni di coppie NLI in 27 lingue (licenza MIT).
Scelto il 2026-11-13 dopo un confronto su 32 citazioni italiane giuste e sbagliate: nessuna
citazione sbagliata accettata e nessuna giusta respinta (AUC 1,000 leggendo il passaggio anche
frase per frase), 100-200 ms a citazione sulla CPU. Scartati: la versione quantizzata a 8 bit
dello stesso modello (AUC 0,909) e LettuceDetect v2 mmBERT (AUC 0,925, richiede PyTorch).
Sulle affermazioni lunghe scritte da un agente respinge alcune citazioni corrette: per questo
nella verifica è il primo filtro di una cascata, non l'unico giudice.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
from pathlib import Path

from . import apphome

REPO = "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7"
REVISION = "b5113eb38ab63efdd7f280f8c144ea8b13f978ce"
NAME = "mdeberta-v3-nli"
LICENSE = "MIT"
# nome locale -> (percorso nel repository, dimensione in byte, sha256)
FILES = {
    "model.onnx": ("onnx/model.onnx", 1116115065,
                   "e9238a33e07411eae1d1cef1d5f22e5f556717ce586c827581bb59598a45fe37"),
    "tokenizer.json": ("tokenizer.json", 16316151,
                       "e23095eb61ba944c7be3a5d3e8ec19e37ce7ced0daa03550bde03e83c21b3f8a"),
}
TOTAL_BYTES = sum(size for _, size, _ in FILES.values())
MAX_TOKENS = 512
MAX_CLAIM_TOKENS = 160
# I modelli NLI sono addestrati su premesse brevi: con finestre lunghe e piene di testo
# irrilevante smettono di riconoscere il fatto anche quando c'è.
WINDOW_TOKENS = 200
MAX_GROUPS = 240
BATCH = 16

log = logging.getLogger(__name__)


def model_dir() -> Path:
    return apphome.models_dir() / NAME


def installed(directory: Path | None = None) -> bool:
    """Un modello presente ma illeggibile (permessi, disco staccato, un collegamento di cartella
    che Windows rifiuta: WinError 448) conta come assente. Così l'app si apre comunque e
    verifica con il modello linguistico, invece di non partire."""
    directory = directory or model_dir()
    try:
        return all((directory / name).is_file() and (directory / name).stat().st_size == size
                   for name, (_, size, _) in FILES.items())
    except OSError as exc:
        log.warning("decision model in %s non leggibile: %s", directory, exc)
        return False


class Download:
    """Scaricamento del modello da Hugging Face, riprendibile e verificato con sha256."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or model_dir()
        self.state = {"status": "ready" if installed(self.directory) else "missing",
                      "done": 0, "total": TOTAL_BYTES, "error": ""}
        self._lock = threading.Lock()

    def status(self) -> dict:
        info = dict(self.state)
        info.update(name=NAME, repo=REPO, license=LICENSE, path=str(self.directory))
        return info

    def start(self) -> None:
        with self._lock:
            if self.state["status"] in ("downloading", "ready"):
                return
            self.state.update(status="downloading", done=0, error="")
        threading.Thread(target=self._run, name="llmwiki-model-download", daemon=True).start()

    def run_blocking(self) -> dict:
        if self.state["status"] != "ready":
            self.state.update(status="downloading", done=0, error="")
            self._run()
        return self.status()

    def _run(self) -> None:
        import httpx

        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            finished = 0
            with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, read=120.0)) as http:
                for name, (remote, size, sha) in FILES.items():
                    target = self.directory / name
                    if not (target.is_file() and target.stat().st_size == size):
                        self._fetch(http, remote, target, size, sha, finished)
                    finished += size
                    self.state["done"] = finished
            self.state.update(status="ready", done=TOTAL_BYTES)
        except Exception as exc:  # rete assente, disco pieno, file corrotto: lo stato lo racconta
            self.state.update(status="error", error=str(exc)[:300])

    def _fetch(self, http, remote: str, target: Path, size: int, sha: str, base: int) -> None:
        url = f"https://huggingface.co/{REPO}/resolve/{REVISION}/{remote}"
        part = target.with_name(target.name + ".part")
        offset = part.stat().st_size if part.exists() else 0
        if offset > size:
            part.unlink()
            offset = 0
        headers = {"Range": f"bytes={offset}-"} if offset else {}
        with http.stream("GET", url, headers=headers) as response:
            if offset and response.status_code != 206:
                offset = 0  # il server non riprende: si ricomincia
            response.raise_for_status()
            with part.open("ab" if offset else "wb") as handle:
                done = offset
                for block in response.iter_bytes(1 << 20):
                    handle.write(block)
                    done += len(block)
                    self.state["done"] = base + done
        digest = hashlib.sha256()
        with part.open("rb") as handle:
            for block in iter(lambda: handle.read(1 << 20), b""):
                digest.update(block)
        if digest.hexdigest() != sha:
            part.unlink()
            raise RuntimeError(f"{target.name}: file scaricato corrotto (sha256 diverso), riprova")
        os.replace(part, target)


class NliJudge:
    """Carica il modello alla prima domanda e lo tiene in memoria (circa 1,5 GB di RAM)."""

    def __init__(self, directory: Path | None = None) -> None:
        self.directory = directory or model_dir()
        self._session = None
        self._tokenizer = None
        self._lock = threading.Lock()

    def _load(self) -> None:
        with self._lock:
            if self._session is not None:
                return
            import onnxruntime as ort
            from tokenizers import Tokenizer

            options = ort.SessionOptions()
            options.intra_op_num_threads = max(1, min(8, (os.cpu_count() or 4) // 2))
            session = ort.InferenceSession(str(self.directory / "model.onnx"), options,
                                           providers=["CPUExecutionProvider"])
            self._inputs = {item.name for item in session.get_inputs()}
            self._tokenizer = Tokenizer.from_file(str(self.directory / "tokenizer.json"))
            self._session = session

    def score(self, claim: str, passage: str, context: str = "") -> float:
        """Probabilità (0-1) che il passaggio implichi l'affermazione. `context` (per esempio
        "Documento: Policy ferie.") viene anteposto a ogni finestra del passaggio."""
        import numpy as np

        self._load()
        tok = self._tokenizer
        claim_ids = tok.encode(claim, add_special_tokens=False).ids[:MAX_CLAIM_TOKENS]
        claim = tok.decode(claim_ids) if len(claim_ids) == MAX_CLAIM_TOKENS else claim
        prefix = context.strip() + "\n" if context.strip() else ""
        used = len(claim_ids) + len(tok.encode(prefix, add_special_tokens=False).ids) + 4
        premises = self._windows(passage, min(WINDOW_TOKENS, MAX_TOKENS - used))
        premises += [p for p in self._sentence_groups(passage) if p not in premises]
        best = 0.0
        for start in range(0, len(premises), BATCH):
            encoded = [tok.encode(prefix + premise, claim) for premise in premises[start : start + BATCH]]
            width = min(MAX_TOKENS, max(len(e.ids) for e in encoded))

            def padded(rows: list[list[int]], width: int = width):
                return np.array([row[:width] + [0] * (width - len(row[:width])) for row in rows],
                                dtype=np.int64)

            feed = {"input_ids": padded([e.ids for e in encoded]),
                    "attention_mask": padded([e.attention_mask for e in encoded])}
            if "token_type_ids" in self._inputs:
                feed["token_type_ids"] = padded([e.type_ids for e in encoded])
            logits = self._session.run(None, feed)[0]
            exp = np.exp(logits - logits.max(axis=1, keepdims=True))
            probabilities = exp[:, 0] / exp.sum(axis=1)  # indice 0 = entailment
            best = max(best, float(probabilities.max()))
        return best

    @staticmethod
    def _sentence_groups(passage: str) -> list[str]:
        """Gruppi di 1, 2 e 3 frasi consecutive: un fatto circondato da testo che parla d'altro
        viene riconosciuto molto meglio se il modello vede solo le frasi che lo contengono."""
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", passage) if s.strip()]
        if len(sentences) < 2:
            return []
        groups: dict[str, None] = {}  # insieme ordinato: prima tutte le frasi singole
        for size in (1, 2, 3):
            if size >= len(sentences):
                break
            for i in range(len(sentences) - size + 1):
                if len(groups) >= MAX_GROUPS:
                    return list(groups)
                groups[" ".join(sentences[i : i + size])] = None
        return list(groups)

    def _windows(self, passage: str, budget: int) -> list[str]:
        """Un passaggio più lungo di quanto il modello legge viene diviso in finestre
        sovrapposte: basta che una sola sostenga l'affermazione."""
        offsets = self._tokenizer.encode(passage, add_special_tokens=False).offsets
        if len(offsets) <= budget:
            return [passage]
        windows, step = [], max(1, budget // 2)
        for start in range(0, len(offsets), step):
            chunk = offsets[start : start + budget]
            windows.append(passage[chunk[0][0] : chunk[-1][1]])
            if start + budget >= len(offsets):
                break
        return windows
