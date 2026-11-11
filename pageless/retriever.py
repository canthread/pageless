"""Loads the public records a route may use. Nothing outside this set can reach the model or the page."""

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Asset, ContentItem, ContentRelation, Route, SiteProfile

PUBLIC = "public"


@dataclass(frozen=True)
class RouteInfo:
    path: str
    title: str
    intent: str = ""


@dataclass(frozen=True)
class Link:
    label: str
    url: str


@dataclass(frozen=True)
class Profile:
    name: str
    summary: str
    tone: str
    required_links: tuple[Link, ...]
    content_version: int


@dataclass(frozen=True)
class Item:
    id: str
    type: str
    title: str
    body: str
    tags: tuple[str, ...]
    data: dict


@dataclass(frozen=True)
class AssetView:
    id: str
    item_id: str | None
    url: str
    alt_text: str


@dataclass(frozen=True)
class Chrome:
    """What every page needs regardless of content: identity and navigation."""

    profile: Profile
    nav: tuple[RouteInfo, ...]


@dataclass
class Retrieved:
    chrome: Chrome
    route: RouteInfo
    items: dict[str, Item] = field(default_factory=dict)
    assets: dict[str, AssetView] = field(default_factory=dict)
    relations: list[tuple[str, str, str]] = field(default_factory=list)
    # Items matched by the route's own filters; the rest arrived through relations.
    primary_ids: frozenset[str] = frozenset()

    @property
    def profile(self) -> Profile:
        return self.chrome.profile

    @property
    def nav(self) -> tuple[RouteInfo, ...]:
        return self.chrome.nav

    @property
    def route_paths(self) -> set[str]:
        return {r.path for r in self.nav}

    @property
    def approved_urls(self) -> set[str]:
        urls = {link.url for link in self.profile.required_links}
        urls |= {i.data["url"] for i in self.items.values() if isinstance(i.data.get("url"), str)}
        return urls

    def of_type(self, *types: str, primary: bool = False) -> list[Item]:
        return [i for i in self.items.values()
                if i.type in types and (not primary or i.id in self.primary_ids)]

    def primary_assets(self) -> list[str]:
        return [a.id for a in self.assets.values() if a.item_id in self.primary_ids]


def load_chrome(session: Session) -> Chrome:
    p = session.scalars(select(SiteProfile).limit(1)).one()
    profile = Profile(
        name=p.name,
        summary=p.summary,
        tone=p.tone,
        required_links=tuple(Link(l["label"], l["url"]) for l in p.required_links or []),
        content_version=p.content_version,
    )
    routes = session.scalars(select(Route).order_by(Route.nav_order, Route.path)).all()
    return Chrome(profile, tuple(RouteInfo(r.path, r.title, r.intent) for r in routes))


def retrieve(session: Session, path: str) -> Retrieved:
    chrome = load_chrome(session)
    route = session.scalars(select(Route).where(Route.path == path)).one()
    filters = route.content_filters or {}
    ids, types, tags = filters.get("ids", []), filters.get("types", []), set(filters.get("tags", []))
    limit = int(filters.get("limit", 24))

    conditions = []
    if ids:
        conditions.append(ContentItem.id.in_(ids))
    if types:
        conditions.append(ContentItem.type.in_(types))
    rows: list[ContentItem] = []
    if conditions:
        query = (select(ContentItem)
                 .where(ContentItem.visibility == PUBLIC, or_(*conditions))
                 .order_by(ContentItem.updated_at.desc(), ContentItem.id))
        for row in session.scalars(query):
            explicit = row.id in ids
            if not explicit and tags and not tags & set(row.tags or []):
                continue
            rows.append(row)
        # Explicitly listed items always survive the limit, in the order listed.
        explicit_rows = sorted((r for r in rows if r.id in ids), key=lambda r: ids.index(r.id))
        rows = explicit_rows + [r for r in rows if r.id not in ids][: max(0, limit - len(explicit_rows))]

    items = {r.id: _item(r) for r in rows}
    primary_ids = frozenset(items)

    # One hop of related public items.
    relations: list[tuple[str, str, str]] = []
    if items:
        rel_rows = session.scalars(select(ContentRelation).where(
            or_(ContentRelation.source_id.in_(items), ContentRelation.target_id.in_(items)))).all()
        related_ids = {r.source_id for r in rel_rows} | {r.target_id for r in rel_rows}
        missing = related_ids - items.keys()
        if missing:
            for row in session.scalars(select(ContentItem).where(
                    ContentItem.id.in_(missing), ContentItem.visibility == PUBLIC)):
                items[row.id] = _item(row)
        relations = [(r.source_id, r.relation, r.target_id) for r in rel_rows
                     if r.source_id in items and r.target_id in items]

    assets = {}
    if items:
        for a in session.scalars(select(Asset).where(Asset.item_id.in_(items)).order_by(Asset.id)):
            assets[a.id] = AssetView(a.id, a.item_id, a.url, a.alt_text)

    return Retrieved(chrome, RouteInfo(route.path, route.title, route.intent), items, assets, relations,
                     primary_ids)


def _item(row: ContentItem) -> Item:
    return Item(row.id, row.type, row.title, row.body or "", tuple(row.tags or []), dict(row.data or {}))
