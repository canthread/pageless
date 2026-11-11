"""The Ollama composer: streams a page spec from a local model and yields steps as they complete."""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

from .composer import Hint
from .config import Settings
from .prompt import build_messages, page_schema, retry_message, step_schema
from .retriever import Retrieved
from .streamparse import Partial, StepStreamParser

log = logging.getLogger(__name__)

_IS_ADD = re.compile(r'^\{\s*"type"\s*:\s*"add"')
_ID = re.compile(r'"id"\s*:\s*"([a-z][a-z0-9_-]{0,31})"')
_TEXT = re.compile(r'"(heading|subheading)"\s*:\s*"((?:[^"\\]|\\.)*)"')
_DONE = object()


@dataclass(frozen=True)
class ModelOptions:
    model: str
    temperature: float = 0.4
    num_ctx: int = 8192
    keep_alive: str = "30m"


@dataclass
class Usage:
    prompt_tokens: int = 0
    output_tokens: int = 0
    model_ms: float = 0.0


class OllamaError(RuntimeError):
    pass


class OllamaComposer:
    def __init__(self, options: ModelOptions, settings: Settings, client: httpx.AsyncClient | None = None):
        self.options = options
        self.settings = settings
        self.name = f"ollama:{options.model}"
        self.client = client
        self.usage = Usage()
        self._ctx: Retrieved | None = None
        self._messages: list[dict] = []

    # -- Composer protocol ---------------------------------------------------------------------

    async def steps(self, ctx: Retrieved) -> AsyncIterator[object]:
        self._ctx = ctx
        self._messages = build_messages(ctx)
        payload = self._payload(self._messages, page_schema(ctx, self.settings), stream=True,
                                num_predict=self.settings.max_output_tokens)
        # Drain the HTTP stream in a background task so a retry request (which Ollama queues behind
        # this one when OLLAMA_NUM_PARALLEL=1) can never stall it.
        queue: asyncio.Queue = asyncio.Queue()
        reader = asyncio.create_task(self._read_stream(payload, queue))
        deadline = time.monotonic() + self.settings.generation_timeout_s
        hints = _HintTracker()
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"generation exceeded {self.settings.generation_timeout_s}s")
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    raise TimeoutError(f"generation exceeded {self.settings.generation_timeout_s}s") from None
                if item is _DONE:
                    break
                if isinstance(item, BaseException):
                    raise item
                if isinstance(item, Partial):
                    for hint in hints.update(item.text):
                        yield hint
                else:
                    hints.reset()
                    yield item
        finally:
            reader.cancel()
            try:
                await reader
            except (asyncio.CancelledError, Exception):
                pass

    async def retry(self, step: object, error: str) -> object | None:
        if self._ctx is None:
            return None
        payload = self._payload(self._messages + retry_message(step, error),
                                step_schema(self._ctx, self.settings), stream=False, num_predict=512)
        try:
            data = await self._post(payload)
            return json.loads(data["message"]["content"])
        except Exception as exc:
            log.warning("retry failed: %s", exc)
            return None

    # -- HTTP ----------------------------------------------------------------------------------

    def _payload(self, messages: list[dict], schema: dict, stream: bool, num_predict: int) -> dict:
        return {
            "model": self.options.model,
            "messages": messages,
            "stream": stream,
            "format": schema,
            "think": False,
            "keep_alive": self.options.keep_alive,
            "options": {"temperature": self.options.temperature, "num_ctx": self.options.num_ctx,
                        "num_predict": num_predict},
        }

    def _http(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(base_url=self.settings.ollama_url, timeout=httpx.Timeout(
                self.settings.ollama_read_timeout_s, connect=self.settings.ollama_connect_timeout_s))
        return self.client

    async def _post(self, payload: dict) -> dict:
        response = await self._http().post("/api/chat", json=payload)
        data = response.json()
        if response.status_code != 200 or "error" in data:
            raise OllamaError(data.get("error", f"HTTP {response.status_code}"))
        self._count(data)
        return data

    async def _read_stream(self, payload: dict, queue: asyncio.Queue) -> None:
        parser = StepStreamParser()
        try:
            async with self._http().stream("POST", "/api/chat", json=payload) as response:
                if response.status_code != 200:
                    body = (await response.aread()).decode(errors="replace")
                    raise OllamaError(f"HTTP {response.status_code}: {body[:200]}")
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    if "error" in chunk:
                        raise OllamaError(chunk["error"])
                    for item in parser.feed(chunk.get("message", {}).get("content", "")):
                        queue.put_nowait(item)
                    if chunk.get("done"):
                        self._count(chunk)
                        if chunk.get("done_reason") == "length":
                            log.warning("model output hit num_predict=%s", payload["options"]["num_predict"])
                        break
            queue.put_nowait(_DONE)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            queue.put_nowait(exc)

    def _count(self, chunk: dict) -> None:
        self.usage.prompt_tokens += chunk.get("prompt_eval_count", 0) or 0
        self.usage.output_tokens += chunk.get("eval_count", 0) or 0
        self.usage.model_ms += (chunk.get("total_duration", 0) or 0) / 1e6


@dataclass
class _HintTracker:
    """Turns the text of a step that is still being written into early section hints."""

    sent_start: bool = False
    sent_text: set[str] = field(default_factory=set)

    def reset(self) -> None:
        self.sent_start = False
        self.sent_text = set()

    def update(self, text: str) -> list[Hint]:
        if not _IS_ADD.match(text):
            return []
        match = _ID.search(text)
        if not match:
            return []
        section_id = match.group(1)
        hints: list[Hint] = []
        if not self.sent_start:
            self.sent_start = True
            hints.append(Hint("start", section_id))
        for field_name, raw in _TEXT.findall(text):
            if field_name in self.sent_text:
                continue
            try:
                value = json.loads(f'"{raw}"')
            except ValueError:
                continue
            self.sent_text.add(field_name)
            hints.append(Hint("text", section_id, field_name, value))
        return hints
