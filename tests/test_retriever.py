def test_only_public_items_are_retrieved(ctx_for):
    for path in ("/", "/about", "/projects", "/contact"):
        ctx = ctx_for(path)
        assert "note_private" not in ctx.items
        assert all(i.id != "note_private" for i in ctx.items.values())


def test_route_filters(ctx_for):
    about = ctx_for("/about")
    assert {"bio_short", "bio_long", "exp_acme", "exp_initech", "edu_state"} <= about.items.keys()
    projects = ctx_for("/projects")
    assert {"proj_pageless", "proj_tiles", "post_small_models"} <= projects.items.keys()
    assert {"img_pageless", "img_tiles"} <= projects.assets.keys()


def test_related_items_are_included(ctx_for):
    # exp_acme relates to proj_tiles, so /about can mention it.
    assert "proj_tiles" in ctx_for("/about").items


def test_approved_urls(ctx_for):
    urls = ctx_for("/projects").approved_urls
    assert "https://github.com/example" in urls
    assert "https://github.com/example/pageless" in urls


def test_fallback_page_shows_only_primary_content(ctx_for):
    from pageless.fallback import fallback_spec

    def components(path):
        return [s["component"] for s in fallback_spec(ctx_for(path))["steps"][0]["sections"]]

    assert components("/about") == ["Hero", "RichText", "Timeline"]
    assert components("/") == ["Hero", "CardGrid", "ContactBlock"]
    assert components("/projects") == ["Hero", "CardGrid", "CardGrid", "Gallery"]
