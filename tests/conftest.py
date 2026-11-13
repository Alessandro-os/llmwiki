from __future__ import annotations

import pytest

from llmwiki import nli

# Cartella vera del decision model, letta prima che i test spostino la cartella dell'app.
REAL_MODEL_DIR = nli.model_dir()


@pytest.fixture(autouse=True)
def isolated_app_home(tmp_path_factory, monkeypatch):
    """Ogni test ha la sua cartella dell'app: niente registro, chiavi o modelli del PC."""
    monkeypatch.setenv("LLMWIKI_HOME", str(tmp_path_factory.mktemp("apphome")))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
