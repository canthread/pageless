"""Database tables. The database stores small reusable content items, not finished pages."""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SiteProfile(Base):
    __tablename__ = "site_profile"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    summary: Mapped[str] = mapped_column(Text)
    tone: Mapped[str] = mapped_column(String(200))
    # [{"label": "GitHub", "url": "https://..."}]; these URLs are approved for links.
    required_links: Mapped[list] = mapped_column(JSON, default=list)
    # Bump whenever public content changes; it is part of every pool key.
    content_version: Mapped[int] = mapped_column(Integer, default=1)


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(primary_key=True)
    path: Mapped[str] = mapped_column(String(200), unique=True)
    title: Mapped[str] = mapped_column(String(120))
    intent: Mapped[str] = mapped_column(Text)
    # {"ids": [...], "types": [...], "tags": [...], "limit": n}
    content_filters: Mapped[dict] = mapped_column(JSON, default=dict)
    nav_order: Mapped[int] = mapped_column(Integer, default=0)


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    type: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list] = mapped_column(JSON, default=list)
    visibility: Mapped[str] = mapped_column(String(16), default="private")
    # Type-specific fields, e.g. {"org", "role", "start", "end"} or {"url", "email"}.
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class ContentRelation(Base):
    __tablename__ = "content_relations"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    target_id: Mapped[str] = mapped_column(ForeignKey("content_items.id", ondelete="CASCADE"), index=True)
    relation: Mapped[str] = mapped_column(String(40))


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str | None] = mapped_column(ForeignKey("content_items.id", ondelete="SET NULL"), index=True)
    url: Mapped[str] = mapped_column(String(500))
    alt_text: Mapped[str] = mapped_column(String(300))


class GeneratedPage(Base):
    __tablename__ = "generated_pages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    pool_key: Mapped[str] = mapped_column(String(300), index=True)
    events: Mapped[list] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class GenerationLog(Base):
    __tablename__ = "generation_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    route: Mapped[str] = mapped_column(String(200), index=True)
    model: Mapped[str] = mapped_column(String(120))
    tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[float] = mapped_column(Float)
    result: Mapped[str] = mapped_column(String(20))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class VersionView(Base):
    __tablename__ = "version_views"

    id: Mapped[int] = mapped_column(primary_key=True)
    visitor_id: Mapped[str] = mapped_column(String(64), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("generated_pages.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ModelSettings(Base):
    __tablename__ = "model_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    model: Mapped[str] = mapped_column(String(120))
    temperature: Mapped[float] = mapped_column(Float, default=0.4)
    num_ctx: Mapped[int] = mapped_column(Integer, default=8192)
    keep_alive: Mapped[str] = mapped_column(String(20), default="30m")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
