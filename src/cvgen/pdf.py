"""LibreOffice PDF export and page counting."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


class PdfExportError(RuntimeError):
    pass


def find_soffice() -> str | None:
    return shutil.which("soffice") or shutil.which("libreoffice")


def export_pdf(docx_path: Path, *, soffice: str | None = None) -> Path:
    """Convert docx_path to a PDF next to it. Raises PdfExportError on failure."""
    binary = soffice or find_soffice()
    if not binary:
        raise PdfExportError(
            "LibreOffice (soffice) was not found. Install it to export PDF, "
            "or pass --no-pdf to write only the .docx."
        )
    docx_path = docx_path.resolve()
    with tempfile.TemporaryDirectory(prefix="cvgen-lo-") as profile_dir:
        profile = Path(profile_dir)
        command = [
            binary,
            f"-env:UserInstallation={profile.as_uri()}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(docx_path.parent),
            str(docx_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
        except subprocess.TimeoutExpired as exc:
            raise PdfExportError(f"LibreOffice timed out while converting {docx_path.name}") from exc
    pdf_path = docx_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf_path.exists():
        detail = (result.stderr or result.stdout or "").strip()
        raise PdfExportError(f"LibreOffice failed for {docx_path.name}: {detail}")
    return pdf_path


def count_pdf_pages(pdf_path: Path) -> int:
    """Page count via pdfinfo when it is installed, otherwise a raw object scan."""
    if shutil.which("pdfinfo"):
        out = subprocess.run(["pdfinfo", str(pdf_path)], capture_output=True, text=True).stdout
        match = re.search(r"^Pages:\s+(\d+)", out, re.MULTILINE)
        if match:
            return int(match.group(1))
    data = pdf_path.read_bytes()
    return len(re.findall(rb"/Type\s*/Page(?!s)", data))
