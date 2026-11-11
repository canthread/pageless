"""Composers produce raw page-spec steps. They are untrusted: everything they emit is validated."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol

from .fallback import fallback_spec
from .retriever import Retrieved


@dataclass(frozen=True)
class Hint:
    """An early signal about a step that is still being written; not a step itself.

    kind "start": the model began adding section `id`. kind "text": it finished writing `field`.
    """

    kind: str
    id: str
    field: str | None = None
    text: str | None = None


class Composer(Protocol):
    name: str

    def steps(self, ctx: Retrieved) -> AsyncIterator[object]:
        """Yield raw steps (outline first) as they are produced, optionally interleaved with Hints."""

    async def retry(self, step: object, error: str) -> object | None:
        """Return a corrected step after a validation failure, or None if retrying isn't possible."""


class StaticComposer:
    """Plays a hand-written spec. Used for fallbacks, tests, and demos of the browser animation."""

    def __init__(self, spec: dict, name: str = "static"):
        self.spec = spec
        self.name = name

    async def steps(self, ctx: Retrieved) -> AsyncIterator[object]:
        for step in self.spec.get("steps", []):
            yield step

    async def retry(self, step: object, error: str) -> object | None:
        return None


class FallbackComposer:
    """The deterministic page for a route. Its output always validates."""

    name = "fallback"

    async def steps(self, ctx: Retrieved) -> AsyncIterator[object]:
        for step in fallback_spec(ctx)["steps"]:
            yield step

    async def retry(self, step: object, error: str) -> object | None:
        return None
