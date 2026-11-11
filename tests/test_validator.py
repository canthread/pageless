import pytest

from pageless.fallback import fallback_spec
from pageless.validator import PageValidator, ValidationFailure

OUTLINE = {"type": "outline", "sections": [
    {"id": "intro", "component": "Hero", "span": 12},
    {"id": "history", "component": "Timeline", "span": 12},
]}


@pytest.fixture
def v(ctx_for, settings):
    validator = PageValidator(ctx_for("/about"), settings)
    validator.validate(OUTLINE)
    return validator


def test_fallback_specs_validate(ctx_for, settings):
    for path in ("/", "/about", "/projects", "/contact"):
        validator = PageValidator(ctx_for(path), settings)
        for step in fallback_spec(ctx_for(path))["steps"]:
            validator.validate(step)
        assert validator.unfilled() == []


def test_spec_example_flow(v):
    v.validate({"type": "add", "id": "intro", "props": {"heading": "Background", "contentId": "bio_short"}})
    v.validate({"type": "add", "id": "history", "props": {"contentIds": ["exp_acme", "edu_state"]}})
    v.validate({"type": "add", "id": "next", "component": "LinkList", "span": 4,
                "props": {"routes": ["/projects", "/contact"]}})
    v.validate({"type": "move", "id": "history", "span": 8})
    assert [(s["id"], s["span"]) for s in v.layout()] == [("intro", 12), ("history", 8), ("next", 4)]
    v.validate({"type": "move", "id": "next", "order": 0})
    assert [s["id"] for s in v.layout()] == ["next", "intro", "history"]


def test_outline_must_come_first(ctx_for, settings):
    v = PageValidator(ctx_for("/about"), settings)
    with pytest.raises(ValidationFailure, match="first step"):
        v.validate({"type": "add", "id": "x", "component": "Hero", "span": 12,
                    "props": {"heading": "Hi", "contentId": "bio_short"}})


@pytest.mark.parametrize("step, message", [
    ("not a step", "schema"),
    ({"type": "explode"}, "schema"),
    ({"type": "add", "id": "intro", "props": {"heading": "Hi", "contentId": "bio_short", "onclick": "x"}}, "props"),
    ({"type": "add", "id": "intro", "props": {"heading": "Hi", "contentId": "note_private"}}, "not in the retrieved set"),
    ({"type": "add", "id": "intro", "props": {"heading": "Hi", "contentId": "made_up"}}, "not in the retrieved set"),
    ({"type": "add", "id": "intro", "component": "Timeline", "props": {"contentIds": ["exp_acme"]}}, "outlined as Hero"),
    ({"type": "add", "id": "history", "props": {"contentIds": ["bio_short"]}}, "cannot show bio"),
    ({"type": "add", "id": "intro", "span": 13, "props": {"heading": "Hi", "contentId": "bio_short"}}, "span 13"),
    ({"type": "add", "id": "intro", "props": {"heading": "x" * 120, "contentId": "bio_short"}}, "longer than"),
    ({"type": "add", "id": "intro", "props": {"heading": "‮\x00 ", "contentId": "bio_short"}}, "empty"),
    ({"type": "add", "id": "evil", "component": "Script", "span": 12, "props": {}}, "unknown component"),
    ({"type": "add", "id": "new", "props": {}}, "needs a component"),
    ({"type": "add", "id": "nav", "component": "LinkList", "span": 4, "props": {"routes": ["/admin"]}}, "not a known route"),
    ({"type": "add", "id": "nav", "component": "LinkList", "span": 4,
      "props": {"urls": ["https://evil.example"]}}, "not approved"),
    ({"type": "add", "id": "nav", "component": "LinkList", "span": 4,
      "props": {"urls": ["javascript:alert(1)"]}}, "not approved"),
    ({"type": "move", "id": "intro", "span": 6}, "not a placed component"),
    ({"type": "move", "id": "ghost", "span": 6}, "not a placed component"),
    ({"type": "outline", "sections": [{"id": "a", "component": "Hero", "span": 12}]}, "already sent"),
])
def test_rejections(v, step, message):
    with pytest.raises(ValidationFailure, match=message):
        v.validate(step)


def test_rejected_step_does_not_change_state(v):
    before = v.layout()
    with pytest.raises(ValidationFailure):
        v.validate({"type": "add", "id": "intro", "props": {"heading": "Hi", "contentId": "nope"}})
    assert v.layout() == before and not v.sections["intro"].added


def test_text_is_cleaned(v):
    accepted = v.validate({"type": "add", "id": "intro",
                           "props": {"heading": "  Hello\n\tthere​ ", "contentId": "bio_short"}})
    assert accepted.props["heading"] == "Hello there"


def test_bad_moves(v):
    v.validate({"type": "add", "id": "intro", "props": {"heading": "Hi", "contentId": "bio_short"}})
    with pytest.raises(ValidationFailure, match="outside the page"):
        v.validate({"type": "move", "id": "intro", "order": 5})
    with pytest.raises(ValidationFailure, match="span or an order"):
        v.validate({"type": "move", "id": "intro"})


def test_repeated_ids_are_deduplicated(v):
    accepted = v.validate({"type": "add", "id": "history",
                           "props": {"contentIds": ["exp_acme", "edu_state", "exp_acme"]}})
    assert accepted.props["contentIds"] == ["exp_acme", "edu_state"]


def test_renamed_add_binds_to_outlined_section(v):
    accepted = v.validate({"type": "add", "id": "bio_section", "component": "Hero",
                           "props": {"heading": "Hi", "contentId": "bio_short"}})
    assert accepted.section.id == "intro"
    moved = v.validate({"type": "move", "id": "bio_section", "span": 6})
    assert moved.section.id == "intro" and v.layout()[0]["span"] == 6
    # With nothing left to bind to, an unplanned add becomes a new full-width section.
    accepted = v.validate({"type": "add", "id": "links", "component": "LinkList",
                           "props": {"routes": ["/"]}})
    assert accepted.section.span == 12 and v.layout()[-1]["id"] == "links"
    with pytest.raises(ValidationFailure, match="only one Hero"):
        v.validate({"type": "add", "id": "hero2", "component": "Hero",
                    "props": {"heading": "Again", "contentId": "bio_short"}})
