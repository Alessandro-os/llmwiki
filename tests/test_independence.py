"""L'app non dipende da un modello in particolare: server finti che si comportano in modi
diversi (e male) devono portare comunque a un indice costruito e a una risposta citata."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from llmwiki import indexer as indexer_module
from llmwiki.app import Wiki
from llmwiki.config import Config
from llmwiki.llm import LLMError, MockLLM, OpenAICompatLLM

CONTRACT = """\
# Contratto di fornitura Acme

## Art. 7 · Consegne
La consegna avviene entro 30 giorni dalla data dell'ordine.

## Art. 9 · Penali
In caso di ritardo è prevista una penale del 2% del valore dell'ordine per ogni
settimana di ritardo, fino a un massimo del 10%.
"""
CITATION = {"id": 1, "doc": "contratti/acme.md", "start_line": 7, "end_line": 8,
            "claim": "È prevista una penale del 2% del valore dell'ordine per ogni settimana di ritardo."}
FINAL = {"answer": "La penale è del 2% per ogni settimana di ritardo [1].", "citations": [CITATION]}


def reply(content=None, tool_calls=None, status=200):
    if status != 200:
        return httpx.Response(status, json={"error": {"message": content}})
    message = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = [
            {"id": f"c{i}", "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}
            for i, (name, args) in enumerate(tool_calls)]
    return httpx.Response(200, json={"choices": [{"message": message}]})


def fake_model(*, tools: str, json_schema: bool = True, follows_protocol: bool = True):
    """Un server compatibile OpenAI finto.
    tools: "native" le usa, "rejected" risponde 400 se le riceve, "ignored" risponde a parole.
    json_schema: se accetta response_format. follows_protocol: se rispetta il protocollo testuale."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        system = body["messages"][0]["content"]
        last = body["messages"][-1]
        if body.get("logprobs"):
            return reply("YES")  # nessun logprob nella risposta: si passa al giudizio in JSON
        if "response_format" in body and not json_schema:
            return reply("response_format non supportato", status=400)
        if "tools" in body:
            if tools == "rejected":
                return reply("questo modello non supporta tools", status=400)
            if tools == "ignored":
                return reply("Posso aiutarti a cercare nei documenti.")
            if last["role"] == "tool":
                return reply(None, [("answer", FINAL)])
            return reply(None, [("search", {"query": "penale ritardo"})])
        if "A ogni turno rispondi SOLO con un oggetto JSON" in system:  # protocollo testuale
            if not follows_protocol:
                return reply("Certo! Cerco subito le penali nel contratto.")
            if "[risultati]" in last["content"]:
                return reply("Ecco la risposta:\n" + json.dumps({"calls": [{"tool": "answer", "args": FINAL}]}))
            return reply(json.dumps({"calls": [{"tool": "search", "args": {"query": "penale ritardo"}}]}))
        if system.startswith("Rispondi alla domanda usando solo i passaggi"):  # ricerca diretta
            return reply("```json\n" + json.dumps(FINAL) + "\n```")
        if "verificatore" in system or "secondo controllo" in system:
            return reply(json.dumps({"supported": True, "confidence": 0.9, "reason": "c'è",
                                     "start_line": 0, "end_line": 0}))
        return reply("# Contratto di fornitura Acme\n\n## Sintesi\nPenale del 2% a settimana (righe 7-8).")

    return handler, seen


def make_wiki(tmp_path, handler, **llm) -> Wiki:
    cfg = Config.from_dict({
        "llm": {"provider": "openai", "base_url": "http://modello.test/v1", "agent_model": "m",
                "summary_model": "m", "judge_model": "m", **llm},
        "verify": {"judge": "llm"},
    }, tmp_path)
    (cfg.docs_dir / "contratti").mkdir(parents=True)
    (cfg.docs_dir / "contratti" / "acme.md").write_text(CONTRACT, encoding="utf-8")
    model = OpenAICompatLLM(cfg.llm)
    model.http = httpx.AsyncClient(base_url="http://modello.test/v1", transport=httpx.MockTransport(handler))
    return Wiki(cfg, llm=model)


@pytest.mark.parametrize(("behaviour", "mode"), [
    ({"tools": "native"}, "agente"),                                   # modello capace
    ({"tools": "rejected"}, "agente"),                                 # il server rifiuta gli strumenti
    ({"tools": "ignored"}, "agente"),                                  # il modello non li usa
    ({"tools": "rejected", "json_schema": False}, "agente"),           # e non accetta nemmeno lo schema
    ({"tools": "ignored", "follows_protocol": False}, "ricerca diretta"),  # non segue alcun protocollo
])
def test_any_model_ends_with_a_verified_cited_answer(tmp_path, behaviour, mode):
    handler, seen = fake_model(**behaviour)

    async def scenario():
        wiki = make_wiki(tmp_path, handler)
        status = await wiki.indexer.run_once()
        assert status["ready"] == 1 and status["error"] == 0
        answer = await wiki.ask("Qual è la penale per ritardo?")
        assert answer.complete and answer.mode == mode
        assert "2%" in answer.answer
        assert [c.doc for c in answer.citations] == ["contratti/acme.md"]
        assert answer.citations[0].status == "verified"
        if behaviour["tools"] == "rejected":
            before = len([b for b in seen if "tools" in b])
            await wiki.ask("E il tetto massimo?")
            assert len([b for b in seen if "tools" in b]) == before  # il rifiuto è stato ricordato
        await wiki.aclose()

    asyncio.run(scenario())


def test_forced_text_mode_never_sends_native_tools(tmp_path):
    handler, seen = fake_model(tools="native")

    async def scenario():
        wiki = make_wiki(tmp_path, handler, tool_mode="text")
        await wiki.indexer.run_once()
        answer = await wiki.ask("Qual è la penale per ritardo?")
        assert answer.complete and answer.citations[0].status == "verified"
        assert not any("tools" in body for body in seen)
        await wiki.aclose()

    asyncio.run(scenario())


def test_small_context_window_trims_old_results_and_long_documents_are_split(tmp_path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        size = sum(len(str(m.get("content") or "")) for m in body["messages"])
        if size > 9000:  # un modello con poco contesto rifiuta le richieste troppo lunghe
            return reply("maximum context length exceeded", status=400)
        return reply("# Verbale\n\nAppunti sulla parte letta.")

    async def scenario():
        wiki = make_wiki(tmp_path, handler)
        long_text = "\n".join(f"Riga {n}: il valore registrato è {n * 7} euro." for n in range(900))
        (wiki.cfg.docs_dir / "lungo.txt").write_text(long_text, encoding="utf-8")
        status = await wiki.indexer.run_once()
        # 36.000 caratteri non stanno nella finestra: l'app dimezza i pezzi finché il modello li accetta
        assert status["ready"] == 2 and status["error"] == 0
        assert wiki.llm.calls["chunk"] > 4
        await wiki.aclose()

    asyncio.run(scenario())

    from llmwiki.llm import OMITTED, ToolResult, _OpenAIConversation
    cfg = Config.from_dict({"llm": {"provider": "openai", "context_tokens": 1000}}, tmp_path).llm
    conversation = _OpenAIConversation(OpenAICompatLLM(cfg), "m", "sistema", [], "domanda")
    for n in range(6):
        conversation.messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": "x" * 1500})
    conversation._trim()
    contents = [m["content"] for m in conversation.messages if m["role"] == "tool"]
    assert contents[0] == OMITTED and contents[-1] != OMITTED  # i più vecchi lasciano il posto
    assert contents.count(OMITTED) == 4  # restano interi solo i due risultati più recenti
    assert ToolResult("a", "b").is_error is False


def test_indexing_waits_for_the_model_instead_of_failing(tmp_path, monkeypatch):
    monkeypatch.setattr(indexer_module, "RETRY_SECONDS", 0.3)

    class FlakyModel(MockLLM):
        """Spento per le prime richieste, poi torna."""

        failures = 4

        async def complete(self, **kwargs):
            if FlakyModel.failures > 0:
                FlakyModel.failures -= 1
                raise LLMError("il modello non risponde", 0)
            return await super().complete(**kwargs)

    cfg = Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"},
                            "index": {"watch_seconds": 0.2}}, tmp_path)
    cfg.docs_dir.mkdir(parents=True)
    for n in range(3):
        (cfg.docs_dir / f"nota_{n}.md").write_text(f"# Nota {n}\n\nContenuto della nota {n}.\n", encoding="utf-8")

    async def scenario():
        wiki = Wiki(cfg, llm=FlakyModel(cfg.llm))
        await wiki.indexer.start()
        await asyncio.sleep(0.25)
        status = wiki.indexer.status()
        assert status["error"] == 0 and status["waiting"]  # in attesa, non in errore
        loop = asyncio.get_running_loop()
        started = loop.time()
        while wiki.indexer.status()["ready"] < 3 or wiki.indexer.status()["busy"]:
            await asyncio.sleep(0.1)
            assert loop.time() - started < 20
        status = wiki.indexer.status()
        assert status["ready"] == 3 and status["error"] == 0 and not status["waiting"]
        assert wiki.tools.list_folder("")["document_count"] == 3
        await wiki.indexer.stop()
        await wiki.aclose()

    asyncio.run(scenario())


def test_wrong_key_is_reported_as_an_error_not_retried_forever(tmp_path):
    def handler(_request: httpx.Request) -> httpx.Response:
        return reply("Incorrect API key provided", status=401)

    async def scenario():
        wiki = make_wiki(tmp_path, handler)
        status = await wiki.indexer.run_once()
        assert status["error"] == 1 and not status["waiting"]
        assert "401" in wiki.store.get_doc("contratti/acme.md")["error"]
        await wiki.aclose()

    asyncio.run(scenario())
