"""Checks each streamed step against the catalog and the retrieved records before it reaches the browser.

The validator is stateful: it tracks the planned and placed sections, so it can check that adds
match the outline and that moves target a component that exists. State only changes when a step
is accepted.
"""

import re
from dataclasses import dataclass

from pydantic import ValidationError

from .catalog import CATALOG
from .config import Settings
from .retriever import Retrieved
from .spec import STEP_ADAPTER, AddStep, MoveStep, OutlineStep

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")


class ValidationFailure(Exception):
    pass


def clean_text(text: str) -> str:
    """Strip control and bidi characters and collapse whitespace. HTML escaping happens at render time."""
    return " ".join(_CONTROL.sub(" ", text).split())


@dataclass
class Section:
    id: str
    component: str
    span: int
    added: bool = False


@dataclass
class Accepted:
    kind: str  # "outline" | "add" | "move"
    section: Section | None = None
    props: dict | None = None


class PageValidator:
    def __init__(self, ctx: Retrieved, settings: Settings):
        self.ctx = ctx
        self.grid = settings.grid_columns
        self.max_heading = settings.max_heading_chars
        self.sections: dict[str, Section] = {}
        self.order: list[str] = []
        self.outlined = False
        # Model ids that were bound to a differently named outlined section (see _add).
        self.aliases: dict[str, str] = {}

    # -- public API ---------------------------------------------------------------------------

    def validate(self, raw: object) -> Accepted:
        try:
            step = STEP_ADAPTER.validate_python(raw)
        except ValidationError as exc:
            raise ValidationFailure(f"schema: {_summarize(exc)}") from None
        if isinstance(step, OutlineStep):
            return self._outline(step)
        if not self.outlined:
            raise ValidationFailure("the first step must be an outline")
        if isinstance(step, AddStep):
            return self._add(step)
        return self._move(step)

    def layout(self) -> list[dict]:
        return [{"id": sid, "component": self.sections[sid].component, "span": self.sections[sid].span,
                 "order": i} for i, sid in enumerate(self.order)]

    def position(self, section_id: str) -> int:
        return self.order.index(section_id)

    def unfilled(self) -> list[Section]:
        return [self.sections[sid] for sid in self.order if not self.sections[sid].added]

    def place_fallback(self, section_id: str, component: str, props: dict) -> dict:
        """Place deterministic fallback content in a planned slot. Fallbacks must validate too."""
        section = self.sections[section_id]
        checked = self._check_props(component, props)
        section.component, section.added = component, True
        return checked

    # -- step handlers ------------------------------------------------------------------------

    def _outline(self, step: OutlineStep) -> Accepted:
        if self.outlined:
            raise ValidationFailure("outline was already sent")
        ids = [s.id for s in step.sections]
        if len(set(ids)) != len(ids):
            raise ValidationFailure("outline section ids must be unique")
        for s in step.sections:
            self._check_component(s.component)
            self._check_span(s.span)
        self.sections = {s.id: Section(s.id, s.component, s.span) for s in step.sections}
        self.order = ids
        self.outlined = True
        return Accepted("outline")

    def _add(self, step: AddStep) -> Accepted:
        existing = self.sections.get(self.aliases.get(step.id, step.id))
        alias = None
        if existing is None and step.span is None and step.component:
            # Small models often rename a section between outline and add. Bind the add to the first
            # unfilled outlined section with the same component instead of rejecting it.
            existing = next((self.sections[sid] for sid in self.order
                             if not self.sections[sid].added and self.sections[sid].component == step.component),
                            None)
            alias = existing and step.id
        if existing and existing.added:
            raise ValidationFailure(f"section {step.id!r} was already added")
        if existing:
            component = step.component or existing.component
            if component != existing.component:
                raise ValidationFailure(
                    f"section {step.id!r} was outlined as {existing.component}, not {component}")
            span = step.span or existing.span
        else:
            if not step.component:
                raise ValidationFailure(f"new section {step.id!r} needs a component")
            component, span = step.component, step.span or self.grid  # unplanned: full width
        self._check_component(component)
        self._check_span(span)
        if component == "Hero" and any(s.component == "Hero" and s.added for s in self.sections.values()):
            raise ValidationFailure("a page has only one Hero")
        props = self._check_props(component, step.props)

        if existing:
            existing.span, existing.added = span, True
            section = existing
            if alias:
                self.aliases[alias] = existing.id
        else:
            section = self.sections[step.id] = Section(step.id, component, span, added=True)
            self.order.append(step.id)
        return Accepted("add", section, props)

    def _move(self, step: MoveStep) -> Accepted:
        section = self.sections.get(self.aliases.get(step.id, step.id))
        if section is None or not section.added:
            raise ValidationFailure(f"move target {step.id!r} is not a placed component")
        if step.span is None and step.order is None:
            raise ValidationFailure("move needs a span or an order")
        if step.span is not None:
            self._check_span(step.span)
        if step.order is not None and step.order >= len(self.order):
            raise ValidationFailure(f"order {step.order} is outside the page (0-{len(self.order) - 1})")

        if step.span is not None:
            section.span = step.span
        if step.order is not None:
            self.order.remove(section.id)
            self.order.insert(step.order, section.id)
        return Accepted("move", section)

    # -- checks -------------------------------------------------------------------------------

    def _check_component(self, name: str) -> None:
        if name not in CATALOG:
            raise ValidationFailure(f"unknown component {name!r}")

    def _check_span(self, span: int) -> None:
        if not 1 <= span <= self.grid:
            raise ValidationFailure(f"span {span} must be between 1 and {self.grid}")

    def _check_props(self, component: str, props: dict) -> dict:
        comp = CATALOG[component]
        try:
            model = comp.props.model_validate(props)
        except ValidationError as exc:
            raise ValidationFailure(f"{component} props: {_summarize(exc)}") from None
        data = model.model_dump(exclude_none=True)

        for name in comp.text_fields:
            if name in data:
                data[name] = clean_text(data[name])
                if not data[name]:
                    raise ValidationFailure(f"{component}.{name} is empty")
                if len(data[name]) > self.max_heading:
                    raise ValidationFailure(f"{component}.{name} is longer than {self.max_heading} characters")

        # Small models often repeat an id; keep the first of each rather than rejecting the step.
        for key in ("contentIds", "assetIds", "routes", "urls"):
            if key in data:
                data[key] = list(dict.fromkeys(data[key]))
        ids = ([data["contentId"]] if "contentId" in data else []) + data.get("contentIds", [])
        for item_id in ids:
            item = self.ctx.items.get(item_id)
            if item is None:
                raise ValidationFailure(f"content id {item_id!r} is not in the retrieved set")
            if comp.content_types and item.type not in comp.content_types:
                raise ValidationFailure(f"{component} cannot show {item.type} item {item_id!r}")

        for asset_id in data.get("assetIds", []):
            if asset_id not in self.ctx.assets:
                raise ValidationFailure(f"asset id {asset_id!r} is not in the retrieved set")

        routes = self.ctx.route_paths
        for path in data.get("routes", []):
            if path not in routes:
                raise ValidationFailure(f"route {path!r} is not a known route")
        approved = self.ctx.approved_urls
        for url in data.get("urls", []):
            if url not in approved:
                raise ValidationFailure(f"url {url!r} is not approved")
        return data


def _summarize(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err["loc"]) or "step"
        parts.append(f"{loc}: {err['msg']}")
    return "; ".join(parts)
