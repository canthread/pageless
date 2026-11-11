# pageless
A just-in-time website that generates every page from a database on request. See [SPEC.md](SPEC.md).

## Run it

```sh
docker compose up -d --wait      # PostgreSQL on 127.0.0.1:5432
uv sync
uv run uvicorn pageless.main:app --reload
```

Open http://localhost:8000. Tables are created and placeholder content is seeded on first start.
Add `?static=1` to any URL (or send a crawler user agent) for fully server-rendered HTML.

Configuration lives in `pageless/config.py`; override any value with a `PAGELESS_*` environment
variable or a `.env` file (see `.env.example`).

```sh
uv run pytest
```

## Layout

| Module | Role |
| --- | --- |
| `models.py`, `seed.py` | Database tables and placeholder content |
| `routing.py` | URL normalization, closest-route matching, crawler detection |
| `retriever.py` | Loads the public records a route may use |
| `catalog.py`, `spec.py` | Component catalog and the page-spec step schema |
| `validator.py` | Checks every step against the catalog and retrieved records |
| `fallback.py` | Deterministic pages and per-section stand-ins |
| `composer.py` | Step sources: static and deterministic fallback |
| `prompt.py` | Model prompt and the per-request JSON schema passed to Ollama's `format` |
| `streamparse.py` | Pulls each finished step out of the model's streamed JSON |
| `ollama.py` | The Ollama composer: streaming, early section hints, retries |
| `pipeline.py` | Validates steps, retries, falls back, emits SSE events |
| `static/pageless.js` | Browser player: paced queue, FLIP moves, reading anchor |

## Status

Build order steps 1–5 are done. Pages are composed live by the active Ollama model (the newest
row in `model_settings`, seeded as `llama3.1:8b`); if Ollama is unreachable or the outline fails,
the deterministic page is served instead. Set `PAGELESS_COMPOSER=fallback` to skip the model.

Next up (step 6): version pools, the admin model picker and test button, generation logs, and
visitor limits.
