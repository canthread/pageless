"""Placeholder seed content. Replace with the owner's real content via the admin page (coming later)."""

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .db import Base, make_engine
from .models import Asset, ContentItem, ContentRelation, ModelSettings, Route, SiteProfile

PROFILE = dict(
    name="Sam Example",
    summary="Placeholder software engineer who builds backend systems and small tools.",
    tone="Plain, friendly, specific. No hype.",
    required_links=[
        {"label": "GitHub", "url": "https://github.com/example"},
        {"label": "LinkedIn", "url": "https://www.linkedin.com/in/example"},
    ],
    content_version=1,
)

ROUTES = [
    dict(path="/", title="Home", nav_order=0,
         intent="Introduce the owner in a few lines and point visitors to their strongest work.",
         content_filters={"ids": ["bio_short", "contact_email"], "types": ["project"], "limit": 8}),
    dict(path="/about", title="About", nav_order=1,
         intent="Tell the owner's background: who they are, where they worked, what they studied.",
         content_filters={"ids": ["bio_short", "bio_long"], "types": ["experience", "education"]}),
    dict(path="/projects", title="Projects", nav_order=2,
         intent="Show the owner's projects and related writing.",
         content_filters={"types": ["project", "writing"]}),
    dict(path="/contact", title="Contact", nav_order=3,
         intent="Explain how to get in touch.",
         content_filters={"ids": ["bio_short"], "types": ["contact"]}),
]

ITEMS = [
    dict(id="bio_short", type="bio", title="Short bio", visibility="public", tags=["intro"],
         body="Placeholder bio. Sam builds backend services and small, sharp tools, "
              "and likes making slow things fast."),
    dict(id="bio_long", type="bio", title="Background", visibility="public", tags=["intro"],
         body="Placeholder long bio, paragraph one. Sam started programming by automating "
              "spreadsheets and never stopped.\n\nParagraph two. These days the focus is on "
              "Python services, data pipelines, and running models on local hardware."),
    dict(id="exp_acme", type="experience", title="Backend Engineer", visibility="public",
         tags=["python", "backend"],
         data={"org": "Acme Corp", "start": "2022", "end": "Present"},
         body="Placeholder role. Built and operated the order pipeline and its APIs."),
    dict(id="exp_initech", type="experience", title="Software Developer", visibility="public",
         tags=["python", "data"],
         data={"org": "Initech", "start": "2019", "end": "2022"},
         body="Placeholder role. Maintained reporting jobs and internal tools."),
    dict(id="edu_state", type="education", title="B.S. Computer Science", visibility="public",
         tags=["education"],
         data={"org": "State University", "start": "2015", "end": "2019"},
         body="Placeholder degree."),
    dict(id="proj_pageless", type="project", title="pageless", visibility="public",
         tags=["python", "llm", "fastapi"],
         data={"url": "https://github.com/example/pageless"},
         body="A website that composes every page on request from database records, "
              "streamed live from a small local model."),
    dict(id="proj_tiles", type="project", title="Tile Server", visibility="public",
         tags=["go", "maps"],
         data={"url": "https://github.com/example/tiles"},
         body="Placeholder project. A small vector tile server with aggressive caching."),
    dict(id="proj_notes", type="project", title="Plain Notes", visibility="public",
         tags=["python", "cli"],
         body="Placeholder project. A command-line notebook that stores notes as plain text."),
    dict(id="post_small_models", type="writing", title="Small models, strict schemas", visibility="public",
         tags=["llm"], data={"url": "https://github.com/example/pageless#readme"},
         body="Placeholder article summary. Why constraining a small model's output beats "
              "prompting a large one to behave."),
    dict(id="contact_email", type="contact", title="Get in touch", visibility="public",
         data={"email": "hello@example.com"},
         body="Placeholder contact note. Email is the fastest way to reach Sam."),
    dict(id="note_private", type="bio", title="Private note", visibility="private",
         body="Private placeholder. This must never reach the model or a page."),
]

RELATIONS = [
    dict(source_id="proj_pageless", target_id="post_small_models", relation="discussed_in"),
    dict(source_id="exp_acme", target_id="proj_tiles", relation="built_at"),
]

ASSETS = [
    dict(id="img_pageless", item_id="proj_pageless", url="/static/placeholder/pageless.svg",
         alt_text="Placeholder diagram of the pageless pipeline"),
    dict(id="img_tiles", item_id="proj_tiles", url="/static/placeholder/tiles.svg",
         alt_text="Placeholder map tiles"),
]


def seed(session: Session) -> bool:
    """Insert placeholder content into an empty database. Returns True if anything was added."""
    if session.scalar(select(SiteProfile.id).limit(1)) is not None:
        return False
    session.add(SiteProfile(**PROFILE))
    session.add_all(Route(**r) for r in ROUTES)
    session.add_all(ContentItem(**i) for i in ITEMS)
    session.flush()
    session.add_all(ContentRelation(**r) for r in RELATIONS)
    session.add_all(Asset(**a) for a in ASSETS)
    session.add(ModelSettings(model="llama3.1:8b"))
    session.commit()
    return True


def main() -> None:
    engine = make_engine(get_settings().database_url)
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as session:
        print("seeded" if seed(session) else "database already has content; nothing to do")


if __name__ == "__main__":
    main()
