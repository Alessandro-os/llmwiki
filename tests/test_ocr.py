"""OCR: qualunque OCR, trovato e provato da solo. Server OCR finti, nessun modello vero."""

from __future__ import annotations

import asyncio
import io

import httpx
import pytest
from fastapi.testclient import TestClient

from llmwiki import app as app_module
from llmwiki import ocr
from llmwiki.app import Wiki
from llmwiki.config import Config
from llmwiki.extract import ExtractError, extract_lines
from llmwiki.ocr import Ocr, OcrError, ServerOcr, probe
from llmwiki.server import create_app

LOCAL = {"base_url": "http://127.0.0.1:8765", "client": ("127.0.0.1", 50000)}


def scanned_pdf(path, pages: int = 2) -> None:
    """Un PDF fatto solo di immagini, come una scansione: dentro non c'è testo."""
    from PIL import Image

    images = [Image.open(io.BytesIO(ocr.sample_image())).convert("RGB") for _ in range(pages)]
    images[0].save(path, format="PDF", save_all=True, append_images=images[1:])


def vision_server(sees: bool = True, status: int = 200):
    """Un server compatibile OpenAI che legge (o non legge) le immagini."""

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status, text="errore")
        has_image = b"data:image/png;base64," in request.content
        text = "<think>guardo</think>CARNOT 1824" if sees and has_image else "Non vedo immagini."
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

    return httpx.MockTransport(handler)


class FakeOcr(Ocr):
    name = "OCR di prova"

    def __init__(self, fail: OcrError | None = None) -> None:
        super().__init__(dpi=50)
        self.fail, self.pages = fail, 0

    def read(self, png: bytes) -> str:
        if self.fail:
            raise self.fail
        self.pages += 1
        return f"Appunti di termodinamica, pagina letta dall'OCR numero {self.pages}."


def ocr_cfg(tmp_path, **ocr_values) -> Config:
    return Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"},
                             "ocr": {"mode": "ocr", **ocr_values}}, tmp_path)


def test_server_ocr_reads_and_reports_problems_like_a_model():
    engine = ServerOcr("http://ocr.test/v1", "unlimited-ocr", transport=vision_server())
    assert engine.read(ocr.sample_image()) == "CARNOT 1824"  # il ragionamento <think> si toglie
    down = ServerOcr("http://ocr.test/v1", "m", transport=vision_server(status=503))
    with pytest.raises(OcrError) as busy:
        down.read(b"png")
    assert busy.value.unavailable
    refused = ServerOcr("http://ocr.test/v1", "m", transport=vision_server(status=400))
    with pytest.raises(OcrError) as rejected:
        refused.read(b"png")
    assert not rejected.value.unavailable


def test_layout_coordinates_are_removed():
    """Uscite vere di Unlimited OCR 2 (misura del 16/11) e il formato di DeepSeek-OCR."""
    unlimited = ("text[45, 79, 512, 133]Meccanica applicata alle macchine - Lezione 7\n"
                 "text[47, 284, 606, 343]Il rendimento è $\\eta = 1 - T_2/T_1$ e non dipende dal fluido.")
    assert ocr.clean_text(unlimited) == ("Meccanica applicata alle macchine - Lezione 7\n"
                                         "Il rendimento è $\\eta = 1 - T_2/T_1$ e non dipende dal fluido.")
    deepseek = "<|ref|>title<|/ref|><|det|>[[10, 20, 300, 60]]<|/det|>\nCiclo di Carnot"
    assert ocr.clean_text(deepseek) == "Ciclo di Carnot"
    assert ocr.clean_text("Il vettore v[1, 2, 3, 4] resta") == "Il vettore v[1, 2, 3, 4] resta"
    page = ("<PAGE><BLOCK>text[35, 15, 299, 35]<FORK>STATICA DEI FLUIDI\n"
            "<BLOCK>equation[59, 639, 619, 675]<FORK>$$p = p(x,y,z)$$")  # pagina vera, 16/11
    assert ocr.clean_text(page) == "STATICA DEI FLUIDI\n$$p = p(x,y,z)$$"


def test_probe_accepts_only_an_ocr_that_really_reads():
    assert probe(ServerOcr("http://ocr.test/v1", "vede", transport=vision_server()))["ok"]
    blind = probe(ServerOcr("http://ocr.test/v1", "cieco", transport=vision_server(sees=False)))
    assert not blind["ok"] and "non legge" in blind["error"]


def test_scanned_pdf_needs_the_ocr_and_says_where_to_choose_it(tmp_path):
    pdf = tmp_path / "appunti.pdf"
    scanned_pdf(pdf)
    with pytest.raises(ExtractError, match="Impostazioni"):
        extract_lines(pdf)
    pages = []
    lines = extract_lines(pdf, FakeOcr(), lambda done, total: pages.append((done, total)))
    assert pages == [(1, 2), (2, 2)]
    assert "=== Pagina 2 ===" in lines and any("letta dall'OCR numero 2" in line for line in lines)


def test_document_read_with_the_ocr_remembers_which_ocr(tmp_path):
    cfg = ocr_cfg(tmp_path)
    cfg.docs_dir.mkdir(parents=True)
    scanned_pdf(cfg.docs_dir / "appunti.pdf", pages=3)

    async def scenario():
        wiki = Wiki(cfg)
        wiki.indexer.ocr = FakeOcr()
        status = await wiki.indexer.run_once()
        assert status["ready"] == 1 and status["last_done"]["ocr"] == "OCR di prova"
        assert wiki.store.get_doc("appunti.pdf")["ocr"] == "OCR di prova"
        assert "letta dall'OCR numero 3" in wiki.tools.read_document("appunti.pdf")
        await wiki.aclose()

    asyncio.run(scenario())


def test_without_a_working_ocr_the_document_waits_instead_of_failing(tmp_path):
    cfg = ocr_cfg(tmp_path)  # modo OCR ma nessun OCR collegato
    cfg.docs_dir.mkdir(parents=True)
    scanned_pdf(cfg.docs_dir / "appunti.pdf")
    (cfg.docs_dir / "nota.md").write_text("# Nota\n\nUn file di testo non passa dall'OCR.\n", encoding="utf-8")

    async def scenario():
        wiki = Wiki(cfg)
        status = await wiki.indexer.run_once()
        assert status["ready"] == 1 and status["pending"] == 1 and status["error"] == 0
        assert status["waiting_ocr"] and "Nessun OCR collegato" in status["waiting"]
        await wiki.aclose()

        wiki = Wiki(cfg)  # OCR collegato ma spento a metà
        wiki.indexer.ocr = FakeOcr(fail=OcrError("l'OCR non risponde", unavailable=True))
        status = await wiki.indexer.run_once()
        assert status["pending"] == 1 and status["error"] == 0 and status["waiting_ocr"]
        await wiki.aclose()

    asyncio.run(scenario())


def test_search_lists_what_reads_first(monkeypatch):
    async def servers():
        return [{"name": "SGLang", "base_url": "http://127.0.0.1:10000/v1", "models": ["cieco", "Unlimited-OCR-2"]}]

    def server_ocr(base_url, model, api_key="", dpi=200, timeout=600.0, transport=None):
        return ServerOcr(base_url, model, transport=vision_server(sees=model != "cieco"))

    monkeypatch.setattr(app_module, "detect_local_servers", servers)
    monkeypatch.setattr(ocr, "ServerOcr", server_ocr)
    monkeypatch.setattr(ocr, "find_tesseract", lambda: [])
    found = asyncio.run(app_module.detect_ocr())
    assert [(f["model"], f["ok"]) for f in found] == [("Unlimited-OCR-2", True), ("cieco", False)]


def test_ocr_settings_from_the_ui(tmp_path):
    cfg = Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"}}, tmp_path)
    cfg.save()
    with TestClient(create_app(Wiki(Config.load(cfg.path))), **LOCAL) as client:
        assert client.post("/api/admin/ocr/test").json()["ok"] is False  # niente collegato
        saved = client.post("/api/admin/settings", json={"ocr": {
            "mode": "ocr", "kind": "server", "base_url": "http://127.0.0.1:10000/v1", "model": "Unlimited-OCR-2"}})
        assert saved.status_code == 200 and saved.json()["ocr"]["model"] == "Unlimited-OCR-2"
        assert client.post("/api/admin/settings", json={"ocr": {"mode": "boh"}}).status_code == 400
    assert Config.load(cfg.path).ocr.kind == "server"


@pytest.mark.skipif(not ocr.tesseract_places(), reason="Tesseract non installato")
def test_real_tesseract_reads_a_scanned_pdf(tmp_path):
    """Con Tesseract vero, se c'è sul computer: la ricerca lo trova e legge una scansione."""
    found = ocr.find_tesseract()
    assert found and found[0]["ok"]
    pdf = tmp_path / "scansione.pdf"
    scanned_pdf(pdf, pages=1)
    engine = ocr.TesseractOcr(found[0]["path"], found[0]["language"])
    assert any("CARNOT" in line.upper() for line in extract_lines(pdf, engine))
