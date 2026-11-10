"""Deck slide-list format (E5-R1): load, validate, and export.

A deck is authored as a JSON slide list (schemas/deck_spec.schema.json):
deck-level ``title`` plus defaults (``subtitle``, ``date``, ``eyebrow``,
``footer_section``) and a ``slides`` array whose entries each name a
generic ``layout`` and that layout's content fields, plus optional
``notes`` (speaker notes, '|'-separated lines) and ``section`` (the
footer's section name). Slide numbers are positional; the cover is
slide 1. This module is the stdlib authority for that format:

    load_deck(path)          read a slide-list file and validate it
    validate_deck(obj)       raise DeckError naming the slide index and field
    slides_from_plan(model)  plan_slides(model) specs as a valid slide list

Layout set (CSS in assets/render/deck.css and research.css; limits keep
every field combination inside the layout at 1280x720):

    cover        title(120), eyebrow?, subtitle?, date?      (deck defaults fill gaps)
    section      title, eyebrow?, sub?                       (divider)
    agenda       title(30), items[{title(20), desc?(55)}] 2-5 (rows numbered 01..N)
    statement    headline(150), stats?[{value(40), label(90), ref?}] (up to 3 stat tiles)
    bullets      title, bullets[{text(200), refs?}], refs?   (up to 5 points)
    two_column   title, left/right {title, body(350) | bullets x3(120)} (two titled panels)
    three_values title(42), values[{title(45), body(200)}] x3, note?(100)
    compare      title(35), options[{tag?(30), name(45), rows 1-3x(60), kicker?(80)}] x2
    bars         title, bars[{label(60), value, display(16)}] 2-6, note?(200) (scaled to the max)
    facet        title, sides[{label(40), summary(200)}] 1-4 | bullets x3 (fallback)
    quote        quote(400), attribution?(120), title?(35), eyebrow?
    sources      title(40), sources[{n, title(70), publisher?(60), url?}] 1-12, more_sources?
    closing      headline(90), steps[] 1-5x(120)             (numbered next steps)

CLI (E5-R4): write the research slide plan for a report as an editable
slide list an agent can reorder, rewrite, and render:

    python3 deck_spec.py --report report.md [--manifest run_manifest.json] \
        [--format comprehensive-report] --out slides.json

--check validates an existing slide list without rendering or writing
anything: it prints ``valid: N slides`` and exits 0, or prints every
error naming the slide index and field and exits 1.

    python3 deck_spec.py --check deck.json
"""
import argparse
import json
import sys
from pathlib import Path

from build_render_model import build_model
from slide_plan import FORMAT_DISPLAY, clip, plan_slides

LAYOUTS = (
    "cover", "section", "agenda", "statement", "bullets", "two_column",
    "three_values", "compare", "bars", "facet", "quote", "sources", "closing",
)

# Per layout: (required fields, optional content fields). notes/section are
# allowed on every slide. Mirrors schemas/deck_spec.schema.json oneOf branches.
LAYOUT_FIELDS = {
    "cover": ({"title"}, {"eyebrow", "subtitle", "date"}),
    "section": ({"title"}, {"eyebrow", "sub"}),
    "agenda": ({"title", "items"}, {"eyebrow"}),
    "statement": ({"headline"}, {"eyebrow", "stats"}),
    "bullets": ({"title", "bullets"}, {"eyebrow", "refs"}),
    "two_column": ({"title", "left", "right"}, {"eyebrow"}),
    "three_values": ({"title", "values"}, {"eyebrow", "note"}),
    "compare": ({"title", "options"}, {"eyebrow"}),
    "bars": ({"title", "bars"}, {"eyebrow", "note"}),
    "facet": ({"title"}, {"eyebrow", "sides", "bullets"}),
    "quote": ({"quote"}, {"title", "eyebrow", "attribution"}),
    "sources": ({"title", "sources"}, {"eyebrow", "more_sources"}),
    "closing": ({"headline", "steps"}, {"eyebrow"}),
}
COMMON_FIELDS = ("notes", "section")

TITLE_MAX = 90          # slide titles (the cover allows 120, like slide_plan)
COVER_TITLE_MAX = 120
HEADLINE_MAX = 200

# Per-layout title/headline caps: the tallest fixed content per layout leaves
# less room for a wrapped slide title. Verified against rendered geometry at
# 1280x720 (see tests/test_deck_spec.py).
TITLE_LIMITS = {
    "cover": COVER_TITLE_MAX,
    "agenda": 30,
    "three_values": 42,
    "compare": 35,
    "quote": 35,
    "sources": 40,
}


class DeckError(ValueError):
    """A slide-list validation problem; the message names the slide and field."""


def _string(value, where, limit=None):
    if not isinstance(value, str):
        raise DeckError(f"{where}: expected a string, got {type(value).__name__}")
    if not value.strip():
        raise DeckError(f"{where}: must not be empty")
    if limit is not None and len(value) > limit:
        raise DeckError(f"{where}: longer than {limit} characters ({len(value)})")
    return value


def _citation(value, where, allow_null=False):
    ok = isinstance(value, int) and not isinstance(value, bool) and value >= 1
    if not ok:
        raise DeckError(f"{where}: expected a [N] citation integer >= 1"
                        + (" or null" if allow_null else ""))
    return value


def _number_min(value, where, low=0):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < low:
        raise DeckError(f"{where}: expected a number >= {low}, got {value!r}")
    return value


def _refs(value, where):
    if not isinstance(value, list):
        raise DeckError(f"{where}: expected a list of [N] citation integers")
    for j, r in enumerate(value):
        _citation(r, f"{where}[{j}]")
    return value


def _string_list(value, where, low, high, limit):
    if not isinstance(value, list):
        raise DeckError(f"{where}: expected a list of strings")
    if not low <= len(value) <= high:
        raise DeckError(f"{where}: expected {low} to {high} entries, got {len(value)}")
    for j, item in enumerate(value):
        _string(item, f"{where}[{j}]", limit=limit)
    return value


def _bullet(value, where, limit=200):
    if not isinstance(value, dict):
        raise DeckError(f"{where}: expected an object")
    unknown = set(value) - {"text", "refs"}
    if unknown:
        raise DeckError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    if "text" not in value:
        raise DeckError(f"{where}.text: required")
    _string(value["text"], f"{where}.text", limit=limit)
    if value.get("refs") is not None:
        _refs(value["refs"], f"{where}.refs")
    return value


def _bullets(value, where, high, text_limit=200):
    if not isinstance(value, list):
        raise DeckError(f"{where}: expected a list of bullets")
    if len(value) > high:
        raise DeckError(f"{where}: at most {high} bullets, got {len(value)}")
    for j, item in enumerate(value):
        _bullet(item, f"{where}[{j}]", limit=text_limit)
    return value


def _panel(value, where):
    if not isinstance(value, dict):
        raise DeckError(f"{where}: expected an object")
    unknown = set(value) - {"title", "body", "bullets"}
    if unknown:
        raise DeckError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    if "title" not in value:
        raise DeckError(f"{where}.title: required")
    _string(value["title"], f"{where}.title", limit=60)
    has_body, has_bullets = "body" in value, "bullets" in value
    if not (has_body or has_bullets):
        raise DeckError(f"{where}: needs body or bullets")
    if has_body and has_bullets:
        raise DeckError(f"{where}: use body or bullets, not both")
    if has_body:
        _string(value["body"], f"{where}.body", limit=350)
    else:
        _bullets(value["bullets"], f"{where}.bullets", 3, text_limit=120)
        if not value["bullets"]:
            raise DeckError(f"{where}.bullets: must not be empty")
    return value


def _entries(value, where, low, high, required, optional, checks):
    """A bounded list of objects; checks maps field name -> check(value, where)."""
    if not isinstance(value, list):
        raise DeckError(f"{where}: expected a list")
    if not low <= len(value) <= high:
        raise DeckError(f"{where}: expected {low} to {high} entries, got {len(value)}")
    for j, item in enumerate(value):
        at = f"{where}[{j}]"
        if not isinstance(item, dict):
            raise DeckError(f"{at}: expected an object")
        unknown = set(item) - set(required) - set(optional)
        if unknown:
            raise DeckError(f"{at}: unknown field(s) {', '.join(sorted(unknown))}")
        for name in required:
            if name not in item:
                raise DeckError(f"{at}.{name}: required")
        for name, check in checks.items():
            if name in item and item[name] is not None:
                check(item[name], f"{at}.{name}")
    return value


def _check_items(value, where):
    return _entries(value, where, 2, 5, ("title",), ("desc",), {
        "title": lambda v, w: _string(v, w, limit=20),
        "desc": lambda v, w: _string(v, w, limit=55),
    })


def _check_stats(value, where):
    return _entries(value, where, 0, 3, ("value", "label"), ("ref",), {
        "value": lambda v, w: _string(v, w, limit=40),
        "label": lambda v, w: _string(v, w, limit=90),
        "ref": lambda v, w: _citation(v, w, allow_null=True),
    })


def _check_values(value, where):
    return _entries(value, where, 3, 3, ("title", "body"), (), {
        "title": lambda v, w: _string(v, w, limit=45),
        "body": lambda v, w: _string(v, w, limit=200),
    })


def _check_options(value, where):
    return _entries(value, where, 2, 2, ("name", "rows"), ("tag", "kicker"), {
        "tag": lambda v, w: _string(v, w, limit=30),
        "name": lambda v, w: _string(v, w, limit=45),
        "rows": lambda v, w: _string_list(v, w, 1, 3, 60),
        "kicker": lambda v, w: _string(v, w, limit=80),
    })


def _check_bars(value, where):
    return _entries(value, where, 2, 6, ("label", "value", "display"), (), {
        "label": lambda v, w: _string(v, w, limit=60),
        "value": _number_min,
        "display": lambda v, w: _string(v, w, limit=16),
    })


def _check_sides(value, where):
    return _entries(value, where, 1, 4, ("label", "summary"), (), {
        "label": lambda v, w: _string(v, w, limit=40),
        "summary": lambda v, w: _string(v, w, limit=200),
    })


def _check_sources(value, where):
    return _entries(value, where, 1, 12, ("n", "title"), ("publisher", "url"), {
        "n": lambda v, w: _citation(v, w),
        "title": lambda v, w: _string(v, w, limit=70),
        "publisher": lambda v, w: _string(v, w, limit=60),
        "url": lambda v, w: _string(v, w, limit=300),
    })


def _check_more_sources(value, where):
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise DeckError(f"{where}: expected an integer >= 0, got {value!r}")
    return value


# Content-field checks shared by name across layouts; limits mirror the schema.
FIELD_CHECKS = {
    "eyebrow": lambda v, w: _string(v, w, limit=120),
    "subtitle": lambda v, w: _string(v, w, limit=160),
    "sub": lambda v, w: _string(v, w, limit=200),
    "note": lambda v, w: _string(v, w, limit=200),
    "attribution": lambda v, w: _string(v, w, limit=120),
    "quote": lambda v, w: _string(v, w, limit=400),
    "refs": _refs,
    "bullets": lambda v, w: _bullets(v, w, 5),
    "items": _check_items,
    "stats": _check_stats,
    "left": _panel,
    "right": _panel,
    "values": _check_values,
    "options": _check_options,
    "bars": _check_bars,
    "sides": _check_sides,
    "sources": _check_sources,
    "more_sources": _check_more_sources,
    "steps": lambda v, w: _string_list(v, w, 1, 5, 120),
    "date": lambda v, w: _string(v, w, limit=80),
}

# Field limits that differ by layout (schema mirrors these per branch).
NOTE_LIMITS = {"three_values": 100, "bars": 200}
HEADLINE_LIMITS = {"statement": 150, "closing": 90}


def _validate_slide(index, slide):
    if not isinstance(slide, dict):
        raise DeckError(f"slide {index}: expected an object")
    layout = slide.get("layout")
    if layout not in LAYOUT_FIELDS:
        raise DeckError(f"slide {index}.layout: expected one of "
                        f"{', '.join(LAYOUTS)} (got {layout!r})")
    where = f"slide {index} ({layout})"
    required, optional = LAYOUT_FIELDS[layout]
    unknown = set(slide) - required - optional - set(COMMON_FIELDS) - {"layout"}
    if unknown:
        raise DeckError(f"{where}: unknown field(s) {', '.join(sorted(unknown))}")
    for name in required:
        if name not in slide:
            raise DeckError(f"{where}.{name}: required")
    title_limit = TITLE_LIMITS.get(layout, TITLE_MAX)
    for name in sorted(set(required) | set(optional)):
        if name not in slide:
            continue
        value = slide[name]
        if name in ("title", "headline"):
            limit = (title_limit if name == "title"
                     else HEADLINE_LIMITS.get(layout, HEADLINE_MAX))
            _string(value, f"{where}.{name}", limit=limit)
        elif value is None:
            if name != "date":          # cover date may be an explicit null
                raise DeckError(f"{where}.{name}: must not be null")
        elif name == "note":
            _string(value, f"{where}.{name}", limit=NOTE_LIMITS.get(layout, 200))
        else:
            FIELD_CHECKS[name](value, f"{where}.{name}")
    if layout == "facet":
        # the facet fallback carries at most 3 bullets (the plan's condensing trim)
        if slide.get("bullets") is not None:
            _bullets(slide["bullets"], f"{where}.bullets", 3)
        if not slide.get("sides") and not slide.get("bullets"):
            raise DeckError(f"{where}: needs sides or bullets")
    if slide.get("section") is not None:
        _string(slide["section"], f"{where}.section", limit=60)
    if slide.get("notes") is not None:
        _string(slide["notes"], f"{where}.notes")
    return slide


def iter_deck_errors(deck):
    """Yield every validation problem as a message: deck-level faults in
    check order, then one per faulty slide (its first error). Empty when
    the deck is valid."""
    if not isinstance(deck, dict):
        yield "deck: expected a JSON object"
        return
    unknown = set(deck) - {"title", "subtitle", "date", "eyebrow", "footer_section", "slides"}
    if unknown:
        yield f"deck: unknown field(s) {', '.join(sorted(unknown))}"
    if "title" not in deck:
        yield "deck.title: required"
    else:
        try:
            _string(deck["title"], "deck.title", limit=COVER_TITLE_MAX)
        except DeckError as exc:
            yield str(exc)
    for name in ("subtitle", "eyebrow", "footer_section"):
        if deck.get(name) is not None:
            try:
                _string(deck[name], f"deck.{name}", limit=160 if name == "subtitle" else 200)
            except DeckError as exc:
                yield str(exc)
    if deck.get("date") is not None:
        try:
            _string(deck["date"], "deck.date", limit=80)
        except DeckError as exc:
            yield str(exc)
    slides = deck.get("slides")
    if not isinstance(slides, list) or not slides:
        yield "deck.slides: expected a non-empty list of slides"
        return
    for index, slide in enumerate(slides, start=1):
        try:
            _validate_slide(index, slide)
        except DeckError as exc:
            yield str(exc)


def validate_deck(deck):
    """Validate a slide-list deck dict; raise DeckError naming the slide and field."""
    for message in iter_deck_errors(deck):
        raise DeckError(message)
    return deck


def deck_errors(deck):
    """Every validation problem as a message; empty when the deck is valid."""
    return list(iter_deck_errors(deck))


def load_deck(path):
    """Read and validate a slide-list JSON file; DeckError carries the path."""
    try:
        with open(path, encoding="utf-8") as f:
            deck = json.load(f)
    except FileNotFoundError:
        raise DeckError(f"file not found: {path}") from None
    except json.JSONDecodeError as exc:
        raise DeckError(f"{path} is not valid JSON ({exc})") from None
    try:
        validate_deck(deck)
    except DeckError as exc:
        raise DeckError(f"{path}: {exc}") from None
    return deck


def slides_from_plan(model):
    """plan_slides(model) specs as a valid slide-list deck dict.

    The research slide kinds map onto the generic layouts — cover, statement,
    finding/section -> bullets, facet, sources — keeping every note, eyebrow,
    section, and stat ref so rendering the export reproduces the planned deck
    byte for byte whenever the plan respects the layout limits. Statement
    headlines are re-clipped to the layout's fit limit (the plan's 20-word
    trim can exceed it); everything else the plan emits already sits inside
    the caps.
    """
    specs = plan_slides(model)
    cover = specs[0]
    slides = [{
        "layout": "cover",
        "title": cover["title"],
        "eyebrow": cover["eyebrow"],
        "subtitle": cover["subtitle"],
        "date": cover["date"],
        "notes": cover["notes"],
    }]
    for spec in specs[1:]:
        base = {"eyebrow": spec["eyebrow"], "section": spec["section"],
                "notes": spec["notes"]}
        kind = spec["kind"]
        if kind == "statement":
            # re-clip: the plan's 20-word headline can exceed the layout's
            # 150-character fit limit; the layout cap wins on export
            slides.append({"layout": "statement",
                           "headline": clip(spec["title"], HEADLINE_LIMITS["statement"]),
                           **base,
                           "stats": [{"value": s["value"], "label": s["label"], "ref": s["ref"]}
                                     for s in spec["stats"]]})
        elif kind in ("finding", "section"):
            slides.append({"layout": "bullets", "title": spec["title"], **base,
                           "bullets": [{"text": b["text"], "refs": b["refs"]}
                                       for b in spec.get("bullets") or []]})
        elif kind == "facet":
            slide = {"layout": "facet", "title": spec["title"], **base}
            if spec.get("sides"):
                slide["sides"] = [{"label": s["label"], "summary": s["summary"]}
                                  for s in spec["sides"]]
            else:
                slide["bullets"] = [{"text": b["text"], "refs": b["refs"]}
                                    for b in spec.get("bullets") or []]
            slides.append(slide)
        else:  # sources
            slides.append({"layout": "sources", "title": spec["title"], **base,
                           "sources": [{"n": s["n"], "title": s["title"],
                                        "publisher": s["publisher"], "url": s["url"]}
                                       for s in spec["sources"]],
                           "more_sources": spec["more_sources"]})
    deck = {"title": cover["title"], "subtitle": cover["subtitle"],
            "date": cover["date"], "eyebrow": cover["eyebrow"], "slides": slides}
    return validate_deck(deck)


def _check(path):
    """--check: validate a slide-list file; print every error or 'valid: N slides'."""
    try:
        with open(path, encoding="utf-8") as f:
            deck = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: file not found: {path}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} is not valid JSON ({exc})", file=sys.stderr)
        return 1
    errors = deck_errors(deck)
    if errors:
        for message in errors:
            print(f"ERROR: {path}: {message}", file=sys.stderr)
        return 1
    print(f"valid: {len(deck['slides'])} slides")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Validate a deck slide list (--check) or write a report's "
                    "research slide plan as an editable slide list (E5-R4)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 deck_spec.py --check deck.json
  python3 deck_spec.py --report report.md --out slides.json
  python3 deck_spec.py --report report.md --manifest run_manifest.json --out slides.json
  python3 render_deck.py --slides slides.json --out deck.html
        """,
    )
    ap.add_argument("--check", metavar="[deck.json]", default=None,
                    help="validate a slide list and exit: prints 'valid: N slides' "
                         "or every error naming the slide index and field; writes no file")
    ap.add_argument("--report", "-r", default=None,
                    help="report markdown; the model is built in-process")
    ap.add_argument("--manifest", "-m", default=None, help="run_manifest.json for --report")
    ap.add_argument("--format", "-f", default=None, choices=sorted(FORMAT_DISPLAY.keys()),
                    help="report format; default: manifest value, else inferred")
    ap.add_argument("--out", "-o", default=None, help="write the slide-list JSON here")
    args = ap.parse_args(argv)

    if args.check:
        exclusive = [flag for flag, value in (("--report", args.report),
                                              ("--manifest", args.manifest),
                                              ("--format", args.format),
                                              ("--out", args.out)) if value]
        if exclusive:
            ap.error(f"--check validates one deck file; not allowed with "
                     f"{', '.join(exclusive)}")
        return _check(args.check)
    if not args.report:
        ap.error("give --report [report.md] --out [slides.json] to export a plan, "
                 "or --check [deck.json] to validate an existing slide list")
    if not args.out:
        ap.error("--out is required with --report")

    report_path = Path(args.report)
    if not report_path.exists():
        print(f"ERROR: report not found: {report_path}", file=sys.stderr)
        return 1
    manifest = None
    if args.manifest:
        try:
            with open(args.manifest, encoding="utf-8") as f:
                manifest = json.load(f)
        except FileNotFoundError:
            print(f"ERROR: file not found: {args.manifest}", file=sys.stderr)
            return 1
        except json.JSONDecodeError as exc:
            print(f"ERROR: {args.manifest} is not valid JSON ({exc})", file=sys.stderr)
            return 1
    model = build_model(report_path.read_text(encoding="utf-8"), manifest, args.format)
    deck = slides_from_plan(model)
    out = Path(args.out)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(deck, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {out} ({len(deck['slides'])} slides)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
