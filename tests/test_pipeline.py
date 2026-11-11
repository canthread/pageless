import asyncio

from pageless.composer import StaticComposer
from pageless.pipeline import PipelineResult, final_layout, run_pipeline


def run(ctx, composer, settings):
    result = PipelineResult()

    async def collect():
        return [e async for e in run_pipeline(ctx, composer, settings, result)]

    return asyncio.run(collect()), result


def names(events):
    return [e.name for e in events]


class RetryingComposer(StaticComposer):
    def __init__(self, spec, fixes):
        super().__init__(spec, "retrying")
        self.fixes = fixes
        self.calls = 0

    async def retry(self, step, error):
        self.calls += 1
        return self.fixes.get(step.get("id"))


class CrashingComposer(StaticComposer):
    async def steps(self, ctx):
        yield {"type": "outline", "sections": [{"id": "intro", "component": "Hero", "span": 12}]}
        raise ConnectionError("ollama went away")


def test_valid_stream(ctx_for, settings):
    spec = {"steps": [
        {"type": "outline", "sections": [{"id": "intro", "component": "Hero", "span": 12}]},
        {"type": "add", "id": "intro", "props": {"heading": "Background", "contentId": "bio_short"}},
        {"type": "add", "id": "next", "component": "LinkList", "span": 4, "props": {"routes": ["/projects"]}},
        {"type": "move", "id": "intro", "span": 8},
    ]}
    events, result = run(ctx_for("/about"), StaticComposer(spec), settings)
    assert names(events) == ["page.start", "layout.outline", "section.start", "section.text", "section.ready",
                             "section.start", "section.ready", "layout.move", "page.done"]
    assert result.valid and events[-1].data == {"valid": True}
    layout = final_layout(events)
    assert [(s["id"], s["span"]) for s in layout] == [("intro", 8), ("next", 4)]


def test_failed_add_is_retried_then_replaced(ctx_for, settings):
    spec = {"steps": [
        {"type": "outline", "sections": [{"id": "intro", "component": "Hero", "span": 12},
                                         {"id": "history", "component": "Timeline", "span": 12}]},
        {"type": "add", "id": "intro", "props": {"heading": "Hi", "contentId": "invented_fact"}},
        {"type": "add", "id": "history", "props": {"contentIds": ["note_private"]}},
    ]}
    fixed_intro = {"type": "add", "id": "intro", "props": {"heading": "Hi", "contentId": "bio_short"}}
    composer = RetryingComposer(spec, {"intro": fixed_intro})
    events, result = run(ctx_for("/about"), composer, settings)
    assert composer.calls == 2  # one retry per failed step
    assert "section.ready" in names(events)
    replaced = [e for e in events if e.name == "section.replace"]
    assert [e.data["id"] for e in replaced] == ["history"]
    assert "note_private" not in replaced[0].data["html"]
    assert not result.valid


def test_invalid_outline_falls_back_to_deterministic_page(ctx_for, settings):
    spec = {"steps": [{"type": "outline", "sections": [{"id": "x", "component": "<script>", "span": 12}]}]}
    events, result = run(ctx_for("/about"), StaticComposer(spec), settings)
    assert names(events)[1] == "layout.outline"
    assert "<script>" not in str([e.data for e in events])
    assert events[-1].name == "page.done" and not result.valid
    assert len(final_layout(events)) >= 3


def test_planned_but_missing_sections_get_fallbacks(ctx_for, settings):
    spec = {"steps": [{"type": "outline", "sections": [{"id": "intro", "component": "Hero", "span": 12},
                                                       {"id": "work", "component": "CardGrid", "span": 12}]}]}
    events, result = run(ctx_for("/projects"), StaticComposer(spec), settings)
    assert [e.data["id"] for e in events if e.name == "section.replace"] == ["intro", "work"]


def test_composer_crash_keeps_placed_sections(ctx_for, settings):
    events, result = run(ctx_for("/about"), CrashingComposer({}), settings)
    assert any("composer error" in f for f in result.failures)
    assert names(events)[-2:] == ["section.replace", "page.done"]


def test_unusable_fallback_component_degrades_to_links(ctx_for, settings):
    # /contact has no assets, so a Gallery slot falls back to navigation links.
    spec = {"steps": [{"type": "outline", "sections": [{"id": "pics", "component": "Gallery", "span": 12}]},
                      {"type": "add", "id": "pics", "props": {"assetIds": ["img_pageless"]}}]}
    events, _ = run(ctx_for("/contact"), StaticComposer(spec), settings)
    replaced = next(e for e in events if e.name == "section.replace")
    assert replaced.data["component"] == "LinkList"


def test_generated_text_is_escaped(ctx_for, settings):
    spec = {"steps": [
        {"type": "outline", "sections": [{"id": "intro", "component": "Hero", "span": 12}]},
        {"type": "add", "id": "intro", "props": {"heading": "<img src=x onerror=alert(1)>", "contentId": "bio_short"}},
    ]}
    events, _ = run(ctx_for("/about"), StaticComposer(spec), settings)
    ready = next(e for e in events if e.name == "section.ready")
    assert "<img" not in ready.data["html"] and "&lt;img" in ready.data["html"]
