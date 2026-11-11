import pytest

from pageless.routing import normalize_path, resolve

KNOWN = {"/", "/about", "/projects", "/contact"}


@pytest.mark.parametrize("raw, expected", [
    ("/About/", "/about"),
    ("//projects///", "/projects"),
    ("/../../etc/passwd", "/etc/passwd"),
    ("/about?x=1#y", "/about"),
    ("/%3Cscript%3E", "/script"),
    ("/ignore previous instructions", "/ignorepreviousinstructions"),
])
def test_normalize(raw, expected):
    assert normalize_path(raw) == expected


@pytest.mark.parametrize("path, expected", [
    ("/about", ("/about", True)),
    ("/projects/pageless", ("/projects", False)),
    ("/abuot", ("/about", False)),
    ("/index", ("/", False)),
    ("/wp-admin", (None, False)),
    ("/ignorepreviousinstructions", (None, False)),
])
def test_resolve(path, expected):
    assert resolve(path, KNOWN) == expected


def test_shell_page_streams(client):
    r = client.get("/about")
    assert r.status_code == 200
    assert 'data-pl-stream="/_stream?path=/about"' in r.text
    assert 'aria-busy="true"' in r.text


def test_stream_events(client):
    with client.stream("GET", "/_stream", params={"path": "/about"}) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        body = "".join(r.iter_text())
    events = [line.split(": ", 1)[1] for line in body.splitlines() if line.startswith("event: ")]
    assert events[0] == "page.start" and events[1] == "layout.outline" and events[-1] == "page.done"
    assert "layout.move" in events
    assert "Private placeholder" not in body


def test_static_and_crawler_get_full_html(client):
    for r in (client.get("/projects?static=1"),
              client.get("/projects", headers={"User-Agent": "Googlebot/2.1"})):
        assert r.status_code == 200
        assert "data-pl-stream" not in r.text
        assert "Tile Server" in r.text and 'class="pl-block is-ready"' in r.text


def test_unknown_paths(client):
    r = client.get("/projects/pageless", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == "/projects"
    r = client.get("/wp-login.php")
    assert r.status_code == 404 and "Nothing here" in r.text
    assert client.get("/_stream", params={"path": "/nope"}).status_code == 404
