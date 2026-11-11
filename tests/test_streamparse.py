import json
import random

from pageless.streamparse import Partial, StepStreamParser

DOC = {"title": "About", "steps": [
    {"type": "outline", "sections": [{"id": "intro", "component": "Hero", "span": 12}]},
    {"type": "add", "id": "intro", "props": {"heading": 'Say "hi" {not a brace}', "contentId": "bio_short"}},
    {"type": "move", "id": "intro", "span": 8},
]}


def parse(text: str, sizes):
    parser, steps, partials = StepStreamParser(), [], []
    i = 0
    for size in sizes:
        for item in parser.feed(text[i:i + size]):
            (partials if isinstance(item, Partial) else steps).append(item)
        i += size
        if i >= len(text):
            break
    return steps, partials


def test_whole_document():
    steps, _ = parse(json.dumps(DOC), [10_000])
    assert steps == DOC["steps"]


def test_any_chunking_gives_the_same_steps():
    text = json.dumps(DOC, indent=2)
    rng = random.Random(7)
    for _ in range(50):
        steps, _ = parse(text, iter(lambda: rng.randint(1, 9), None))
        assert steps == DOC["steps"]


def test_partials_show_the_open_step():
    text = json.dumps(DOC)
    cut = text.index('"contentId"')
    _, partials = parse(text[:cut], [cut])
    assert partials[-1].text.startswith('{"type": "add", "id": "intro"')


def test_ignores_brackets_outside_steps():
    text = '{"title": "[x] {y}", "meta": {"steps": [1]}, "steps": [{"type": "move", "id": "a", "span": 3}]}'
    steps, _ = parse(text, [5] * 40)
    assert steps == [{"type": "move", "id": "a", "span": 3}]


def test_malformed_element_is_passed_through_as_text():
    steps, _ = parse('{"steps": [{"type": "add", "id": 01}]}', [100])
    assert steps == ['{"type": "add", "id": 01}']


def test_outline_key_becomes_the_first_step():
    doc = {"title": "x", "outline": [{"id": "intro", "component": "Hero", "span": 12}],
           "steps": [{"type": "move", "id": "intro", "span": 6}]}
    steps, _ = parse(json.dumps(doc), [3] * 100)
    assert steps == [{"type": "outline", "sections": doc["outline"]}, doc["steps"][0]]
