"""Il banco di prova resta eseguibile, e il decision model non peggiora senza che ce ne accorgiamo."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from conftest import REAL_MODEL_DIR
from llmwiki import nli

EVALS = Path(__file__).parent.parent / "evals"
spec = importlib.util.spec_from_file_location("evals_run", EVALS / "run.py")
evals_run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evals_run)


def test_eval_files_are_consistent():
    cases = evals_run.load_cases()
    assert len(cases) >= 30 and any(y for *_, y in cases) and any(not y for *_, y in cases)
    questions = json.loads((EVALS / "questions.json").read_text(encoding="utf-8"))["questions"]
    docs = Path(__file__).parent.parent / "examples" / "docs"
    for item in questions:
        assert item["question"].strip()
        for doc in item["must_cite"]:
            assert (docs / doc).is_file(), f"documento d'esempio mancante: {doc}"
    perfect = evals_run.judge_metrics([0.9, 0.8, 0.1], [True, True, False], 0.6)
    assert perfect == {"auc": 1.0, "false_accepts": 0, "false_rejects": 0}


def test_answers_report_keeps_text_steps_and_settings(tmp_path, monkeypatch):
    """Per confrontare le combinazioni servono il testo delle risposte, i passi, il tempo della
    verifica e le impostazioni usate, salvati nel file indicato."""
    config = tmp_path / "wiki.toml"
    config.write_text('[llm]\nprovider = "mock"\n[verify]\njudge = "llm"\n', encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["run.py", "answers", "--config", str(config), "--limit", "2",
                                     "--work", str(tmp_path / "lavoro"), "--out", "prova.json"])
    evals_run.main()
    report = json.loads((tmp_path / "lavoro" / "prova.json").read_text(encoding="utf-8"))
    assert report["settings"]["agent_model"] and report["index"]["documents"] >= 1
    assert len(report["answers"]) == 2
    for row in report["answers"]:
        assert {"answer", "steps", "explorer_steps", "verify_seconds", "chars", "mode"} <= set(row)
        assert row["steps"] >= 1


@pytest.mark.skipif(not nli.installed(REAL_MODEL_DIR), reason="decision model non installato")
def test_decision_model_keeps_its_quality():
    judge = nli.NliJudge(REAL_MODEL_DIR)
    cases = evals_run.load_cases()
    scores = [judge.score(claim, passage) for passage, claim, _ in cases]
    metrics = evals_run.judge_metrics(scores, [y for *_, y in cases], 0.6)
    assert metrics["false_accepts"] == 0   # mai accettare una citazione sbagliata
    assert metrics["false_rejects"] <= 2   # quelle giuste respinte passano al giudice successivo
    assert metrics["auc"] >= 0.98


def test_formulas_written_in_latex_count_as_the_same_answer():
    """Confronto del 15/11: tre risposte giuste contate sbagliate perché scritte come formule."""
    assert evals_run._matches(r"Il rapporto vale $\frac{5}{2}$.", "5/2")
    assert evals_run._matches(r"Il coefficiente è $0{,}40$", "0,40|0.40")
    assert evals_run._matches("La penale è del 2%", "3%|2%")
    assert not evals_run._matches(r"vale $\frac{5}{3}$", "5/2")
