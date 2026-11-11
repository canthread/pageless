import asyncio
import json

import httpx

from pageless.ollama import ModelOptions, OllamaComposer
from pageless.pipeline import PipelineResult, run_pipeline
from pageless.prompt import build_messages, page_schema

GOOD = {"title": "About",
        "outline": [{"id": "intro", "component": "Hero", "span": 12},
                    {"id": "history", "component": "Timeline", "span": 8}],
        "steps": [
    {"type": "add", "id": "intro", "component": "Hero",
     "props": {"heading": "Background", "contentId": "bio_short"}},
    {"type": "add", "id": "history", "component": "Timeline",
     "props": {"heading": "Work", "contentIds": ["exp_acme", "invented_job"]}},
]}
FIXED = {"type": "add", "id": "history", "component": "Timeline",
         "props": {"heading": "Work", "contentIds": ["exp_acme"]}}


def fake_ollama(doc, retry_reply=None, status=200):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append(body)
        if status != 200:
            return httpx.Response(status, json={"error": "model 'nope' not found"})
        if not body["stream"]:
            return httpx.Response(200, json={"message": {"content": json.dumps(retry_reply)}, "done": True,
                                             "eval_count": 5})
        text = json.dumps(doc)
        chunks = [text[i:i + 7] for i in range(0, len(text), 7)]
        lines = [json.dumps({"message": {"content": c}, "done": False}) for c in chunks]
        lines.append(json.dumps({"message": {"content": ""}, "done": True, "eval_count": 99,
                                 "prompt_eval_count": 400}))
        return httpx.Response(200, content="\n".join(lines).encode())

    return httpx.AsyncClient(base_url="http://ollama", transport=httpx.MockTransport(handler)), seen


def run(ctx, composer, settings):
    result = PipelineResult()

    async def go():
        return [e async for e in run_pipeline(ctx, composer, settings, result)]

    return asyncio.run(go()), result


def test_streams_validates_and_retries(ctx_for, settings):
    client, seen = fake_ollama(GOOD, retry_reply=FIXED)
    composer = OllamaComposer(ModelOptions("llama3.1:8b"), settings, client)
    events, result = run(ctx_for("/about"), composer, settings)
    names = [e.name for e in events]
    # Hints announce sections before their step completes; validation gates section.ready.
    assert names[:4] == ["page.start", "layout.outline", "section.start", "section.text"]
    assert names.count("section.start") == 2
    ready = [e.data["id"] for e in events if e.name == "section.ready"]
    assert ready == ["intro", "history"]  # history passed on retry
    assert result.retries == 1 and result.valid
    assert composer.usage.output_tokens == 104
    stream_req, retry_req = seen
    assert stream_req["model"] == "llama3.1:8b" and stream_req["keep_alive"] == "30m"
    assert stream_req["format"]["properties"]["steps"]["items"]["anyOf"]
    assert "invented_job" in retry_req["messages"][-2]["content"]


def test_retry_failure_uses_fallback(ctx_for, settings):
    client, _ = fake_ollama(GOOD, retry_reply={"type": "add", "id": "history", "props": {}})
    events, result = run(ctx_for("/about"), OllamaComposer(ModelOptions("m"), settings, client), settings)
    assert [e.data["id"] for e in events if e.name == "section.replace"] == ["history"]
    assert not result.valid


def test_unreachable_model_falls_back_to_deterministic_page(ctx_for, settings):
    client, _ = fake_ollama(GOOD, status=404)
    events, result = run(ctx_for("/about"), OllamaComposer(ModelOptions("nope"), settings, client), settings)
    assert any("not found" in f for f in result.failures)
    assert events[-1].name == "page.done"
    assert sum(e.name == "section.ready" for e in events) >= 3


def test_schema_only_allows_retrieved_ids(ctx_for, settings):
    ctx = ctx_for("/contact")
    schema = json.dumps(page_schema(ctx, settings))
    assert "note_private" not in schema and "exp_acme" not in schema
    assert '"Gallery"' not in schema  # no assets on /contact, so the component isn't offered
    prompt = json.dumps(build_messages(ctx))
    assert "note_private" not in prompt and "Private placeholder" not in prompt

