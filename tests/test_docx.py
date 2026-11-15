from pathlib import Path

from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT

from cvgen.docx_io import build_document, contact_url, load_docx
from cvgen.layout import STYLES
from cvgen.markdown import parse_markdown, parse_markdown_file

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "cvgen" / "templates"


def test_contact_urls():
    assert contact_url("avery.quinn@example.com") == "mailto:avery.quinn@example.com"
    assert contact_url("github.com/avery-quinn") == "https://github.com/avery-quinn"
    assert contact_url("+1 555 010 0199") == "tel:+15550100199"
    assert contact_url("Port Meridian") is None


def test_comments_are_omitted_from_the_docx(tmp_path: Path):
    model = parse_markdown("# Avery Quinn\n<!-- CVGEN-COMMENT-MARKER -->\n\n## PROFILE\nVisible sentence.\n")
    assert "CVGEN-COMMENT-MARKER" not in str(model)
    docx_path = tmp_path / "comment.docx"
    build_document(model, dict(STYLES["short"]), docx_path)
    blob = "\n".join(paragraph.text for paragraph in Document(docx_path).paragraphs)
    assert "CVGEN-COMMENT-MARKER" not in blob
    assert "Visible sentence." in blob


def test_metadata_and_contact_links(tmp_path: Path):
    model = parse_markdown_file(TEMPLATES / "short-en.md")
    docx_path = tmp_path / "cv.docx"
    build_document(model, dict(STYLES["short"]), docx_path, locale_en="en-US", locale_es="es")
    document = Document(docx_path)
    assert document.core_properties.author == "Avery Quinn"
    assert document.core_properties.language == "en-US"
    targets = [rel.target_ref for rel in document.part.rels.values() if rel.reltype == RT.HYPERLINK]
    assert "mailto:avery.quinn@example.com" in targets
    assert "https://github.com/avery-quinn" in targets


def test_structured_lines_survive_docx(tmp_path: Path):
    model = parse_markdown_file(TEMPLATES / "extended-en.md")
    docx_path = tmp_path / "cv.docx"
    build_document(model, dict(STYLES["extended"]), docx_path)
    loaded = load_docx(docx_path)

    def structured(document):
        rows = []
        for section in document["sections"]:
            for item in section["items"]:
                if item[0] in {"entry", "subentry", "tech"}:
                    rows.append((item[0], item[1], item[2] if len(item) > 2 else ""))
        return rows

    assert loaded["name"] == model["name"]
    assert loaded["headline"] == model["headline"]
    assert structured(loaded) == structured(model)


def test_entry_without_pipe_roundtrip(tmp_path: Path):
    model = parse_markdown("# Test Person\n\n## EXPERIENCE\n**Northwind Labs**\n- Built a service.\n")
    docx_path = tmp_path / "cv.docx"
    build_document(model, dict(STYLES["short"]), docx_path)
    loaded = load_docx(docx_path)
    assert loaded["sections"][0]["items"][0] == ("entry", "Northwind Labs", "")
    assert Document(docx_path).core_properties.author == "Test Person"
