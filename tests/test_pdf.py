import shutil
from pathlib import Path

import pytest

from cvgen.cli import main
from cvgen.pdf import count_pdf_pages

soffice_missing = shutil.which("soffice") is None and shutil.which("libreoffice") is None


def test_page_count_falls_back_without_pdfinfo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr("cvgen.pdf.shutil.which", lambda _name: None)
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"<< /Type /Pages >> << /Type /Page >> << /Type /Page >>")
    assert count_pdf_pages(pdf) == 2


@pytest.mark.pdf
@pytest.mark.skipif(soffice_missing, reason="LibreOffice is not installed")
def test_example_pdfs_meet_page_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    assert main(["init"]) == 0
    assert main(["build", "short-en", "extended-en"]) == 0
    short_pdf = tmp_path / "out" / "avery-quinn-short-en.pdf"
    extended_pdf = tmp_path / "out" / "avery-quinn-extended-en.pdf"
    assert short_pdf.is_file()
    assert extended_pdf.is_file()
    assert count_pdf_pages(short_pdf) <= 1
    assert count_pdf_pages(extended_pdf) <= 2
    assert (tmp_path / "out" / "avery-quinn-short-en.docx").is_file()
