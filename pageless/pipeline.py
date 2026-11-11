"""Turns a composer's raw steps into validated browser events.

Only validated steps become events. A failed step is retried (`retries_per_step` times), then
replaced with a deterministic fallback. If the outline itself can't be validated, the whole page
switches to the deterministic fallback page.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from dataclasses import dataclass, field

from .catalog import CATALOG
from .composer import Composer, FallbackComposer, Hint
from .config import Settings
from .fallback import fallback_section
from .render import render_section
from .retriever import Retrieved
from .validator import Accepted, PageValidator, Section, ValidationFailure, clean_text

log = logging.getLogger(__name__)


@dataclass
class Event:
    name: str
    data: dict

    def sse(self) -> str:
        return f"event: {self.name}\ndata: {json.dumps(self.data, separators=(',', ':'))}\n\n"

    def as_dict(self) -> dict:
        return {"event": self.name, "data": self.data}


@dataclass
class PipelineResult:
    composer: str = ""
    failures: list[str] = field(default_factory=list)
    retries: int = 0

    @property
    def valid(self) -> bool:
        """True only if every step passed validation; only valid pages may join a version pool."""
        return not self.failures

    def fail(self, message: str) -> None:
        log.info("pipeline failure: %s", message)
        self.failures.append(message)


async def run_pipeline(ctx: Retrieved, composer: Composer, settings: Settings,
                       result: PipelineResult | None = None) -> AsyncIterator[Event]:
    result = result if result is not None else PipelineResult()
    result.composer = composer.name
    yield Event("page.start", {"path": ctx.route.path, "title": ctx.route.title, "site": ctx.profile.name})

    validator = PageValidator(ctx, settings)
    try:
        async for event in _play(ctx, composer, validator, settings, result):
            yield event
    except Exception as exc:  # e.g. the model server went away mid-stream
        log.exception("composer %s crashed", composer.name)
        result.fail(f"composer error: {exc}")

    if not validator.outlined:
        validator = PageValidator(ctx, settings)
        async for event in _play(ctx, FallbackComposer(), validator, settings, result):
            yield event

    for section in validator.unfilled():
        result.fail(f"section {section.id!r} was planned but never added")
        yield _replace(ctx, validator, section)

    yield Event("page.done", {"valid": result.valid})


async def _play(ctx: Retrieved, composer: Composer, validator: PageValidator, settings: Settings,
                result: PipelineResult) -> AsyncIterator[Event]:
    count = 0
    started: dict[str, set[str]] = {}  # sections announced by hints -> text fields already sent
    async with aclosing(composer.steps(ctx)) as steps:
        async for raw in steps:
            if isinstance(raw, Hint):
                for event in _hint_events(validator, raw, started, settings):
                    yield event
                continue
            if count >= settings.max_steps:
                result.fail(f"more than {settings.max_steps} steps; stopped")
                return
            count += 1

            accepted, error = await _accept(validator, raw, composer, settings, result)
            if accepted is not None:
                for event in _events(ctx, validator, accepted, started):
                    yield event
                continue

            result.fail(error)
            if not validator.outlined:
                return  # caller switches to the deterministic page
            target = raw.get("id") if isinstance(raw, dict) else None
            section = validator.sections.get(target) if isinstance(target, str) else None
            if isinstance(raw, dict) and raw.get("type") == "add" and section and not section.added:
                yield _replace(ctx, validator, section)
            # Failed moves and failed adds of unplanned sections are dropped.


def _hint_events(validator: PageValidator, hint: Hint, started: dict[str, set[str]],
                 settings: Settings) -> list[Event]:
    """Early, pre-validation feedback: only for planned, unplaced sections, and only escaped text."""
    section = validator.sections.get(hint.id)
    if section is None or section.added:
        return []
    if hint.kind == "start" and hint.id not in started:
        started[hint.id] = set()
        return [Event("section.start", _placement(validator, section))]
    if hint.kind == "text" and hint.id in started and hint.field not in started[hint.id]:
        if hint.field not in CATALOG[section.component].text_fields:
            return []
        text = clean_text(hint.text or "")[: settings.max_heading_chars]
        if text:
            started[hint.id].add(hint.field)
            return [Event("section.text", {"id": hint.id, "field": hint.field, "text": text})]
    return []


async def _accept(validator: PageValidator, raw: object, composer: Composer, settings: Settings,
                  result: PipelineResult) -> tuple[Accepted | None, str]:
    try:
        return validator.validate(raw), ""
    except ValidationFailure as exc:
        error = str(exc)
    for _ in range(settings.retries_per_step):
        retried = await composer.retry(raw, error)
        if retried is None:
            break
        result.retries += 1
        try:
            return validator.validate(retried), ""
        except ValidationFailure as exc:
            error = str(exc)
    return None, error


def _placement(validator: PageValidator, section: Section) -> dict:
    return {"id": section.id, "component": section.component, "span": section.span,
            "order": validator.position(section.id)}


def _events(ctx: Retrieved, validator: PageValidator, accepted: Accepted,
            started: dict[str, set[str]]) -> list[Event]:
    if accepted.kind == "outline":
        return [Event("layout.outline", {"sections": validator.layout()})]
    section = accepted.section
    if accepted.kind == "move":
        return [Event("layout.move", {"id": section.id, "layout": validator.layout()})]

    placement = _placement(validator, section)
    sent = started.get(section.id)
    events = [] if sent is not None else [Event("section.start", placement)]
    for name in CATALOG[section.component].text_fields:
        if name in accepted.props and name not in (sent or ()):
            events.append(Event("section.text", {"id": section.id, "field": name, "text": accepted.props[name]}))
    html = render_section(section.component, accepted.props, ctx)
    events.append(Event("section.ready", {**placement, "html": html}))
    return events


def _replace(ctx: Retrieved, validator: PageValidator, section: Section) -> Event:
    component, props = fallback_section(section.component, ctx)
    props = validator.place_fallback(section.id, component, props)
    html = render_section(component, props, ctx)
    return Event("section.replace", {**_placement(validator, section), "html": html})


def final_layout(events: list[Event]) -> list[dict]:
    """Fold an event sequence into the finished page, for server-rendered HTML."""
    sections: dict[str, dict] = {}
    for event in events:
        d = event.data
        if event.name == "layout.outline":
            for s in d["sections"]:
                sections[s["id"]] = dict(s)
        elif event.name in ("section.ready", "section.replace"):
            sections.setdefault(d["id"], {}).update(
                {k: d[k] for k in ("id", "component", "span", "order", "html")})
        elif event.name == "layout.move":
            for s in d["layout"]:
                if s["id"] in sections:
                    sections[s["id"]].update(span=s["span"], order=s["order"])
    return sorted((s for s in sections.values() if "html" in s), key=lambda s: s["order"])
