from pathlib import Path

from cvgen.config import default_config
from cvgen.markdown import parse_markdown
from cvgen.verify import fact_check, keyword_check

SOURCE = """
Avery Quinn
Northwind Labs
Port Meridian
Software Engineer
March 2021 – Present
Python, FastAPI, PostgreSQL
4 internal teams
30%
"""

BASE_CV = """
# Avery Quinn
> Backend Engineer | Python
Port Meridian | avery.quinn@example.com

## EXPERIENCE
**Northwind Labs** | Port Meridian
*Software Engineer | March 2021 – Present*
- Built a FastAPI service for 4 internal teams and cut latency by 30%.
*Technologies: Python, FastAPI, PostgreSQL*

## SKILLS
- **Backend:** Python, FastAPI
"""


def _errors(extra: str) -> list[str]:
    return fact_check(parse_markdown(BASE_CV + extra), SOURCE)


def test_source_facts_pass():
    assert fact_check(parse_markdown(BASE_CV), SOURCE) == []


def test_invented_employer_title_date_number_and_tech_fail():
    errors = _errors(
        """
## EXPERIENCE
**Initech** | Port Meridian
*Chief Astronaut | April 1999 – Present*
- Led 99 launches with Oracle.
*Technologies: Oracle*
"""
    )
    blob = "\n".join(errors)
    assert "Initech" in blob
    assert "Chief Astronaut" in blob
    assert "April 1999" in blob
    assert "99" in blob
    assert "Oracle" in blob


def test_known_tech_in_a_bullet_fails_when_the_source_lacks_it():
    errors = _errors("- Deployed the service to Kubernetes.\n")
    assert any("Kubernetes" in error for error in errors)


def test_keyword_rules():
    text = "Avery Quinn builds with FastAPI"
    assert keyword_check(text, required=["FastAPI"], forbidden=["TODO"]) == []
    missing = keyword_check(text, required=["Lantern"], forbidden=["TODO"])
    assert missing and "Lantern" in missing[0]
    forbidden = keyword_check(text + " TODO later", required=[], forbidden=["TODO"])
    assert forbidden and "TODO" in forbidden[0]


def test_rephrased_bullet_without_new_facts_passes(tmp_path: Path):
    cv = """
# Avery Quinn
## EXPERIENCE
**Northwind Labs** | Port Meridian
*Software Engineer | March 2021 – Present*
- Delivered the FastAPI API used by 4 internal teams. Latency fell 30%.
*Technologies: Python, FastAPI, PostgreSQL*
"""
    assert fact_check(parse_markdown(cv), SOURCE) == []
    config = default_config(tmp_path)
    assert config.person_name == ""
