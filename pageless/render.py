"""Server-side component rendering. Used for live `section.ready` events and full HTML pages alike."""

from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape
from markupsafe import Markup, escape

from .retriever import Retrieved

TEMPLATES_DIR = Path(__file__).parent / "templates"


def paragraphs(text: str) -> Markup:
    """Database text is shown unchanged, but escaped: blank lines become paragraphs."""
    blocks = [b.strip() for b in (text or "").split("\n\n") if b.strip()]
    return Markup("".join(f"<p>{escape(b)}</p>" for b in blocks))


env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)
env.filters["paragraphs"] = paragraphs


def _route_title(ctx: Retrieved, path: str) -> str:
    return next((r.title for r in ctx.nav if r.path == path), path)


def _url_label(ctx: Retrieved, url: str) -> str:
    for link in ctx.profile.required_links:
        if link.url == url:
            return link.label
    for item in ctx.items.values():
        if item.data.get("url") == url:
            return item.title
    return urlparse(url).netloc or url


def render_section(component: str, props: dict, ctx: Retrieved) -> str:
    template = env.get_template(f"components/{component}.html")
    return template.render(p=props, ctx=ctx, items=ctx.items, assets=ctx.assets,
                           route_title=lambda path: _route_title(ctx, path),
                           url_label=lambda url: _url_label(ctx, url)).strip()
