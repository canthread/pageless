"""Deterministic content: a full page per route, and a stand-in for any single section that fails.

Everything here is computed from the retrieved records, so it always validates.
"""

from .retriever import Retrieved

TIMELINE_TYPES = ("experience", "education")
CARD_TYPES = ("project", "writing")


def _sorted_timeline(ctx: Retrieved, primary: bool = False) -> list[str]:
    items = ctx.of_type(*TIMELINE_TYPES, primary=primary)
    return [i.id for i in sorted(items, key=lambda i: str(i.data.get("start", "")), reverse=True)]


def _hero_item(ctx: Retrieved) -> str | None:
    bios = ctx.of_type("bio")
    if bios:
        short = [b for b in bios if b.id == "bio_short"]
        return (short or bios)[0].id
    return next(iter(ctx.items), None)


def _hero_heading(ctx: Retrieved) -> str:
    return ctx.profile.name if ctx.route.path == "/" else ctx.route.title


def _other_routes(ctx: Retrieved) -> list[str]:
    others = [r.path for r in ctx.nav if r.path != ctx.route.path]
    return others or [r.path for r in ctx.nav]


def fallback_props(component: str, ctx: Retrieved) -> dict | None:
    """Props for one component built from the retrieved set, or None if there is nothing suitable."""
    hero_id = _hero_item(ctx)
    match component:
        case "Hero":
            return {"heading": _hero_heading(ctx), "contentId": hero_id} if hero_id else None
        case "RichText":
            ids = [i.id for i in ctx.of_type("bio", "writing") if i.id != hero_id][:2]
            ids = ids or ([hero_id] if hero_id else [])
            return {"contentIds": ids} if ids else None
        case "Timeline":
            ids = _sorted_timeline(ctx)[:12]
            return {"heading": "Experience", "contentIds": ids} if ids else None
        case "ProjectCard":
            projects = ctx.of_type("project")
            return {"contentId": projects[0].id} if projects else None
        case "CardGrid":
            ids = [i.id for i in ctx.of_type(*CARD_TYPES)][:9]
            return {"heading": "Work", "contentIds": ids} if ids else None
        case "Gallery":
            ids = list(ctx.assets)[:12]
            return {"assetIds": ids} if ids else None
        case "LinkList":
            return {"heading": "Keep exploring", "routes": _other_routes(ctx)}
        case "ContactBlock":
            contacts = ctx.of_type("contact")
            return {"heading": "Contact", **({"contentId": contacts[0].id} if contacts else {})}
    return None


def fallback_section(component: str, ctx: Retrieved) -> tuple[str, dict]:
    """A replacement for a failed section: the same component if possible, otherwise navigation links."""
    props = fallback_props(component, ctx)
    if props is not None:
        return component, props
    return "LinkList", fallback_props("LinkList", ctx)


def fallback_spec(ctx: Retrieved) -> dict:
    """A complete, hand-arranged page spec for a route. Includes one move so replays animate."""
    hero_id = _hero_item(ctx)
    planned: list[tuple[str, str, dict]] = []
    if hero_id:
        planned.append(("intro", "Hero", {"heading": _hero_heading(ctx), "contentId": hero_id}))
    story = [i.id for i in ctx.of_type("bio", primary=True) if i.id != hero_id]
    if story:
        planned.append(("story", "RichText", {"contentIds": story[:4]}))
    timeline = _sorted_timeline(ctx, primary=True)
    if timeline:
        planned.append(("history", "Timeline", {"heading": "Experience", "contentIds": timeline[:12]}))
    projects = [i.id for i in ctx.of_type("project", primary=True)]
    if projects:
        heading = "Selected work" if ctx.route.path == "/" else "Projects"
        planned.append(("work", "CardGrid", {"heading": heading, "contentIds": projects[:9]}))
    writing = [i.id for i in ctx.of_type("writing", primary=True)]
    if writing and ctx.route.path != "/":
        planned.append(("writing", "CardGrid", {"heading": "Writing", "contentIds": writing[:9]}))
    gallery = ctx.primary_assets()
    if gallery and ctx.route.path != "/":
        planned.append(("gallery", "Gallery", {"heading": "Gallery", "assetIds": gallery[:12]}))
    if ctx.of_type("contact", primary=True):
        planned.append(("contact", "ContactBlock", fallback_props("ContactBlock", ctx)))

    steps: list[dict] = [{"type": "outline",
                          "sections": [{"id": sid, "component": comp, "span": 12} for sid, comp, _ in planned]}]
    steps += [{"type": "add", "id": sid, "props": props} for sid, _, props in planned]
    steps.append({"type": "add", "id": "next", "component": "LinkList", "span": 12,
                  "props": fallback_props("LinkList", ctx)})
    if len(planned) > 1:
        # Tuck the navigation beside the last content section.
        steps.append({"type": "move", "id": planned[-1][0], "span": 8})
        steps.append({"type": "move", "id": "next", "span": 4})
    return {"title": ctx.route.title, "steps": steps}
