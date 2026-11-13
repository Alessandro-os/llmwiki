"""Banco di prova di LLMWiki: numeri prima e dopo ogni modifica, invece di impressioni.

  uv run python evals/run.py judge                       decision model NLI (se installato)
  uv run python evals/run.py judge --config wiki.toml    anche il giudice del modello in wiki.toml
  uv run python evals/run.py answers --config wiki.toml  domande end-to-end sui documenti di esempio

`answers` indicizza examples/docs in evals/.work (una volta sola, poi riusa l'indice) con i
modelli della configurazione indicata, pone le domande di questions.json e controlla che la
risposta contenga i fatti attesi, citi i documenti giusti e non lasci citazioni non confermate.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from llmwiki import nli  # noqa: E402
from llmwiki.app import Wiki, load_secrets  # noqa: E402
from llmwiki.config import Config  # noqa: E402
from llmwiki.llm import make_llm  # noqa: E402
from llmwiki.verify import VERIFIED, WARNING  # noqa: E402


def load_cases() -> list[tuple[str, str, bool]]:
    data = json.loads((HERE / "judge_cases.json").read_text(encoding="utf-8"))
    return [(data["passages"][c["passage"]], c["claim"], c["supported"]) for c in data["cases"]]


def judge_metrics(scores: list[float], labels: list[bool], threshold: float) -> dict:
    positives = [s for s, y in zip(scores, labels) if y]
    negatives = [s for s, y in zip(scores, labels) if not y]
    pairs = len(positives) * len(negatives)
    auc = sum((p > n) + 0.5 * (p == n) for p in positives for n in negatives) / pairs if pairs else 0.0
    return {
        "auc": auc,
        "false_accepts": sum(s >= threshold for s in negatives),  # citazione sbagliata accettata
        "false_rejects": sum(s < threshold for s in positives),   # citazione giusta respinta
    }


def cmd_judge(args) -> int:
    cases = load_cases()
    labels = [y for _, _, y in cases]
    rows = []
    if nli.installed():
        judge = nli.NliJudge()
        judge.score("riscaldamento", "riscaldamento")
        started = time.time()
        scores = [judge.score(claim, passage) for passage, claim, _ in cases]
        rows.append(("decision model NLI", scores, (time.time() - started) / len(cases)))
    else:
        print("decision model NLI non installato (uv run llmwiki model install): salto")
    if args.config:
        load_secrets()
        cfg = Config.load(args.config)
        llm = make_llm(cfg.llm)

        async def run() -> tuple[list[float], str]:
            out, method = [], ""
            for passage, claim, _ in cases:
                score, method = await llm.judge(model=cfg.llm.judge_model, claim=claim, passage=passage)
                out.append(score)
            await llm.aclose()
            return out, method

        started = time.time()
        scores, method = asyncio.run(run())
        rows.append((f"giudice {cfg.llm.judge_model} ({method})", scores, (time.time() - started) / len(cases)))
    for name, scores, seconds in rows:
        m = judge_metrics(scores, labels, args.threshold)
        print(f"\n{name}: {len(cases)} casi · {seconds * 1000:.0f} ms l'uno · AUC {m['auc']:.3f} · soglia "
              f"{args.threshold}: sbagliate accettate {m['false_accepts']}, giuste respinte {m['false_rejects']}")
        for score, (_, claim, y) in zip(scores, cases):
            if (score >= args.threshold) != y:
                print(f"   errore: atteso {'SI' if y else 'NO'}, punteggio {score:.3f} · {claim}")
    return 0


def _matches(text: str, needle: str) -> bool:
    return any(option.lower() in text.lower() for option in needle.split("|"))


def cmd_answers(args) -> int:
    load_secrets()
    source = Config.load(args.config)
    work = HERE / ".work"
    docs = work / "documenti"
    if args.fresh and work.exists():
        shutil.rmtree(work)
    shutil.copytree(ROOT / "examples" / "docs", docs, dirs_exist_ok=True)
    cfg = Config.from_dict({"paths": {"docs": "documenti", "wiki": ".indice"}}, work)
    cfg.llm, cfg.index, cfg.verify, cfg.agent = source.llm, source.index, source.verify, source.agent
    questions = json.loads((HERE / "questions.json").read_text(encoding="utf-8"))["questions"]
    if args.limit:
        questions = questions[: args.limit]

    async def run() -> list[dict]:
        wiki = Wiki(cfg)
        started = time.time()
        status = await wiki.indexer.run_once()
        print(f"indice: {status['ready']} documenti, {status['nodes']} nodi, {status['error']} errori, "
              f"{time.time() - started:.0f} s, chiamate {status['llm_calls'] or 'nessuna'}")
        results = []
        for item in questions:
            started = time.time()
            try:
                answer = await wiki.ask(item["question"])
            except Exception as exc:
                results.append({"q": item["question"], "ok": False, "why": [f"errore: {exc}"], "seconds": 0,
                                "citations": 0, "verified": 0, "warnings": 0})
                continue
            why = [f"manca «{needle}»" for needle in item["must_contain"] if not _matches(answer.answer, needle)]
            cited = {c.doc for c in answer.citations}
            why += [f"non cita {doc}" for doc in item["must_cite"] if doc not in cited]
            warnings = sum(c.status == WARNING for c in answer.citations)
            if warnings:
                why.append(f"{warnings} citazioni non confermate")
            if not item.get("unanswerable") and not answer.citations:
                why.append("nessuna citazione")
            results.append({
                "q": item["question"], "ok": not why, "why": why, "seconds": time.time() - started,
                "citations": len(answer.citations), "warnings": warnings,
                "verified": sum(c.status == VERIFIED for c in answer.citations),
                "methods": sorted({c.method for c in answer.citations}),
            })
            last = results[-1]
            print(f"{'OK  ' if last['ok'] else 'NO  '} {last['seconds']:4.0f} s · {last['citations']} citazioni "
                  f"({last['verified']} al primo giudice, {warnings} ⚠) · {item['question'][:70]}"
                  + (f"\n      {'; '.join(why)}" if why else ""))
        await wiki.aclose()
        return results

    results = asyncio.run(run())
    total = len(results)
    cites = sum(r["citations"] for r in results)
    print(f"\nrisposte corrette {sum(r['ok'] for r in results)}/{total} · citazioni {cites}, di cui "
          f"confermate al primo giudice {sum(r['verified'] for r in results)}, non confermate "
          f"{sum(r['warnings'] for r in results)} · tempo medio {sum(r['seconds'] for r in results) / max(total, 1):.0f} s")
    (work / "ultimo_risultato.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(r["ok"] for r in results) else 1


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_judge = sub.add_parser("judge")
    p_judge.add_argument("--config")
    p_judge.add_argument("--threshold", type=float, default=0.6)
    p_answers = sub.add_parser("answers")
    p_answers.add_argument("--config", required=True)
    p_answers.add_argument("--limit", type=int, default=0)
    p_answers.add_argument("--fresh", action="store_true", help="ricostruisce l'indice da zero")
    args = parser.parse_args()
    return cmd_judge(args) if args.command == "judge" else cmd_answers(args)


if __name__ == "__main__":
    raise SystemExit(main())
