"""OCR: qualunque OCR, trovato e provato da solo. Server OCR finti, nessun modello vero."""

from __future__ import annotations

import asyncio
import io
import json

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

    def read_piece(self, png: bytes) -> str:
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


def streaming_server(pieces: list[str]):
    """Un server che manda il testo a pezzi (stream), come llama.cpp e vLLM."""

    def handler(request: httpx.Request) -> httpx.Response:
        events = "".join(f'data: {{"choices": [{{"delta": {{"content": {json.dumps(p)}}}}}]}}\n\n' for p in pieces)
        return httpx.Response(200, text=events + "data: [DONE]\n\n", headers={"content-type": "text/event-stream"})

    return httpx.MockTransport(handler)


def test_streamed_text_is_read_and_a_loop_is_cut():
    plain = ServerOcr("http://ocr.test/v1", "m", transport=streaming_server(["Il ciclo ", "di Carnot."]))
    assert plain.read(b"png") == "Il ciclo di Carnot."
    # PaddleOCR-VL su una pagina di soli disegni (misura vera): la stessa riga fino al limite
    unit = "①\n②\n③\n④\n⑤\n⑥\n⑦\n⑧\n⑨\n\nconcorde\n\n"
    looping = ServerOcr("http://ocr.test/v1", "m", transport=streaming_server(["B\n\n"] + [unit] * 300))
    text = looping.read(b"png")
    assert text.startswith("B") and text.count("concorde") <= 4 and len(text) < 400
    real = "riga uno della tabella | 10 | 20\n" * 3  # poche ripetizioni vere restano
    assert ocr.loop_start(real) is None


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
    assert ocr.clean_text("[Non-Text] CARNOT 1824 [Non-Text]") == "CARNOT 1824"  # MiniCPM-OCR, 16/11


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
    assert pages == [(0, 2), (1, 2), (2, 2)]  # il totale si annuncia prima della prima pagina
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


def test_automatic_mode_uses_the_ocr_only_for_pdfs_without_text(tmp_path):
    from test_extract import make_pdf

    cfg = Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"}}, tmp_path)  # "auto"
    cfg.docs_dir.mkdir(parents=True)
    make_pdf(cfg.docs_dir / "contratto.pdf", ["Contratto di fornitura n. 2026/014"])
    scanned_pdf(cfg.docs_dir / "appunti.pdf")

    async def scenario():
        wiki = Wiki(cfg)
        wiki.indexer.ocr = FakeOcr()
        status = await wiki.indexer.run_once()
        assert status["ready"] == 2
        assert wiki.store.get_doc("contratto.pdf")["ocr"] == ""  # testo esatto, niente OCR
        assert wiki.store.get_doc("appunti.pdf")["ocr"] == "OCR di prova"
        await wiki.aclose()

    asyncio.run(scenario())


def test_each_document_can_be_read_its_own_way(tmp_path):
    """Spazio in "solo testo esatto", ma un documento chiede l'OCR: vince il documento."""
    cfg = ocr_cfg(tmp_path, mode="text")
    cfg.docs_dir.mkdir(parents=True)
    scanned_pdf(cfg.docs_dir / "appunti.pdf")

    async def scenario():
        wiki = Wiki(cfg)
        wiki.indexer.ocr = FakeOcr()
        status = await wiki.indexer.run_once()
        assert status["error"] == 1 and "OCR" in wiki.store.get_doc("appunti.pdf")["error"]
        wiki.store.set_method("appunti.pdf", "ocr")  # "Rileggi con l'OCR"
        status = await wiki.indexer.run_once()
        assert status["ready"] == 1 and wiki.store.get_doc("appunti.pdf")["method"] == "ocr"
        await wiki.aclose()

    asyncio.run(scenario())


def test_reading_method_from_upload_and_from_the_document_card(tmp_path):
    cfg = ocr_cfg(tmp_path, mode="text")
    cfg.save()
    pdf = tmp_path / "appunti.pdf"
    scanned_pdf(pdf)
    with TestClient(create_app(Wiki(Config.load(cfg.path))), **LOCAL) as client:
        sent = client.post("/api/upload", data={"folder": "fisica", "method": "ocr"},
                           files={"files": ("appunti.pdf", pdf.read_bytes(), "application/pdf")})
        assert sent.status_code == 200 and sent.json()["saved"] == ["fisica/appunti.pdf"]
        bad = client.post("/api/upload", data={"method": "boh"}, files={"files": ("a.pdf", b"x", "application/pdf")})
        assert bad.status_code == 400
        changed = client.post("/api/admin/doc-method", json={"doc": "fisica/appunti.pdf", "method": "text"})
        assert changed.json()["method"] == "text"
        assert client.post("/api/admin/doc-method", json={"doc": "manca.pdf", "method": "ocr"}).status_code == 404


def test_strips_cut_between_lines_of_writing():
    from PIL import Image, ImageDraw

    page = Image.new("L", (600, 800), 255)
    draw = ImageDraw.Draw(page)
    lines = [60 + 90 * n for n in range(8)]  # righe di "scrittura" alte 30 px, spazi di 60 px
    for top in lines:
        draw.rectangle((40, top, 560, top + 30), fill=0)
    buffer = io.BytesIO()
    page.save(buffer, format="PNG")
    pieces = [Image.open(io.BytesIO(piece)) for piece in ocr.strips(buffer.getvalue(), 4)]
    assert len(pieces) == 4 and sum(p.height for p in pieces) == 800
    assert ocr.strips(ocr.sample_image(), 4) == [ocr.sample_image()]  # una riga sola: non si taglia
    edge = 0
    for piece in pieces[:-1]:  # nessun taglio cade dentro una riga
        edge += piece.height
        assert not any(top <= edge <= top + 30 for top in lines)


def gguf(path, size: int = 1000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)


def test_local_ocrs_are_found_and_recognised(tmp_path, monkeypatch):
    """Come sono sistemati davvero sul PC di sviluppo: MiniCPM-OCR con il suo file di bozza, un
    modello generico che vede le immagini, un modello che non le vede, llama-server a parte."""
    from llmwiki import ocr_local

    minicpm = tmp_path / "llama.cpp" / "modelli" / "MiniCPM-OCR-1.0"
    gguf(minicpm / "MiniCPM-OCR-1_0-Q8_0.gguf")
    gguf(minicpm / "mmproj-model-f16-4x.gguf")
    gguf(minicpm / "MiniCPM-OCR-1_0-dspark-draft.gguf")  # accelera, non è un modello da usare
    gguf(tmp_path / "Qwen visione" / "qwen-vl-7b.gguf")
    gguf(tmp_path / "Qwen visione" / "mmproj-qwen-vl.gguf")
    gguf(tmp_path / "solo testo" / "llama-3-8b.gguf")  # senza mmproj non vede le immagini
    monkeypatch.setattr(ocr_local, "default_folders", lambda: [])
    monkeypatch.setattr(ocr_local.shutil, "which", lambda name: None)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "vuota"))

    found = app_module.find_local_ocr(str(tmp_path))
    assert [f["name"] for f in found] == ["MiniCPM-OCR", "qwen-vl-7b"]  # il consigliato prima
    best, other = found
    assert best["recommended"] and best["prompt"] == "Text Recognition:" and best["strips"] == 4
    assert best["mmproj_path"].endswith("mmproj-model-f16-4x.gguf")
    assert not other["known"] and other["strips"] == 0 and "inventare" in other["good_for"]
    assert not best["ok"] and "llama-server" in best["error"]  # manca il programma che lo fa girare

    server = tmp_path / "llama.cpp" / "programma" / "llama-server.exe"
    gguf(server)
    found = app_module.find_local_ocr(f"  ;{tmp_path};")  # cartelle scritte a mano, con spazi
    assert all(f["ok"] and f["llama_server"] == str(server) for f in found)


def test_local_ocr_starts_on_the_gpu_if_there_is_room_else_on_the_cpu(tmp_path, monkeypatch):
    from llmwiki import ocr_local

    files = [tmp_path / name for name in ("llama-server.exe", "MiniCPM-OCR-1_0-Q8_0.gguf", "mmproj.gguf")]
    for path in files:
        gguf(path)
    tried, gpu = [], {"fails": False}

    def fake_start(self, extra):
        tried.append("gpu" if "99" in extra else "cpu")
        self._client = ServerOcr("http://ocr.test/v1", "ocr", transport=vision_server(), prompt=self.prompt)
        return tried[-1] == "cpu" or not gpu["fails"]

    monkeypatch.setattr(ocr_local.LocalOcr, "_start", fake_start)
    monkeypatch.setattr(ocr_local.LocalOcr, "_stop", lambda self: None)
    for free, fails, expected in ((8000, False, ["gpu"]), (900, False, ["cpu"]), (8000, True, ["gpu", "cpu"])):
        tried.clear()
        gpu["fails"] = fails
        monkeypatch.setattr(ocr_local, "free_gpu_mb", lambda free=free: free)
        engine = ocr_local.LocalOcr(*map(str, files), prompt="Text Recognition:")
        assert engine.read(ocr.sample_image()) == "CARNOT 1824"
        assert tried == expected
        assert engine.name == "MiniCPM-OCR (" + ("processore" if expected[-1] == "cpu" else "scheda video") + ")"
        engine.close()

    files[1].unlink()  # modello cancellato o spostato: il documento aspetta, con il passo da fare
    engine = ocr_local.LocalOcr(*map(str, files), prompt="")
    with pytest.raises(OcrError, match="Cerca gli OCR") as missing:
        engine.read(ocr.sample_image())
    assert missing.value.unavailable
    engine.close()


def test_a_server_ocr_that_is_off_is_started_with_its_command(tmp_path):
    flag = tmp_path / "acceso.txt"

    def handler(request: httpx.Request) -> httpx.Response:
        if not flag.exists():
            return httpx.Response(503, text="spento")
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "ocr"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "CARNOT 1824"}}]})

    off = ServerOcr("http://ocr.test/v1", "ocr", transport=httpx.MockTransport(handler))
    with pytest.raises(OcrError):
        off.read(b"png")  # senza comando di avvio resta un OCR spento
    started = ServerOcr("http://ocr.test/v1", "ocr", transport=httpx.MockTransport(handler),
                        start_command=f'echo acceso > "{flag}"')
    assert started.read(b"png") == "CARNOT 1824" and flag.exists()


def test_search_lists_what_reads_first(monkeypatch):
    async def servers():
        return [{"name": "SGLang", "base_url": "http://127.0.0.1:10000/v1", "models": ["cieco", "PaddleOCR-VL-1.6"]}]

    def server_ocr(base_url, model, **options):
        return ServerOcr(base_url, model, transport=vision_server(sees=model != "cieco"), prompt=options.get("prompt", ""))

    local = {"kind": "local", "name": "MiniCPM-OCR", "ok": True, "recommended": True}
    monkeypatch.setattr(app_module, "detect_local_servers", servers)
    monkeypatch.setattr(app_module, "find_local_ocr", lambda folders: [local])
    monkeypatch.setattr(ocr, "ServerOcr", server_ocr)
    monkeypatch.setattr(ocr, "find_tesseract", lambda: [])
    found = asyncio.run(app_module.detect_ocr())
    assert [(f["name"], f["ok"]) for f in found] == [
        ("MiniCPM-OCR", True), ("PaddleOCR-VL-1.6 su SGLang", True), ("cieco su SGLang", False)]
    assert found[1]["prompt"] == "OCR:" and found[1]["strips"] == 4  # riconosciuto dal catalogo
    assert found[2]["prompt"] == ""


def test_ocr_settings_from_the_ui(tmp_path):
    cfg = Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"}}, tmp_path)
    cfg.save()
    with TestClient(create_app(Wiki(Config.load(cfg.path))), **LOCAL) as client:
        settings = client.get("/api/admin/settings").json()
        assert settings["ocr_catalog"]["ocr"][0]["recommended"] and settings["ocr_folder"].endswith("ocr")
        assert client.post("/api/admin/ocr/test").json()["ok"] is False  # niente collegato
        assert client.post("/api/admin/ocr/install").status_code in (404, 405)  # l'app non scarica OCR
        saved = client.post("/api/admin/settings", json={"ocr": {
            "mode": "ocr", "kind": "server", "base_url": "http://127.0.0.1:10000/v1", "model": "Unlimited-OCR-2",
            "start_command": "C:\\AI\\accendi ocr.cmd"}})
        assert saved.status_code == 200 and saved.json()["ocr"]["start_command"].endswith("ocr.cmd")
        local = client.post("/api/admin/settings", json={"ocr": {
            "kind": "local", "name": "MiniCPM-OCR", "model_path": "m.gguf", "mmproj_path": "p.gguf",
            "llama_server": "llama-server.exe", "strips": 4, "folders": "D:\\modelli"}})
        assert local.status_code == 200 and local.json()["ocr"]["strips"] == 4
        assert client.post("/api/admin/settings", json={"ocr": {"mode": "boh"}}).status_code == 400
        assert client.post("/api/admin/settings", json={"ocr": {"kind": "minicpm"}}).status_code == 400
        assert client.post("/api/admin/settings", json={"ocr": {"strips": 99}}).status_code == 400
    saved = Config.load(cfg.path).ocr
    assert saved.kind == "local" and saved.folders == "D:\\modelli" and saved.name == "MiniCPM-OCR"


@pytest.mark.skipif(not ocr.tesseract_places(), reason="Tesseract non installato")
def test_real_tesseract_reads_a_scanned_pdf(tmp_path):
    """Con Tesseract vero, se c'è sul computer: la ricerca lo trova e legge una scansione."""
    found = ocr.find_tesseract()
    assert found and found[0]["ok"]
    pdf = tmp_path / "scansione.pdf"
    scanned_pdf(pdf, pages=1)
    engine = ocr.TesseractOcr(found[0]["path"], found[0]["language"])
    assert any("CARNOT" in line.upper() for line in extract_lines(pdf, engine))
