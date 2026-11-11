"""The pageless server: resolves routes, runs the pipeline, and streams events or full HTML."""

from contextlib import aclosing, asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from .composer import FallbackComposer
from .config import Settings, get_settings
from .db import Base, make_engine
from .models import ModelSettings
from .ollama import ModelOptions, OllamaComposer
from .pipeline import final_layout, run_pipeline
from .render import env
from .retriever import Chrome, Retrieved, load_chrome, retrieve
from .routing import is_crawler, normalize_path, resolve
from .seed import seed

STATIC_DIR = Path(__file__).parent / "static"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = make_engine(settings.database_url)
    Session = sessionmaker(engine, expire_on_commit=False)
    templates = Jinja2Templates(env=env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        Base.metadata.create_all(engine)
        if settings.seed_on_startup:
            with Session() as session:
                seed(session)
        app.state.http = httpx.AsyncClient(base_url=settings.ollama_url, timeout=httpx.Timeout(
            settings.ollama_read_timeout_s, connect=settings.ollama_connect_timeout_s))
        yield
        await app.state.http.aclose()
        engine.dispose()

    app = FastAPI(title="pageless", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.state.settings = settings
    app.state.session_factory = Session

    def _chrome() -> Chrome:
        with Session() as session:
            return load_chrome(session)

    def _retrieve(path: str) -> Retrieved:
        with Session() as session:
            return retrieve(session, path)

    def _model_options() -> ModelOptions | None:
        with Session() as session:
            row = session.scalars(select(ModelSettings).order_by(ModelSettings.updated_at.desc()).limit(1)).first()
            if row is None:
                return None
            return ModelOptions(row.model, row.temperature, row.num_ctx, row.keep_alive)

    async def composer_for(request: Request):
        """The active model, read per request so a settings change applies to the next generation."""
        if settings.composer != "ollama":
            return FallbackComposer()
        options = await run_in_threadpool(_model_options)
        if options is None:
            return FallbackComposer()
        return OllamaComposer(options, settings, client=request.app.state.http)

    async def resolve_request(raw: str) -> tuple[Chrome, str, str | None, bool]:
        chrome = await run_in_threadpool(_chrome)
        path = normalize_path(raw, settings.max_path_chars)
        route, exact = resolve(path, {r.path for r in chrome.nav})
        return chrome, path, route, exact

    @app.get("/_stream")
    async def stream(request: Request, path: str = "/"):
        _, _, route, exact = await resolve_request(path)
        if route is None or not exact:
            return JSONResponse({"error": "unknown route"}, status_code=404)
        ctx = await run_in_threadpool(_retrieve, route)

        composer = await composer_for(request)

        async def events():
            async with aclosing(run_pipeline(ctx, composer, settings)) as pipeline:
                async for event in pipeline:
                    if await request.is_disconnected():
                        break
                    yield event.sse()

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def page(request: Request, full_path: str, static: bool = False):
        chrome, path, route, exact = await resolve_request("/" + full_path)
        if route is None:
            return templates.TemplateResponse(request, "not_found.html", {"chrome": chrome, "current": None,
                                                                         "path": path}, status_code=404)
        if not exact:
            target = route + ("?static=1" if static else "")
            return RedirectResponse(target, status_code=302)

        route_info = next(r for r in chrome.nav if r.path == route)
        context = {"chrome": chrome, "current": route_info, "sections": [], "ssr": False}
        if static or is_crawler(request.headers.get("user-agent")):
            ctx = await run_in_threadpool(_retrieve, route)
            events = [e async for e in run_pipeline(ctx, FallbackComposer(), settings)]
            context.update(ssr=True, sections=final_layout(events))
        return templates.TemplateResponse(request, "page.html", context)

    return app
