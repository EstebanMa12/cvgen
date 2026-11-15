from cvgen.markdown import detect_language, parse_markdown, strip_comments

SAMPLE = """
<!-- secret note
that spans lines -->
# Avery Quinn
> Backend Engineer | Python
Port Meridian | avery.quinn@example.com

## EXPERIENCE
**Northwind Labs** | Port Meridian
**Side project**
*Software Engineer | March 2021 – Present*
*Technologies: Python, FastAPI*
- Shipped **FastAPI** for *4* teams.
A plain profile sentence.

## SKILLS
- **Backend:** FastAPI, PostgreSQL
"""


def test_strip_comments_removes_multiline_notes():
    assert "secret note" not in strip_comments("before <!-- secret note\nstill --> after")
    assert strip_comments("before <!-- secret note\nstill --> after").strip() == "before  after"


def test_parse_grammar():
    model = parse_markdown(SAMPLE)
    assert model["name"] == "Avery Quinn"
    assert model["headline"] == "Backend Engineer | Python"
    assert model["contact"] == ["Port Meridian | avery.quinn@example.com"]
    experience = model["sections"][0]
    assert experience["title"] == "EXPERIENCE"
    assert experience["items"][0] == ("entry", "Northwind Labs", "Port Meridian")
    assert experience["items"][1] == ("entry", "Side project", "")
    assert experience["items"][2] == ("subentry", "Software Engineer", "March 2021 – Present")
    assert experience["items"][3] == ("tech", "Technologies: Python, FastAPI")
    assert experience["items"][4][0] == "bullet"
    assert "**FastAPI**" in experience["items"][4][1]
    assert experience["items"][5] == ("text", "A plain profile sentence.")
    assert "secret note" not in str(model)
    assert detect_language(model) == "en"


def test_spanish_headings_select_language():
    model = parse_markdown("## EXPERIENCIA PROFESIONAL\n- Una viñeta\n")
    assert detect_language(model) == "es"
