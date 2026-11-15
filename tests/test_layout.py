from cvgen.layout import FIT_FACTOR, MIN_BODY_SIZE, STYLES, fit_style, shrink_style


def test_shrink_does_not_mutate_and_stops_at_the_floor():
    original = dict(STYLES["short"])
    snapshot = dict(original)
    current = original
    seen = []
    for _ in range(10):
        nxt = shrink_style(current, "short")
        assert original == snapshot
        if nxt is None:
            break
        assert nxt["body_size"] < current["body_size"]
        assert nxt["body_size"] >= MIN_BODY_SIZE["short"] - 1e-9
        seen.append(nxt["body_size"])
        current = nxt
    assert seen
    assert shrink_style(current, "short") is None
    assert current["body_size"] * FIT_FACTOR < MIN_BODY_SIZE["short"]


def test_fit_shrinks_until_the_fake_page_count_fits():
    calls = {"n": 0}

    def measure(style):
        calls["n"] += 1
        return 2 if calls["n"] < 3 else 1

    result = fit_style(dict(STYLES["short"]), "short", measure, limit=1)
    assert result.ok
    assert result.steps == 2
    assert result.pages == 1
    assert calls["n"] == 3


def test_fit_fails_when_the_floor_still_overflows():
    result = fit_style(dict(STYLES["short"]), "short", lambda _style: 5, limit=1)
    assert not result.ok
    assert result.pages == 5
    assert result.steps >= 1
    assert result.style["body_size"] >= MIN_BODY_SIZE["short"]


def test_extended_floor_is_higher_than_short():
    assert MIN_BODY_SIZE["extended"] > MIN_BODY_SIZE["short"]
