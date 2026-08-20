#!/usr/bin/env python3
"""Rebuild data/site.js from ijustwanttoeat.com.

The blog runs on Squarespace, which will hand back any page as JSON if you ask
for it -- append ?format=json. No key, no login, nothing that expires. That is
the whole integration: one paginated walk of the /post collection plus one read
of each hand-built index page (Michelin, recipes, map, about).

Run it:

    python3 scripts/update.py --dry-run    # print what would change
    python3 scripts/update.py              # write data/site.js

Instagram is best-effort and off unless IG_HANDLE is set; see the README for
why it cannot be relied on.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ASSETS = ROOT / "assets"

SITE = "https://www.ijustwanttoeat.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# How deep to walk the archive. He has 2300+ posts going back to 2011; the page
# only ever renders a few hundred, and every card is a live request to his CDN.
PAGES = int(os.environ.get("IJWTE_PAGES", "30"))  # 20 items a page

# A run this far below the previous one is treated as a broken read, not news.
SHRINK_LIMIT = 0.5


# ─────────────────────────────────────────────────────────────────────────────
# fetching
# ─────────────────────────────────────────────────────────────────────────────


def get(url: str, tries: int = 3) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001 - retry anything transient
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"GET {url} failed: {last}")


def get_json(url: str) -> dict:
    return json.loads(get(url).decode("utf-8", "replace"))


def sq(path: str, offset: int | None = None) -> dict:
    """Fetch a Squarespace page as JSON."""
    url = f"{SITE}/{path.strip('/')}?format=json"
    if offset:
        url += f"&offset={offset}"
    return get_json(url)


# ─────────────────────────────────────────────────────────────────────────────
# text helpers
# ─────────────────────────────────────────────────────────────────────────────


def clean(s: str | None) -> str:
    """HTML -> plain text, with the entity soup Squarespace stores unwound."""
    s = re.sub(r"<[^>]+>", " ", s or "")
    for _ in range(2):  # titles are double-escaped often enough to matter
        s = html.unescape(s)
    s = s.replace(" ", " ").replace("​", "")
    return re.sub(r"\s+", " ", s).strip()


def fold(s: str) -> str:
    """Lowercase, accent-stripped, for matching only."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.lower()


# ─────────────────────────────────────────────────────────────────────────────
# classification
#
# Two signals: the title he wrote and the slug he chose. The slug is the better
# one -- it is keyword-stuffed for search, so it names the cuisine and the town
# even when the title is a tease ("What went wrong with Happy Tuna").
# ─────────────────────────────────────────────────────────────────────────────

# (key, label, area, slug/title patterns). Order matters: first hit wins, so
# neighbourhoods sit above the boroughs and towns that contain them.
PLACES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("jersey-city", "Jersey City", "nj", ("jersey city", "jersey-city", "journal square", "newport centre")),
    ("hoboken", "Hoboken", "nj", ("hoboken",)),
    ("weehawken", "Weehawken", "nj", ("weehawken", "port imperial")),
    ("brooklyn", "Brooklyn", "nyc", ("brooklyn", "dumbo", "greenpoint", "williamsburg", "bushwick", "park slope", "bed-stuy")),
    ("queens", "Queens", "nyc", ("queens", "astoria", "flushing", "long island city", "lic ")),
    ("bronx", "The Bronx", "nyc", ("the bronx", "-bronx", " bronx")),
    ("staten-island", "Staten Island", "nyc", ("staten island",)),
    (
        "manhattan",
        "Manhattan",
        "nyc",
        (
            "nyc", "new york", "manhattan", "times square", "midtown", "chelsea",
            "tribeca", "soho", "noho", "harlem", "lower east side", "east village",
            "west village", "greenwich village", "upper east", "upper west",
            "hell's kitchen", "hells kitchen", "flatiron", "gramercy", "chinatown",
            "little italy", "koreatown", "bryant park", "financial district",
            "murray hill", "nolita", "meatpacking",
        ),
    ),
    ("north-jersey", "North Jersey", "nj", (
        "guttenberg", "union city", "west new york", "fort lee", "edgewater",
        "englewood", "hackensack", "paramus", "montclair", "newark", "harrison",
        "kearny", "bayonne", "secaucus", "north bergen", "cliffside", "ridgewood",
        "teaneck", "clifton", "passaic", "morristown", "summit", "millburn",
        "jersey shore", "rutherford", "lyndhurst", "nutley", "belleville",
    )),
    ("central-jersey", "Central & South Jersey", "nj", (
        "freehold", "manalapan", "edison", "red bank", "redbank", "rahway",
        "princeton", "new brunswick", "asbury park", "long branch", "marlboro",
        "old bridge", "woodbridge", "cranford", "westfield", "atlantic city",
        "cape may", "hoboken shore", "matawan", "howell", "toms river",
    )),
]

# Neighbourhoods worth naming on the card, above the borough.
HOODS: list[tuple[str, tuple[str, ...]]] = [
    ("Jersey City Heights", ("jersey city heights", "jc heights")),
    ("Dumbo", ("dumbo",)),
    ("Greenpoint", ("greenpoint",)),
    ("Williamsburg", ("williamsburg",)),
    ("Times Square", ("times square", "times-square", "times squares")),
    ("Midtown", ("midtown", "bryant park", "hell's kitchen", "hells kitchen")),
    ("Chelsea", ("chelsea",)),
    ("Tribeca", ("tribeca",)),
    ("SoHo", ("soho", "nolita")),
    ("Lower East Side", ("lower east side", "-les-")),
    ("East Village", ("east village",)),
    ("West Village", ("west village", "greenwich village", "meatpacking")),
    ("Upper East Side", ("upper east",)),
    ("Upper West Side", ("upper west",)),
    ("Harlem", ("harlem",)),
    ("Flatiron", ("flatiron", "gramercy", "union square")),
    ("Chinatown", ("chinatown", "little italy")),
    ("Koreatown", ("koreatown", "k-town")),
    ("Financial District", ("financial district", "-fidi", "seaport")),
    ("Astoria", ("astoria",)),
    ("Newport", ("newport", "paulus hook", "journal square", "grove street")),
    ("Washington Street", ("washington street",)),
]

# Cuisine. These are scored rather than raced: a word in the slug or the title
# is worth far more than the same word buried in the body, because the slug is
# keyword-stuffed for search and so names the cuisine outright. Racing them in
# order got "La Brochette Steakhouse" filed under French, since "brochette" is
# a French word before it is the name of a steakhouse.
CUISINES: list[tuple[str, str, str, tuple[str, ...]]] = [
    ("pizza", "Pizza", "🍕", ("pizza", "pizzeria", "pizzas", "slice shop", "spumoni", "neapolitan", "sicilian slice")),
    ("sushi", "Sushi & Japanese", "🍣", ("sushi", "japanese", "omakase", "izakaya", "yakiniku", "sake", "ootoya", "donburi", "tokyo", "nigiri", "sashimi", "japan")),
    ("ramen", "Ramen & Noodles", "🍜", ("ramen", "noodle", "noodles", "pho", "udon", "soba")),
    ("korean", "Korean", "🥢", ("korean", "korea", "jungsik", "bibimbap", "kbbq", "jeju", "banchan")),
    ("chinese", "Chinese", "🥟", ("chinese", "china", "dim sum", "dumpling", "dumplings", "szechuan", "sichuan", "cantonese", "hot pot", "xiao long bao", "peking")),
    ("indian", "Indian", "🍛", ("indian", "india", "curry", "tandoor", "tandoori", "biryani", "bangalore", "baadshah", "dosa", "masala", "kati roll", "chaat", "paneer", "naan")),
    ("thai", "Thai & Southeast Asian", "🌶️", ("thai", "thailand", "vietnamese", "vietnam", "banh mi", "malaysian", "singaporean", "filipino", "indonesian", "satay", "pad thai")),
    ("french", "French", "🥐", ("french", "france", "bistro", "brasserie", "croissant", "boulud", "bernardin", "kreuther", "jean-georges", "choc-o-pain", "fauchon", "pavillon", "pavillion", "ratatouille", "souffle", "soufflé", "galette", "bugnes", "escargot", "confit")),
    ("italian", "Italian", "🍝", ("italian", "italy", "trattoria", "osteria", "pasta", "risotto", "cacio", "leonetta", "corto", "ci siamo", "mercato", "spaghetti", "lasagna", "carbonara", "focaccia")),
    ("mexican", "Mexican & Latin", "🌮", ("mexican", "mexico", "taco", "tacos", "taqueria", "cantina", "oaxaca", "oxomoco", "cuban", "rumba", "arepas", "peruvian", "colombian", "empanada", "empanadas", "meximodo", "birria", "ceviche")),
    ("mediterranean", "Mediterranean", "🫒", ("mediterranean", "greek", "turkish", "lebanese", "israeli", "falafel", "hummus", "shawarma", "solaz", "spanish", "tapas", "paella", "casa mono", "mezze", "kebab")),
    ("steak", "Steak & Chops", "🥩", ("steak", "steaks", "steakhouse", "brochette", "longhorn", "chophouse", "prime rib", "carnivore", "ribeye", "porterhouse", "wagyu")),
    ("burger", "Burgers", "🍔", ("burger", "burgers", "smash burger", "smashburger", "white mana", "shake shack", "cheeseburger", "patty melt")),
    ("seafood", "Seafood", "🦞", ("seafood", "oyster", "oysters", "lobster", "crab", "clam", "clams", "fish market", "raw bar", "tuna", "scallop", "shrimp")),
    ("bbq", "BBQ & Smoke", "🔥", ("bbq", "barbecue", "brisket", "smokehouse", "ribs", "pit beef")),
    ("brunch", "Brunch", "🍳", ("brunch", "pancake", "pancakes", "waffle", "waffles", "eggs", "breakfast", "french toast", "benedict", "omelette", "mimosa")),
    ("bakery", "Bakery & Pastry", "🥖", ("bakery", "bakehouse", "bread", "pastry", "pastries", "patisserie", "boulangerie", "donut", "donuts", "doughnut", "cake", "tart", "cookie", "cookies", "brioche", "baguette", "sourdough", "macaron", "supermoon", "babka", "croissants")),
    ("dessert", "Dessert & Ice Cream", "🍨", ("ice cream", "gelato", "dessert", "desserts", "chocolate", "morgenstern", "sundae", "s'mores", "smores", "candy", "creamery", "soft serve", "sorbet")),
    ("coffee", "Coffee & Tea", "☕", ("coffee", "espresso", "cafe", "café", "roaster", "roastery", "matcha", "afternoon tea", "bubble tea", "java factory", "latte", "cappuccino")),
    ("bar", "Bars & Cocktails", "🍸", ("cocktail", "cocktails", "bar", "pub", "speakeasy", "whiskey", "whisky", "wine", "wines", "beer", "brewery", "biergarten", "paulaner", "dynamo room", "irish pub", "tavern", "mixology")),
    ("vegan", "Vegan & Vegetarian", "🌱", ("vegan", "vegetarian", "plant-based", "dirt candy", "meatless")),
    ("deli", "Deli & Sandwiches", "🥪", ("deli", "sandwich", "sandwiches", "bodega", "french dip", "hoagie", "bagel", "bagels", "pastrami", "panini")),
    ("american", "American", "🇺🇸", ("american", "diner", "comfort food", "southern", "cajun", "soul food", "new american", "gastropub", "fried chicken", "wings")),
]

# Places he has eaten that are nowhere near home. Filed as travel rather than
# left in the "elsewhere" bucket, because a Paris post is not a failed match.
AWAY = (
    "paris", "lyon", "nice, france", "provence", "bordeaux", "marseille",
    "london", "tokyo, japan", "rome", "florence", "venice", "barcelona",
    "madrid", "lisbon", "amsterdam", "berlin", "montreal", "toronto",
    "miami", "savannah", "charleston", "new orleans", "chicago", "boston",
    "los angeles", "san francisco", "las vegas", "seattle", "austin",
    "puerto rico", "cancun", "tulum", "jamaica", "bahamas", "iceland",
    "my trip to", "trip to", "vacation in", "while in",
)

# His recipe index links out to a restaurant review in passing - the dish came
# from there - and nothing in the markup separates that from the recipes
# themselves, so it is named here rather than guessed at.
RECIPE_SKIP = {"momofuku noodle bar"}

MICHELIN_HINTS = (
    "michelin", "eleven madison", "le bernardin", "per se", "jean-georges",
    "gabriel kreuther", "jungsik", "gramercy tavern", "daniel", "estela",
    "musket room", "oxomoco", "casa mono", "dirt candy", "jeju noodle",
    "the modern", "le pavillon", "le pavillion", "cafe boulud", "hakkasan",
)


_WORD_CACHE: dict[str, re.Pattern[str]] = {}


def word(needle: str) -> re.Pattern[str]:
    """`bar` must not match `barbecue`, and `sake` must not match `pancakes`."""
    pat = _WORD_CACHE.get(needle)
    if pat is None:
        pat = re.compile(r"(?<![a-z0-9])" + re.escape(needle).replace(r"\ ", r"[\s\-]+") + r"(?![a-z0-9])")
        _WORD_CACHE[needle] = pat
    return pat


def match(hay: str, needles: tuple[str, ...]) -> bool:
    return any(word(n).search(hay) for n in needles)


def score(needles: tuple[str, ...], slug: str, title: str, body: str) -> int:
    """4 for the slug, 3 for the title, 1 for the body, capped per source."""
    total = 0
    for source, weight in ((slug, 4), (title, 3), (body, 1)):
        hits = sum(1 for n in needles if word(n).search(source))
        if hits:
            total += weight + min(hits - 1, 2)
    return total


def classify(title: str, url: str, body: str) -> dict:
    """Work out what a post is, where it is, and what he ate."""
    t = fold(title)
    slug = fold(url).replace("/", " ").replace("-", " ")
    b = fold(body[:1200])
    hay = f"{t} {slug}"

    if "product review" in t or "product-review" in fold(url) or "sponsored" in t:
        kind = "product"
    elif re.match(r"^recipe\b", t) or "/recipe" in fold(url):
        kind = "recipe"
    else:
        kind = "review"

    # Where. Title and slug first; only fall back to the body, since a review of
    # a Hoboken place will often mention Manhattan in passing.
    area_key, area_label, region = "", "", ""
    for source in (hay, b):
        for key, label, reg, pats in PLACES:
            if match(source, pats):
                area_key, area_label, region = key, label, reg
                break
        if area_key:
            break
    if not area_key:
        if match(hay, AWAY):
            area_key, area_label, region = "away", "Away from home", "away"
        else:
            area_key, area_label, region = "elsewhere", "Elsewhere", "other"

    hood = ""
    for label, pats in HOODS:
        if match(hay, pats):
            hood = label
            break

    # What. Highest score wins; ties break toward the earlier, more specific
    # entry, which is why pizza sits above italian and ramen above japanese.
    cuisine, cui_label, emoji, best = "other", "Other", "✦", 0
    for key, label, em, pats in CUISINES:
        s = score(pats, slug, t, b)
        if s > best:
            cuisine, cui_label, emoji, best = key, label, em, s

    return {
        "kind": kind,
        "area": area_key,
        "areaLabel": area_label,
        "region": region,
        "hood": hood,
        "cuisine": cuisine,
        "cuisineLabel": cui_label,
        "emoji": emoji,
        "starred": match(f"{hay} {b}", MICHELIN_HINTS),
    }


TRAIL = re.compile(
    r"\s*(?:,?\s*in\s+)?(?:[A-Z][\w.'’-]*(?:\s+[A-Z][\w.'’-]*){0,3})?,?\s*"
    r"(?:NJ|NY|New Jersey|New York|NYC)\s*[!?.]*$"
)


def place_name(title: str) -> str:
    """Best guess at just the restaurant, for the card's second line."""
    name = re.sub(r"^(Restaurant Review|Review|Product Review)\s*[:\-]\s*", "", title, flags=re.I)
    name = TRAIL.sub("", name).strip(" ,-–—")
    return name or title


# ─────────────────────────────────────────────────────────────────────────────
# scraping
# ─────────────────────────────────────────────────────────────────────────────


def img_url(raw: str | None, width: int = 1000) -> str:
    """Squarespace serves any stored image at any width. Ask for a sane one."""
    if not raw:
        return ""
    raw = raw.split("?")[0]
    if raw.startswith("//"):
        raw = "https:" + raw
    return f"{raw}?format={width}w"


def scrape_posts() -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    offset: int | None = None

    for page in range(PAGES):
        try:
            payload = sq("post", offset)
        except Exception as exc:  # noqa: BLE001
            print(f"  page {page + 1} failed ({exc}); stopping here", file=sys.stderr)
            break

        items = payload.get("items") or []
        if not items:
            break

        for it in items:
            pid = str(it.get("id") or "")
            if not pid or pid in seen:
                continue
            seen.add(pid)

            title = clean(it.get("title"))
            url = it.get("fullUrl") or ""
            if not title or not url:
                continue

            ts = int(it.get("publishOn") or 0) // 1000
            meta = classify(title, url, clean(it.get("body")))
            out.append(
                {
                    "id": pid,
                    "t": title,
                    "n": place_name(title),
                    "u": SITE + url,
                    "d": ts,
                    "img": img_url(it.get("assetUrl")),
                    **meta,
                }
            )

        offset = items[-1].get("publishOn")
        print(f"  page {page + 1}: {len(out)} posts", file=sys.stderr)
        time.sleep(0.5)

    out.sort(key=lambda p: p["d"], reverse=True)
    return out


LINK = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)


def walk_strings(node) -> "list[str]":
    """Every string anywhere in a decoded JSON tree."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for v in node.values() for s in walk_strings(v)]
    if isinstance(node, list):
        return [s for v in node for s in walk_strings(v)]
    return []


def page_links(path: str, keep: str) -> list[dict]:
    """Pull the hand-built link list off one of his index pages.

    Decoding through json.loads rather than unescaping the raw text by hand:
    hand-unescaping leaves \\u00e9 sitting in the middle of "banana souffle".
    """
    raw = "\n".join(walk_strings(sq(path)))

    found: list[dict] = []
    seen: set[str] = set()
    for href, label in LINK.findall(raw):
        name = clean(label)
        href = html.unescape(href)
        if not name or keep not in href:
            continue
        if href.startswith("/"):
            href = SITE + href
        href = href.replace("http://www.", "https://www.")
        key = href.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        found.append({"n": re.sub(r"^Recipe\s*:\s*", "", name).strip(), "u": href})
    return found


# Posts old enough to predate the current CDN still carry an image URL, but it
# resolves to Squarespace's 2 KB grey placeholder rather than his photograph.
# It answers 200, so only the size gives it away.
PLACEHOLDER_BYTES = 8_000


def image_ok(url: str) -> bool:
    if not url:
        return False
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status != 200:
                return False
            size = int(r.headers.get("Content-Length") or 0)
    except Exception:  # noqa: BLE001 - an unreachable image is an absent one
        return False
    # No length header at all: trust it rather than throw away a real photo.
    return size == 0 or size >= PLACEHOLDER_BYTES


def scrape_collection(path: str, limit: int = 40, verify: bool = False) -> list[dict]:
    payload = sq(path)
    out = []
    for it in (payload.get("items") or [])[:limit]:
        title = clean(it.get("title"))
        url = it.get("fullUrl") or ""
        if not title or not url:
            continue
        img = img_url(it.get("assetUrl"), 800)
        if verify and img and not image_ok(img):
            img = ""  # the page falls back to a typographic card
        out.append(
            {
                "t": title,
                "u": SITE + url,
                "d": int(it.get("publishOn") or 0) // 1000,
                "img": img,
            }
        )
    return out


def scrape_instagram(handle: str) -> dict | None:
    """Best-effort. See the README: this endpoint is metered hard and will fail."""
    url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={handle}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "X-IG-App-ID": "936619743392459",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except Exception as exc:  # noqa: BLE001
        print(f"  instagram unavailable ({exc}) - keeping yesterday's", file=sys.stderr)
        return None

    user = ((data.get("data") or {}).get("user")) or {}
    followers = ((user.get("edge_followed_by") or {}).get("count")) or 0
    if not followers:
        return None
    return {
        "handle": handle,
        "followers": followers,
        "following": ((user.get("edge_follow") or {}).get("count")) or 0,
        "postCount": ((user.get("edge_owner_to_timeline_media") or {}).get("count")) or 0,
        "bio": (user.get("biography") or "").strip(),
        "stale": False,
    }


# ─────────────────────────────────────────────────────────────────────────────
# rollups
# ─────────────────────────────────────────────────────────────────────────────


def tally(posts: list[dict], field: str, label_field: str) -> list[dict]:
    counts: dict[str, dict] = {}
    for p in posts:
        key = p.get(field) or ""
        if not key or key in ("other", "elsewhere"):
            continue
        row = counts.setdefault(key, {"key": key, "label": p.get(label_field) or key, "n": 0})
        row["n"] += 1
    return sorted(counts.values(), key=lambda r: (-r["n"], r["label"]))


def previous() -> dict:
    path = DATA / "site.js"
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def check(new: dict, old: dict) -> list[str]:
    """Reasons to throw this run away. Empty list means it is safe to write."""
    bad: list[str] = []
    posts = new.get("posts") or []
    if len(posts) < 20:
        bad.append(f"only {len(posts)} posts came back")
    if not any(p.get("img") for p in posts):
        bad.append("not one post came back with a photo")
    if not new.get("michelin"):
        bad.append("the Michelin list came back empty")

    was = len(old.get("posts") or [])
    if was and len(posts) < was * SHRINK_LIMIT:
        bad.append(f"post count fell from {was} to {len(posts)}")
    return bad


def write(payload: dict) -> None:
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    (DATA / "site.js").write_text(
        "// Generated by scripts/update.py - do not edit by hand.\n"
        "// Source: ijustwanttoeat.com, read as JSON. Everything here is his.\n"
        f"window.SITE_DATA = {body};\n",
        encoding="utf-8",
    )

    hist_path = DATA / "history.json"
    history = []
    if hist_path.exists():
        try:
            history = json.loads(hist_path.read_text())
        except json.JSONDecodeError:
            history = []
    today = dt.date.today().isoformat()
    snap = {
        "date": today,
        "posts": payload["totals"]["posts"],
        "igFollowers": (payload.get("instagram") or {}).get("followers", 0),
    }
    history = [h for h in history if h.get("date") != today] + [snap]
    hist_path.write_text(json.dumps(history[-400:], indent=1) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)
    old = previous()

    print("reading the archive...", file=sys.stderr)
    posts = scrape_posts()

    print("reading the index pages...", file=sys.stderr)
    michelin = page_links("michelin-stars", "/post/")
    recipes = [r for r in page_links("recipe", "/post/") if fold(r["n"]) not in RECIPE_SKIP]
    podcasts = scrape_collection("podcasts", 20, verify=True)
    picks = scrape_collection("pick-of-the-month", 12, verify=True)

    reviews = [p for p in posts if p["kind"] == "review"]
    dates = [p["d"] for p in posts if p["d"]]
    areas = tally(posts, "area", "areaLabel")
    cuisines = tally(reviews, "cuisine", "cuisineLabel")
    hoods = sorted({p["hood"] for p in posts if p["hood"]})

    payload = {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "profile": {
            "name": "Jean-Philippe Gerbi",
            "brand": "I Just Want To Eat",
            "handle": "ijustwant2eat",
            "site": SITE,
            "since": 2011,
            "home": "New York & New Jersey",
            "links": {
                "instagram": "https://www.instagram.com/ijustwant2eat/",
                "facebook": "https://www.facebook.com/ijustwanttoeat",
                "x": "https://twitter.com/ijustwanttoeat",
                "threads": "https://www.threads.net/@ijustwant2eat",
                "map": "https://goo.gl/maps/1RotT1V7z1w",
                "podcast": f"{SITE}/podcasts",
                "contact": f"{SITE}/contact",
            },
        },
        "instagram": old.get("instagram"),
        "totals": {
            "posts": len(posts),
            "reviews": len(reviews),
            "archive": 0,  # filled below from the live collection count
            "recipes": len(recipes),
            "michelin": len(michelin),
            "podcasts": len(podcasts),
            "picks": len(picks),
            "areas": len(areas),
            "hoods": len(hoods),
            "years": dt.date.today().year - 2011,
            "oldest": min(dates) if dates else 0,
            "newest": max(dates) if dates else 0,
        },
        "areas": areas,
        "cuisines": cuisines,
        "hoods": hoods,
        "posts": posts,
        "michelin": michelin,
        "recipes": recipes,
        "podcasts": podcasts,
        "picks": picks,
    }

    # The true lifetime count, straight from the collection header, so the site
    # can say "2,344 posts" while only shipping the few hundred it renders.
    try:
        payload["totals"]["archive"] = int(
            (sq("post").get("collection") or {}).get("itemCount") or 0
        )
    except Exception:  # noqa: BLE001
        payload["totals"]["archive"] = len(posts)

    handle = os.environ.get("IG_HANDLE", "").strip()
    if handle:
        fresh = scrape_instagram(handle)
        if fresh:
            payload["instagram"] = fresh
        elif payload.get("instagram"):
            payload["instagram"] = {**payload["instagram"], "stale": True}

    problems = check(payload, old)
    if problems:
        print("REJECTED - keeping the previous data:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1

    t = payload["totals"]
    print(
        f"{t['posts']} posts rendered of {t['archive']} lifetime | "
        f"{t['reviews']} reviews | {t['michelin']} starred | {t['recipes']} recipes | "
        f"{t['podcasts']} episodes | {t['areas']} areas",
        file=sys.stderr,
    )

    if args.dry_run:
        was = len(old.get("posts") or [])
        print(f"dry run: posts {was} -> {t['posts']} (nothing written)", file=sys.stderr)
        return 0

    write(payload)
    print(f"wrote {DATA / 'site.js'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
