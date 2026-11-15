import re
from pathlib import Path

from cvgen.markdown import parse_markdown_file
from cvgen.verify import fact_check

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "cvgen" / "templates"
CVS = ("short-en.md", "short-es.md", "extended-en.md", "extended-es.md")


def test_example_lines_are_in_the_consolidated_source():
    source = (TEMPLATES / "consolidated.md").read_text(encoding="utf-8")
    for name in CVS:
        visible = re.sub(r"<!--.*?-->", "", (TEMPLATES / name).read_text(encoding="utf-8"), flags=re.DOTALL)
        for line in visible.splitlines():
            stripped = line.strip()
            assert stripped in source, f"{name} has a line the source does not contain: {stripped}"


def test_example_cvs_have_no_invented_facts():
    source = (TEMPLATES / "consolidated.md").read_text(encoding="utf-8")
    for name in CVS:
        errors = fact_check(parse_markdown_file(TEMPLATES / name), source)
        assert errors == [], (name, errors)
