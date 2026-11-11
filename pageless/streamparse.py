"""Incremental extraction of page-spec steps from a streamed JSON document.

The model streams `{"title": ..., "outline": [...], "steps": [{...}, {...}]}` a few characters at a
time. The parser emits the top-level "outline" array as an outline step when it closes, then each
element of the top-level "steps" array as soon as its closing brace arrives. It also exposes the text
of the element still being written so callers can react early (section.start/section.text).

A separate "outline" key (rather than an outline step inside "steps") lets the grammar guarantee the
outline comes first and only once; JSON-schema grammars can't constrain array positions.
"""

import json
from dataclasses import dataclass


@dataclass
class Partial:
    text: str


class StepStreamParser:
    def __init__(self) -> None:
        self.buf = ""
        self.pos = 0
        self.depth = 0
        self.in_string = False
        self.escape = False
        self.string_start = -1
        self.last_key: str | None = None
        self.steps_depth: int | None = None  # depth inside the "steps" array
        self.element_start: int | None = None
        self.awaiting_steps = False
        self.awaiting_outline = False
        self.outline_start: int | None = None

    def feed(self, chunk: str) -> list[object]:
        """Return completed steps (as parsed JSON) and, last, a Partial for any open element."""
        self.buf += chunk
        out: list[object] = []
        buf = self.buf
        for i in range(self.pos, len(buf)):
            ch = buf[i]
            if self.in_string:
                if self.escape:
                    self.escape = False
                elif ch == "\\":
                    self.escape = True
                elif ch == '"':
                    self.in_string = False
                    if self.depth == 1:
                        try:
                            self.last_key = json.loads(buf[self.string_start:i + 1])
                        except ValueError:
                            self.last_key = None
                continue
            if ch == '"':
                self.in_string, self.string_start = True, i
            elif ch == ":" and self.depth == 1:
                self.awaiting_steps = self.last_key == "steps"
                self.awaiting_outline = self.last_key == "outline"
            elif ch in "{[":
                if ch == "[" and self.depth == 1 and self.awaiting_outline:
                    self.outline_start = i
                    self.awaiting_outline = False
                elif ch == "[" and self.depth == 1 and self.awaiting_steps:
                    self.steps_depth = 2
                    self.awaiting_steps = False
                elif ch == "{" and self.steps_depth is not None and self.depth == self.steps_depth:
                    self.element_start = i
                self.depth += 1
            elif ch in "}]":
                self.depth -= 1
                if (ch == "}" and self.element_start is not None and self.steps_depth is not None
                        and self.depth == self.steps_depth):
                    text = buf[self.element_start:i + 1]
                    self.element_start = None
                    try:
                        out.append(json.loads(text))
                    except ValueError:
                        out.append(text)  # malformed: the validator will reject it
                elif ch == "]" and self.steps_depth is not None and self.depth == self.steps_depth - 1:
                    self.steps_depth = None
                elif ch == "]" and self.outline_start is not None and self.depth == 1:
                    text = buf[self.outline_start:i + 1]
                    self.outline_start = None
                    try:
                        out.append({"type": "outline", "sections": json.loads(text)})
                    except ValueError:
                        out.append(text)
        self.pos = len(buf)
        if self.element_start is not None:
            out.append(Partial(buf[self.element_start:]))
        return out
