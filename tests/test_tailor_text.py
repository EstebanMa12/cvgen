from cvgen.tailor import extract_block, html_to_text, slugify

CV_START = "<<<CV_MARKDOWN"
CV_END = "CV_MARKDOWN>>>"


def test_slugify_strips_accents():
    assert slugify("Diseño Senior") == "diseno-senior"


def test_html_to_text_drops_scripts_and_tags():
    html = "<html><style>body{}</style><p>Hello<br>there</p><script>nope()</script></html>"
    text = html_to_text(html)
    assert "Hello" in text
    assert "there" in text
    assert "nope" not in text
    assert "<p>" not in text


def test_extract_block_strips_a_fence():
    raw = f"preamble\n{CV_START}\n```markdown\n# Avery Quinn\n```\n{CV_END}\nafter"
    assert extract_block(raw, CV_START, CV_END) == "# Avery Quinn\n"
