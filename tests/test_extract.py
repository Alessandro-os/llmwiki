"""Estrazione del testo dai formati che un'azienda usa davvero: PDF, Word, HTML, testo."""

from __future__ import annotations

import asyncio

import pytest

from llmwiki.app import Wiki
from llmwiki.config import Config
from llmwiki.extract import ExtractError, extract_lines


def make_pdf(path, pages: list[str]) -> None:
    """Un PDF minimo scritto a mano (una riga di testo per pagina), senza librerie esterne."""
    objects: list[bytes] = []
    kids = " ".join(f"{4 + 2 * i} 0 R" for i in range(len(pages)))
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    for i, text in enumerate(pages):
        escaped = text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
        stream = f"BT /F1 12 Tf 50 750 Td ({escaped}) Tj ET".encode("cp1252")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents {5 + 2 * i} 0 R "
                       f"/Resources << /Font << /F1 3 0 R >> >> >>".encode())
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def test_pdf_pages_become_citable_lines(tmp_path):
    pdf = tmp_path / "contratto.pdf"
    make_pdf(pdf, ["Contratto di fornitura n. 2026/014", "Penale del 2% per ogni settimana di ritardo"])
    lines = extract_lines(pdf)
    assert "=== Pagina 1 ===" in lines and "=== Pagina 2 ===" in lines
    assert any("2026/014" in line for line in lines)
    assert lines.index("=== Pagina 2 ===") < next(i for i, line in enumerate(lines) if "Penale del 2%" in line)

    empty = tmp_path / "scansione.pdf"
    make_pdf(empty, [""])
    with pytest.raises(ExtractError, match="OCR"):
        extract_lines(empty)


def test_docx_paragraphs_and_tables(tmp_path):
    import docx

    document = docx.Document()
    document.add_heading("Policy trasferte", 1)
    document.add_paragraph("Il rimborso chilometrico è di 0,45 euro al chilometro.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text, table.cell(0, 1).text = "Voce", "Limite"
    table.cell(1, 0).text, table.cell(1, 1).text = "Hotel", "140 euro a notte"
    target = tmp_path / "policy_trasferte.docx"
    document.save(str(target))
    lines = extract_lines(target)
    assert "Policy trasferte" in lines[0]
    assert any("0,45 euro" in line for line in lines)
    assert "Hotel | 140 euro a notte" in lines


def test_html_text_encodings_and_long_lines(tmp_path):
    html = tmp_path / "pagina.html"
    html.write_text("<html><head><style>p{color:red}</style><script>var x = 1;</script></head>"
                    "<body><h1>Listino</h1><p>Valvola VX-200: 84 euro</p></body></html>", encoding="utf-8")
    assert extract_lines(html) == ["Listino", "", "Valvola VX-200: 84 euro"]

    latin = tmp_path / "vecchio.txt"
    latin.write_bytes("Società per azioni: capitale già versato".encode("cp1252"))
    assert extract_lines(latin) == ["Società per azioni: capitale già versato"]

    long_line = tmp_path / "lungo.md"
    long_line.write_text("parola " * 200, encoding="utf-8")
    lines = extract_lines(long_line)
    assert len(lines) > 3 and all(len(line) <= 240 for line in lines)  # righe citabili, non muri di testo

    with pytest.raises(ExtractError):
        extract_lines(tmp_path / "foto.png")


def test_real_formats_and_accented_names_go_through_the_index(tmp_path):
    import docx

    cfg = Config.from_dict({"llm": {"provider": "mock"}, "verify": {"judge": "llm"}}, tmp_path)
    folder = cfg.docs_dir / "Società & Qualità"
    folder.mkdir(parents=True)
    make_pdf(folder / "verbale qualità.pdf", ["La soglia di difettosita scende allo 0,3% dal 2027"])
    document = docx.Document()
    document.add_paragraph("Il comitato qualità si riunisce ogni trimestre.")
    document.save(str(folder / "comitato.docx"))
    (folder / "immagine.png").write_bytes(b"\x89PNG")  # formato non supportato: ignorato, non un errore

    async def scenario():
        wiki = Wiki(cfg)
        status = await wiki.indexer.run_once()
        assert status["ready"] == 2 and status["error"] == 0 and status["total"] == 2
        hits = wiki.tools.search("soglia difettosita")["results"]
        assert hits and hits[0]["doc"] == "Società & Qualità/verbale qualità.pdf"
        assert "0,3%" in wiki.tools.read_document("Società & Qualità/verbale qualità.pdf")
        assert wiki.tools.list_folder("Società & Qualità")["document_count"] == 2
        await wiki.aclose()

    asyncio.run(scenario())
