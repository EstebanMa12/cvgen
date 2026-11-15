"""Render a parsed CV to a Harvard-style .docx, and read one back."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.document import Document as DocumentObject
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.text.paragraph import Paragraph

from cvgen.markdown import CvModel, Section, detect_language, extract_skills

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def set_bottom_border(paragraph: Paragraph, size: int = 6, space: int = 2) -> None:
    """Add a thin bottom border (the horizontal rule under the header and headings)."""
    p_pr = paragraph._p.get_or_add_pPr()
    p_bdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), "000000")
    p_bdr.append(bottom)
    p_pr.append(p_bdr)


def styled_run(
    paragraph: Paragraph,
    text: str,
    size: float,
    *,
    font: str,
    bold: bool = False,
    italic: bool = False,
):
    run = paragraph.add_run(text)
    run.bold = bold
    run.italic = italic
    run.font.name = font
    run.font.size = Pt(size)
    return run


def add_hyperlink(paragraph: Paragraph, url: str, text: str, size: float, *, font: str) -> None:
    """Append a clickable external hyperlink that uses the body font."""
    r_id = paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True)
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), r_id)
    run = OxmlElement("w:r")
    r_pr = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    for attr in ("w:ascii", "w:hAnsi", "w:cs"):
        fonts.set(qn(attr), font)
    r_pr.append(fonts)
    for tag in ("w:sz", "w:szCs"):
        el = OxmlElement(tag)
        el.set(qn("w:val"), str(int(size * 2)))
        r_pr.append(el)
    run.append(r_pr)
    text_el = OxmlElement("w:t")
    text_el.set(qn("xml:space"), "preserve")
    text_el.text = text
    run.append(text_el)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def contact_url(token: str) -> str | None:
    """Return a URL for an email, profile, web address or phone token."""
    token = token.strip()
    if re.fullmatch(r"[\w.+-]+@[\w-]+\.[\w.-]+", token):
        return f"mailto:{token}"
    if re.match(r"https?://", token):
        return token
    if re.match(r"(www\.)?(linkedin\.com|github\.com|gitlab\.com)/", token) or re.match(r"www\.", token):
        return f"https://{token}"
    if re.fullmatch(r"\+?[\d\s()-]{7,}", token):
        return "tel:" + re.sub(r"[^\d+]", "", token)
    return None


def add_contact_line(paragraph: Paragraph, line: str, size: float, *, font: str) -> None:
    """Render "a | b | c" with clickable tokens. [text](url) is also a link."""
    tokens = [token.strip() for token in line.split("|")]
    for index, token in enumerate(tokens):
        if index:
            styled_run(paragraph, " | ", size, font=font)
        md_link = re.fullmatch(r"\[(.+?)\]\((.+?)\)", token)
        if md_link:
            add_hyperlink(paragraph, md_link.group(2), md_link.group(1), size, font=font)
            continue
        url = contact_url(token)
        if url:
            add_hyperlink(paragraph, url, token, size, font=font)
        else:
            styled_run(paragraph, token, size, font=font)


def add_rich_text(paragraph: Paragraph, text: str, size: float, *, font: str, italic: bool = False) -> None:
    """Render inline **bold** and *italic* into runs."""
    for token in re.split(r"(\*\*.+?\*\*|\*[^*]+?\*)", text):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            styled_run(paragraph, token[2:-2], size, font=font, bold=True, italic=italic)
        elif token.startswith("*") and token.endswith("*"):
            styled_run(paragraph, token[1:-1], size, font=font, italic=True)
        else:
            styled_run(paragraph, token, size, font=font, italic=italic)


def set_core_properties(
    document: DocumentObject,
    model: CvModel,
    *,
    locale_es: str,
    locale_en: str,
) -> None:
    """Fill author, title and skill keywords. Some ATS readers pick these up."""
    lang = detect_language(model)
    props = document.core_properties
    props.author = model["name"]
    props.last_modified_by = model["name"]
    label = "Hoja de vida" if lang == "es" else "Curriculum Vitae"
    props.title = f"{model['name']} — {model['headline'] or label}"[:255]
    props.subject = label
    keywords = ""
    for skill in extract_skills(model):
        candidate = f"{keywords}, {skill}" if keywords else skill
        if len(candidate) > 255:
            break
        keywords = candidate
    props.keywords = keywords
    props.language = locale_es if lang == "es" else locale_en
    props.comments = "Generated by cvgen from Markdown"


def build_document(
    model: CvModel,
    style: dict[str, float],
    output_path: Path,
    *,
    font: str = "Times New Roman",
    locale_es: str = "es",
    locale_en: str = "en-US",
) -> None:
    """Write one .docx. style values are point sizes, inches and line spacing."""
    document = Document()

    for section in document.sections:
        section.top_margin = Inches(style["margin"])
        section.bottom_margin = Inches(style["margin"])
        section.left_margin = Inches(style["margin"])
        section.right_margin = Inches(style["margin"])
        content_width = section.page_width - section.left_margin - section.right_margin

    normal = document.styles["Normal"]
    normal.font.name = font
    normal.font.size = Pt(style["body_size"])
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = style["line_spacing"]
    try:
        bullet_style = document.styles["List Bullet"]
    except KeyError:
        bullet_style = None
    if bullet_style is not None:
        bullet_style.font.name = font
        bullet_style.font.size = Pt(style["body_size"])

    def tabbed_paragraph(
        left: str,
        right: str,
        size: float,
        *,
        bold: bool = False,
        italic: bool = False,
        before: float = 0,
        after: float = 0,
    ) -> None:
        paragraph = document.add_paragraph()
        paragraph.paragraph_format.space_before = Pt(before)
        paragraph.paragraph_format.space_after = Pt(after)
        paragraph.paragraph_format.tab_stops.add_tab_stop(content_width, WD_TAB_ALIGNMENT.RIGHT)
        styled_run(paragraph, left, size, font=font, bold=bold, italic=italic)
        if right:
            styled_run(paragraph, "\t" + right, size, font=font, bold=bold, italic=italic)

    name = document.add_paragraph()
    name.alignment = WD_ALIGN_PARAGRAPH.CENTER
    name.paragraph_format.space_after = Pt(2)
    styled_run(name, model["name"], style["name_size"], font=font, bold=True)

    if model["headline"]:
        headline = document.add_paragraph()
        headline.alignment = WD_ALIGN_PARAGRAPH.CENTER
        headline.paragraph_format.space_after = Pt(1)
        styled_run(headline, model["headline"], style["headline_size"], font=font, italic=True)

    for index, contact_line in enumerate(model["contact"]):
        paragraph = document.add_paragraph()
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        paragraph.paragraph_format.space_after = Pt(1)
        add_contact_line(paragraph, contact_line, style["contact_size"], font=font)
        if index == len(model["contact"]) - 1:
            set_bottom_border(paragraph, size=4, space=4)

    for section in model["sections"]:
        heading = document.add_paragraph()
        heading.paragraph_format.space_before = Pt(style["heading_before"])
        heading.paragraph_format.space_after = Pt(style["heading_after"])
        styled_run(heading, section["title"].upper(), style["heading_size"], font=font, bold=True)
        set_bottom_border(heading, size=4, space=2)

        for item in section["items"]:
            kind = item[0]
            if kind == "entry":
                tabbed_paragraph(
                    item[1],
                    item[2],
                    style["body_size"],
                    bold=True,
                    before=style["entry_before"],
                    after=0,
                )
            elif kind == "subentry":
                tabbed_paragraph(
                    item[1],
                    item[2],
                    style["body_size"],
                    italic=True,
                    before=0,
                    after=style["bullet_after"],
                )
            elif kind == "bullet":
                paragraph = document.add_paragraph(style="List Bullet")
                paragraph.paragraph_format.space_after = Pt(style["bullet_after"])
                paragraph.paragraph_format.left_indent = Inches(0.25)
                paragraph.paragraph_format.first_line_indent = Inches(-0.13)
                add_rich_text(paragraph, item[1], style["body_size"], font=font)
            elif kind == "tech":
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_before = Pt(1)
                paragraph.paragraph_format.space_after = Pt(style["tech_after"])
                styled_run(paragraph, item[1], style["tech_size"], font=font, italic=True)
            elif kind == "text":
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_after = Pt(style["body_after"])
                add_rich_text(paragraph, item[1], style["body_size"], font=font)
            else:
                raise ValueError(f"Unknown CV item kind {kind!r}")

    set_core_properties(document, model, locale_es=locale_es, locale_en=locale_en)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(output_path)


def _has_bottom_border(paragraph: Paragraph) -> bool:
    p_pr = paragraph._p.pPr
    if p_pr is None:
        return False
    return p_pr.find(f"{_W_NS}pBdr") is not None


def load_docx(path: Path) -> CvModel:
    """Rebuild the markdown model from a .docx written by build_document."""
    document = Document(path)
    model: CvModel = {"name": "", "headline": "", "contact": [], "sections": []}
    section: Section | None = None
    paragraphs = [paragraph for paragraph in document.paragraphs if paragraph.text.strip()]
    for index, paragraph in enumerate(paragraphs):
        text = paragraph.text.strip()
        runs = [run for run in paragraph.runs if run.text.strip()]
        all_bold = bool(runs) and all(run.bold for run in runs)
        all_italic = bool(runs) and all(run.italic for run in runs)
        if index == 0:
            model["name"] = text
            continue
        if all_bold and _has_bottom_border(paragraph) and text.isupper():
            section = {"title": text, "items": []}
            model["sections"].append(section)
            continue
        if section is None:
            if all_italic and not model["contact"]:
                model["headline"] = text
            else:
                model["contact"].append(text)
            continue
        if all_bold and not paragraph.style.name.startswith("List") and "\t" not in paragraph.text:
            section["items"].append(("entry", text, ""))
            continue
        if "\t" in paragraph.text:
            left, right = paragraph.text.split("\t", 1)
            kind = "entry" if all_bold else "subentry"
            section["items"].append((kind, left.strip(), right.strip()))
            continue
        if paragraph.style.name.startswith("List"):
            bullet = text
            if runs and runs[0].bold:
                rest = "".join(run.text for run in paragraph.runs[1:]).strip()
                bullet = f"**{runs[0].text.strip()}** {rest}".strip()
            section["items"].append(("bullet", bullet))
            continue
        if all_italic:
            section["items"].append(("tech", text))
            continue
        section["items"].append(("text", text))
    return model
