#!/usr/bin/env python3
"""
Refresh the site's data from TikTok (and optionally Instagram).

Writes:
  data/site.js      the payload the page reads (plain JS assignment, so it works
                    over file:// as well as http:// - no fetch/CORS problems)
  data/history.json one dated snapshot per run, for tracking growth over time

Design rule: this script must NEVER make the site worse. If the scrape looks
wrong (empty, zeroed, or an implausible collapse in followers) it keeps the last
known-good data, writes nothing, and exits non-zero so CI goes red.

Usage:
  python3 scripts/update.py             # normal run
  python3 scripts/update.py --dry-run   # show what would change, write nothing
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ASSETS = ROOT / "assets"

HANDLE = os.environ.get("TIKTOK_HANDLE", "jvalidfoodreviews")
EMBED_URL = f"https://www.tiktok.com/embed/@{HANDLE}"
OEMBED = "https://www.tiktok.com/oembed?url="

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

# ── categorisation ────────────────────────────────────────────────────────────
# Ordered by specificity: the first list to score highest wins. Dessert is
# checked ahead of the others because "ice cream cake" should not read as pizza.
CATEGORIES = [
    ("dessert", "Ice cream", [
        "icecream", "ice cream", "dessert", "gelato", "cone", "sundae",
        "milkshake", "shake", "custard", "donut", "doughnut", "cookie",
        "cake", "cheesecake", "brownie", "cannoli", "froyo", "sweets",
    ]),
    ("pizza", "Pizza", [
        "pizza", "pizzeria", "slice", "sicilian", "grandma pie", "calzone",
    ]),
    ("burger", "Burger", [
        "burger", "smashburger", "smash burger", "cheeseburger", "patty",
        "whopper", "bigmac", "big mac",
    ]),
]

COUNTIES = [
    ("bergen", "Bergen County", "NJ", ["bergencounty", "bergen"]),
    ("rockland", "Rockland County", "NY", ["rocklandcounty", "rockland"]),
    ("westchester", "Westchester", "NY", ["westchester"]),
    ("orange", "Orange County", "NY", ["orangecounty"]),
]


def created_from_id(video_id: str) -> int | None:
    """TikTok IDs are snowflake-ish: the top 32 bits are the unix timestamp."""
    try:
        ts = int(video_id) >> 32
        # sanity-check it lands somewhere between 2016 and 2100
        return ts if 1451606400 < ts < 4102444800 else None
    except (ValueError, TypeError):
        return None


def categorise(caption: str) -> tuple[str, str]:
    """Return (cat_key, human_label) for a caption. Falls back to misc.

    Two signals, in order of trust:
      1. An explicit hashtag (#burger) - he tags almost every post, so this is
         near-decisive.
      2. Otherwise the keyword that appears EARLIEST in the caption, on the
         theory that the subject is named before the side dish. That is what
         separates "smash burger and a milkshake" (a burger review) from
         "milkshake and a side of fries" (a dessert review).

    Counting keyword hits instead would be wrong: "smash burger" also contains
    "burger", and "milkshake" also contains "shake", so scores inflate purely on
    how the synonym lists happen to overlap.

    Word boundaries matter: "#pancakes" must not match "cake", and "nice" must
    not match "ice".
    """
    text = caption.lower()
    matches = []  # (hashtag_first, position, -length, key, label)

    for key, label, words in CATEGORIES:
        for w in words:
            # Hashtags: prefix match is safe and useful - #pizzareview counts
            # as pizza, because the "#" anchors the start of the word.
            tag = "#" + w.replace(" ", "")
            i = text.find(tag)
            if i >= 0:
                matches.append((0, i, -len(w), key, label))
            # Free text: whole words only - "#pancakes" must not hit "cake",
            # and "nice" must not hit "ice".
            m = re.search(rf"\b{re.escape(w)}\b", text)
            if m:
                matches.append((1, m.start(), -len(w), key, label))

    if matches:
        matches.sort()
        return matches[0][3], matches[0][4]
    return "misc", "Off-menu"


def counties_for(caption: str) -> list[str]:
    """County keys for a caption.

    The seed list catches his usual bare tags (#rockland, #westchester). On top
    of that, any "#somethingcounty" hashtag becomes a county automatically, so
    the turf section grows by itself when he starts reviewing somewhere new -
    no code change needed for #putnamcounty or #passaiccounty.
    """
    text = caption.lower()
    keys = [key for key, _, _, words in COUNTIES if any(w in text for w in words)]
    for m in re.finditer(r'#([a-z]+?)county\b', text):
        if m.group(1) not in keys:
            keys.append(m.group(1))
    return keys


# ── fetching ──────────────────────────────────────────────────────────────────
def get(url: str, tries: int = 4, timeout: int = 30) -> bytes:
    """GET with retries and jittered backoff. Raises on final failure."""
    last = None
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - want to retry on anything transient
            last = e
            if attempt < tries:
                nap = attempt * 3 + random.uniform(0, 2)
                print(f"    retry {attempt}/{tries - 1} after {nap:.1f}s ({type(e).__name__}: {e})")
                time.sleep(nap)
    raise RuntimeError(f"GET failed after {tries} tries: {url} ({last})")


def scrape_tiktok() -> dict:
    """One request gets profile stats AND the 10 most recent videos."""
    html = get(EMBED_URL).decode("utf-8", "ignore")

    m = re.search(
        r'id="__FRONTITY_CONNECT_STATE__"[^>]*>(.*?)</script>', html, re.S
    )
    if not m:
        raise RuntimeError(
            "embed page had no __FRONTITY_CONNECT_STATE__ blob - "
            "TikTok probably changed the page or served an anti-bot shell"
        )

    state = json.loads(m.group(1))

    # The payload is keyed by the handle under source.data; find it defensively
    # rather than hard-coding the path, since that path has changed before.
    user_info, video_list = None, None

    def walk(node):
        nonlocal user_info, video_list
        if isinstance(node, dict):
            if user_info is None and "followerCount" in node and "heartCount" in node:
                user_info = node
            if video_list is None:
                v = node.get("videoList")
                if isinstance(v, list) and v and isinstance(v[0], dict) and "id" in v[0]:
                    video_list = v
            for val in node.values():
                walk(val)
        elif isinstance(node, list):
            for val in node:
                walk(val)

    walk(state)

    if not user_info:
        raise RuntimeError("no userInfo (followerCount/heartCount) in embed state")
    if not video_list:
        raise RuntimeError("no videoList in embed state")

    videos = []
    for v in video_list:
        vid = str(v.get("id", "")).strip()
        if not vid:
            continue
        cap = (v.get("desc") or "").strip()
        # playCount sits directly on the video object here; older shapes of this
        # payload nested it under .stats, so accept either.
        stats = v.get("stats") or {}
        views = v.get("playCount")
        if views is None:
            views = stats.get("playCount")
        videos.append({
            "id": vid,
            "cap": cap,
            "views": int(views or 0),
            "created": v.get("createTime") or created_from_id(vid),
            # the embed payload ships cover URLs, so no extra oEmbed round-trip
            "cover": v.get("coverUrl") or v.get("originCoverUrl"),
        })

    return {
        "followers": int(user_info.get("followerCount") or 0),
        "likes": int(user_info.get("heartCount") or 0),
        "following": int(user_info.get("followingCount") or 0),
        "nickname": (user_info.get("nickname") or "").strip() or "Jvalidfoodreviews",
        "bio": (user_info.get("signature") or "").strip(),
        "videos": videos,
        "total_videos": scrape_total_videos(),
    }


def scrape_total_videos() -> int | None:
    """His true video count (the embed feed only exposes the newest 10).

    Best-effort only: this is a second request against a page that is more
    aggressively bot-protected than /embed/, so a failure here must never fail
    the run - the caller falls back to the number of videos we know about.
    """
    try:
        html = get(f"https://www.tiktok.com/@{HANDLE}", tries=2, timeout=25).decode("utf-8", "ignore")
        m = re.search(
            r'id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S
        )
        if not m:
            return None
        scope = json.loads(m.group(1)).get("__DEFAULT_SCOPE__", {})
        stats = (scope.get("webapp.user-detail", {}).get("userInfo", {}) or {}).get("stats", {})
        n = int(stats.get("videoCount") or 0)
        return n if n > 0 else None
    except Exception as e:  # noqa: BLE001
        print(f"  (couldn't read total video count: {e})")
        return None


# ── spoken-score extraction ───────────────────────────────────────────────────
# For each NEW video the job fetches the video page once, reads the place tag
# (poi) and the auto-generated transcript, and pulls out the scores he says on
# camera. Validated against the hand-curated spreadsheet: on all ten currently
# scoreable videos the extracted average landed within 0.01 of the curated
# average. Curated data still always wins - see merge in ratings_auto.js.

NOT_FOOD = re.compile(
    r'bathroom|restroom|toilet|nightlife|night life|vibe|music|atmosphere|'
    r'service|staff|decor|parking|view\b|interior', re.I)

WORD_NUM = {'zero': 0, 'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5}

STAR_PAT = re.compile(
    r'(-?\d+(?:\.\d+)?)\s*(?:stars?\b|out of\s*(?:5|five)\b)', re.I)
# he often drops the word "stars": "I'm gonna give them 4.9", "I'm at 4"
VERB_PAT = re.compile(
    r"(?:i'?m\s+(?:going|at|giving)|(?:gonna\s+)?(?:give|giving)\s+(?:it|them|him|her|this|that)?)\s*a?\s*"
    r"(-?\d+(?:\.\d+)?)\b(?!\s*(?:dollars|bucks|%|percent|minutes|miles))", re.I)

FOOD_WORDS = [
    'burger', 'wings', 'pizza', 'slice', 'pretzel', 'milkshake', 'shake',
    'mac and cheese', 'fries', 'taco', 'nachos', 'sandwich', 'ice cream',
    'sundae', 'cone', 'french dip', 'chicken', 'pancakes', 'sliders', 'melt',
    'egg roll', 'bbq', 'brisket', 'quesadilla', 'burrito', 'hot dog', 'gelato',
]


def _norm_spoken(t: str) -> str:
    for w, n in WORD_NUM.items():
        t = re.sub(rf'\b{w}\s+and\s+a\s+half\b', f'{n}.5', t, flags=re.I)
        t = re.sub(rf'\b{w}\b(?=\s*(?:stars?|out of))', str(n), t, flags=re.I)
    return t


def extract_scores(text: str) -> list[tuple[float, str]]:
    """Return [(score, item_label)] for spoken food scores, in spoken order."""
    t = _norm_spoken(text)
    found = []
    for pat in (STAR_PAT, VERB_PAT):
        for m in pat.finditer(t):
            if t[max(0, m.start(1) - 1):m.start(1)] == '$':   # price, not rating
                continue
            val = float(m.group(1))
            if not (-5 <= val <= 5):
                continue
            ctx = t[max(0, m.start() - 90):m.end() + 30]
            # The score belongs to whatever he mentioned most recently before
            # saying the number: "the vibe is a 5 but the burger, 3 stars" is a
            # burger score, while "I give their bathroom 4 stars" is not food.
            before = t[max(0, m.start() - 90):m.start()].lower()
            nf = max((mm.end() for mm in NOT_FOOD.finditer(before)), default=-1)
            fd = max((before.rfind(w) + len(w) for w in FOOD_WORDS if w in before),
                     default=-1)
            if nf > fd:
                continue
            found.append((m.start(1), val, ctx))
    seen, out = set(), []
    for pos, val, ctx in sorted(found):
        if any(abs(pos - p) < 6 for p in seen):   # same number, both patterns
            continue
        seen.add(pos)
        # name the item from the nearest food word he mentioned before scoring
        low = ctx.lower()
        label = next((w.title() for w in FOOD_WORDS if w in low), None)
        out.append((val, label or "Spoken score"))
    return out


def fetch_video_details(video_id: str) -> dict:
    """Place tag + transcript scores for one video. Never raises.

    Returns {"status": "scored"|"no_scores"|"no_transcript"|"error", ...}.
    A brand-new upload often has no ASR transcript yet, so 'no_transcript'
    is retried on later runs.
    """
    try:
        url = f"https://www.tiktok.com/@{HANDLE}/video/{video_id}"
        html = get(url, tries=2, timeout=30).decode("utf-8", "ignore")
        m = re.search(
            r'id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S)
        if not m:
            return {"status": "error", "why": "no state blob"}
        item = (json.loads(m.group(1))
                .get("__DEFAULT_SCOPE__", {})
                .get("webapp.video-detail", {})
                .get("itemInfo", {}).get("itemStruct", {}))
        if not item:
            return {"status": "error", "why": "no itemStruct"}

        poi = item.get("poi") or {}
        out = {
            "name": (poi.get("name") or "").strip(),
            "address": (poi.get("address") or "").strip(),
        }

        subs = [s for s in ((item.get("video") or {}).get("subtitleInfos") or [])
                if str(s.get("LanguageCodeName", "")).startswith("eng") and s.get("Url")]
        if not subs:
            out["status"] = "no_transcript"
            return out

        vtt = get(subs[0]["Url"], tries=2).decode("utf-8", "ignore")
        lines, seen = [], set()
        for line in vtt.splitlines():
            line = line.strip()
            if not line or "-->" in line or line == "WEBVTT" or line in seen:
                continue
            seen.add(line)
            lines.append(line)
        text = " ".join(lines)

        scores = extract_scores(text)
        out["status"] = "scored" if scores else "no_scores"
        out["items"] = [{"item": lbl, "score": s} for s, lbl in scores]
        return out
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "why": f"{type(e).__name__}: {e}"}


def refresh_auto_ratings(new_ids: list[str], payload: dict) -> None:
    """Keep data/auto_ratings.json and data/ratings_auto.js up to date.

    Only new videos (and previous failures, up to 5 attempts) cost a request.
    Curated entries in data/ratings.js always take precedence on the page, so
    this can only ever ADD information, never fight the spreadsheet.
    """
    store_f = DATA / "auto_ratings.json"
    store = {}
    if store_f.exists():
        try:
            store = json.loads(store_f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            store = {}

    # figure out which ids are already covered by the curated ratings file
    curated_ids = set()
    cur_f = DATA / "ratings.js"
    if cur_f.exists():
        curated_ids = set(re.findall(r'"videoId":\s*"(\d+)"', cur_f.read_text(encoding="utf-8")))

    # Anything on the site that is neither curated nor successfully processed
    # needs a look - not just this run's brand-new ids. That way a video that
    # was missed once (or dropped from the curated file) self-heals on the next
    # run instead of falling through forever.
    todo = []
    for v in payload.get("videos", []):
        vid = v["id"]
        rec = store.get(vid, {})
        if vid in curated_ids or rec.get("status") in ("scored", "no_scores"):
            continue
        if rec and rec.get("status") in ("error", "no_transcript") and rec.get("attempts", 0) >= 5:
            continue   # gave up after five tries; overrides.json can still fill it in
        todo.append(vid)

    for i, vid in enumerate(todo):
        if i:
            time.sleep(2 + random.uniform(0, 2))   # politeness between page loads
        print(f"  → reading video page for {vid}")
        det = fetch_video_details(vid)
        det["attempts"] = store.get(vid, {}).get("attempts", 0) + 1
        store[vid] = det
        n = len(det.get("items", []))
        print(f"    {det['status']}"
              + (f", {n} spoken score(s)" if n else "")
              + (f" @ {det['name']}" if det.get("name") else ""))

    if todo:
        store_f.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")

    # regenerate the page-facing file every run (cheap, and keeps it in sync
    # with overrides and with videos leaving/entering the curated set)
    overrides = {}
    ov = DATA / "overrides.json"
    if ov.exists():
        try:
            overrides = json.loads(ov.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    by_id = {v["id"]: v for v in payload.get("videos", [])}
    entries, unscored = [], []
    for vid, rec in store.items():
        if vid in curated_ids or vid not in by_id:
            continue
        pin = overrides.get(vid, {})
        v = by_id[vid]
        name = pin.get("name") or rec.get("name")
        county = (v.get("counties") or [None])[0]
        if not name:
            # no place tag: an honest generic name beats a wrong guess
            name = f"Untagged {v.get('label', 'spot').lower()} spot"
        items = rec.get("items") or []
        if pin.get("score") is not None:
            items = [{"item": "Pinned by hand", "score": pin["score"]}]
        if items:
            score = round(sum(i["score"] for i in items) / len(items), 3)
            entries.append({
                "n": None, "name": name,
                "place": pin.get("place") or rec.get("address", "").split(",")[0] or (county or "").title(),
                "address": rec.get("address", ""),
                "score": score,
                "tier": ("offscale" if (score > 5 or score < 1) else
                         "elite" if score >= 4.7 else "great" if score >= 4 else
                         "fine" if score >= 3 else "rough"),
                "overall": None,
                "items": sorted(items, key=lambda i: -i["score"]),
                "posted": None, "videoId": vid,
                "caveats": ["Scored automatically from the video's own transcript."],
                "verified": "auto", "auto": True,
            })
        elif rec["status"] in ("no_scores", "no_transcript"):
            unscored.append({
                "name": name, "videoId": vid,
                "why": ("no numerical food score spoken on camera"
                        if rec["status"] == "no_scores"
                        else "transcript not available yet - will keep trying"),
            })

    (DATA / "ratings_auto.js").write_text(
        "// Generated by scripts/update.py from video transcripts - do not edit.\n"
        "// Curated data in ratings.js always wins for the same video.\n"
        "window.RATINGS_AUTO = " + json.dumps(
            {"entries": entries, "unscored": unscored}, indent=2) + ";\n",
        encoding="utf-8",
    )
    if entries or unscored:
        print(f"  auto ratings: {len(entries)} scored, {len(unscored)} unscored")


# ── instagram ─────────────────────────────────────────────────────────────────
# Stats only - videos come exclusively from TikTok, so nothing here ever adds
# to the video grid. Uses the same anonymous web endpoint the instagram.com
# profile page calls: no token, no app, no login, nothing to expire. It IS
# rate-limited per IP and fails on some days; the merge below keeps the last
# good numbers and flags them stale rather than ever losing them.
# Set IG_HANDLE="" to disable.
IG_HANDLE = os.environ.get("IG_HANDLE", "jvalidfoodreviews").lstrip("@").strip()
IG_APP_ID = "936619743392459"


def scrape_instagram() -> dict | None:
    """Follower count and the ~12 most recent posts. None if unavailable.

    Never raises: Instagram going quiet must not take the TikTok half of the
    run down with it.
    """
    if not IG_HANDLE:
        return None

    url = (
        "https://www.instagram.com/api/v1/users/web_profile_info/"
        f"?username={urllib.parse.quote(IG_HANDLE)}"
    )
    req = urllib.request.Request(url, headers={**HEADERS, "x-ig-app-id": IG_APP_ID})
    try:
        # Deliberately no retry loop. This endpoint rate-limits by IP and
        # answers a burst with a 401 lockout lasting 30+ minutes, so one polite
        # request a day is the whole strategy.
        with urllib.request.urlopen(req, timeout=25) as r:
            payload = json.loads(r.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 429):
            # Expected and common. Instagram meters this endpoint hard per IP,
            # and CI runners share a pool that other people are also hitting,
            # so some runs simply will not get through. Yesterday's numbers stay
            # on the site and we try again tomorrow from a different IP.
            print(f"  instagram: rate-limited ({e.code}) - keeping last known "
                  "numbers, will retry tomorrow")
        else:
            print(f"  instagram: HTTP {e.code} - skipping this run")
        return None
    except Exception as e:  # noqa: BLE001
        print(f"  instagram: unavailable ({type(e).__name__}) - skipping this run")
        return None

    user = (payload.get("data") or {}).get("user")
    if not user:
        print("  instagram: response had no user object - skipping")
        return None

    media = user.get("edge_owner_to_timeline_media") or {}
    posts = []
    for edge in media.get("edges", []):
        n = edge.get("node") or {}
        cap_edges = (n.get("edge_media_to_caption") or {}).get("edges") or []
        caption = (cap_edges[0]["node"]["text"] if cap_edges else "").strip()
        posts.append({
            "id": n.get("shortcode") or n.get("id"),
            "cap": caption,
            "likes": int((n.get("edge_liked_by") or {}).get("count") or 0),
            "views": int(n.get("video_view_count") or 0),
            "created": n.get("taken_at_timestamp"),
        })

    followers = int((user.get("edge_followed_by") or {}).get("count") or 0)
    if followers <= 0:
        print("  instagram: follower count came back 0 - ignoring this run")
        return None

    return {
        "handle": IG_HANDLE,
        "followers": followers,
        "following": int((user.get("edge_follow") or {}).get("count") or 0),
        "postCount": int(media.get("count") or 0),
        # Instagram exposes no lifetime-likes metric, so this is a sum over the
        # posts we can actually see. Labelled honestly on the page.
        "likesTracked": sum(p["likes"] for p in posts),
        "postsTracked": len(posts),
        "posts": posts,
    }


def merge_instagram(fresh_ig: dict | None, prev_ig: dict | None) -> dict | None:
    """Keep the last good Instagram block if today's fetch was skipped, and
    archive every post ever seen.

    The endpoint only exposes the ~12 newest posts, so like TikTok videos,
    posts are accumulated: once seen, a post and its like count stay forever
    (likes only ever move up). likesTracked is the sum over that whole archive,
    which is what feeds the site's combined Total Likes counter.
    """
    if fresh_ig is None:
        if prev_ig:
            print("  instagram: keeping yesterday's numbers")
            out = dict(prev_ig)
            out["stale"] = True
            return out
        return None

    # Guard against a sudden collapse the same way TikTok is guarded.
    if prev_ig:
        before = prev_ig.get("followers") or 0
        if before > 100 and fresh_ig["followers"] < before * 0.5:
            print(f"  instagram: followers fell {before} → {fresh_ig['followers']}, "
                  "looks wrong - keeping previous")
            out = dict(prev_ig)
            out["stale"] = True
            return out

    archive = {p["id"]: p for p in (prev_ig or {}).get("posts", []) if p.get("id")}
    for p in fresh_ig["posts"]:
        old = archive.get(p["id"], {})
        p["likes"] = max(p["likes"], old.get("likes", 0))
        p["views"] = max(p["views"], old.get("views", 0))
        archive[p["id"]] = p

    posts = sorted(archive.values(), key=lambda p: p.get("created") or 0, reverse=True)
    fresh_ig["posts"] = posts
    fresh_ig["likesTracked"] = sum(p["likes"] for p in posts)
    fresh_ig["postsTracked"] = len(posts)
    fresh_ig["stale"] = False
    return fresh_ig


def fetch_thumb(video_id: str, cover_url: str | None = None) -> bool:
    """Download a video's cover image. Returns True if a file now exists.

    TikTok's CDN URLs are signed and expire in ~24h, which is exactly why the
    bytes get committed to the repo - once a thumbnail is on disk it never
    expires, so only genuinely new videos need this.

    Prefers the coverUrl already present in the embed payload; falls back to the
    documented oEmbed endpoint if that is missing or fails.
    """
    dest = ASSETS / f"thumb-{video_id}.jpg"
    if dest.exists() and dest.stat().st_size > 2000:
        return True

    candidates = [c for c in (cover_url,) if c]
    try:
        url = f"{OEMBED}{urllib.parse.quote(f'https://www.tiktok.com/@{HANDLE}/video/{video_id}', safe='')}"
        meta = json.loads(get(url, tries=2).decode("utf-8", "ignore"))
        if meta.get("thumbnail_url"):
            candidates.append(meta["thumbnail_url"])
    except Exception as e:  # noqa: BLE001
        print(f"    oEmbed lookup failed for {video_id}: {e}")

    for src in candidates:
        try:
            blob = get(src, tries=2)
        except Exception:  # noqa: BLE001
            continue
        if len(blob) < 2000:  # a few hundred bytes means an error page
            continue
        dest.write_bytes(blob)
        print(f"    saved {dest.name} ({len(blob) // 1024}KB)")
        return True

    print(f"    could not fetch a thumbnail for {video_id}")
    return False


# ── merge + validate ──────────────────────────────────────────────────────────
def load_previous() -> dict:
    f = DATA / "site.js"
    if not f.exists():
        return {}
    txt = f.read_text(encoding="utf-8")
    m = re.search(r"window\.SITE_DATA\s*=\s*(\{.*\});?\s*$", txt, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def validate(fresh: dict, prev: dict) -> list[str]:
    """Return a list of reasons the scrape looks untrustworthy. Empty = good."""
    problems = []

    if fresh["followers"] <= 0:
        problems.append(f"follower count is {fresh['followers']}")
    if fresh["likes"] <= 0:
        problems.append(f"like count is {fresh['likes']}")
    if not fresh["videos"]:
        problems.append("zero videos returned")
    if all(v["views"] == 0 for v in fresh["videos"]):
        problems.append("every video reported 0 views")

    old = (prev.get("profile") or {})
    for key in ("followers", "likes"):
        before = old.get(key) or 0
        after = fresh[key]
        # Accounts do lose followers, but a >50% collapse overnight on a small
        # account means the scrape broke, not that something happened.
        if before > 20 and after < before * 0.5:
            problems.append(f"{key} fell from {before} to {after} (>50% drop)")

    return problems


def merge(fresh: dict, prev: dict, overrides: dict) -> dict:
    """Fold the scrape into the existing data, preserving anything human-set."""
    prev_videos = {v["id"]: v for v in (prev.get("videos") or [])}
    merged, new_ids = [], []

    for v in fresh["videos"]:
        old = prev_videos.get(v["id"], {})
        if not old:
            new_ids.append(v["id"])

        pin = overrides.get(v["id"], {})
        cat, label = categorise(v["cap"])

        merged.append({
            "id": v["id"],
            "cap": v["cap"] or old.get("cap", ""),
            # views only ever move forward; a transient 0 must not erase a real number
            "views": max(v["views"], old.get("views", 0)),
            "cat": pin.get("cat") or cat,
            "label": pin.get("label") or label,
            "counties": pin.get("counties") or counties_for(v["cap"]),
            "created": v.get("created") or old.get("created"),
        })

    # Keep videos we've seen before that have scrolled out of the 10-item embed
    # window, so the archive on the site only ever grows.
    seen = {v["id"] for v in merged}
    for vid, old in prev_videos.items():
        if vid not in seen:
            merged.append(old)

    merged.sort(key=lambda v: int(v["id"]), reverse=True)

    biggest = max(merged, key=lambda v: v["views"])["id"] if merged else None
    for v in merged:
        v["hot"] = (v["id"] == biggest)

    return {
        "updated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "profile": {
            "handle": HANDLE,
            "nickname": fresh["nickname"],
            "bio": fresh["bio"] or (prev.get("profile") or {}).get("bio", ""),
            "followers": fresh["followers"],
            "likes": fresh["likes"],
            "following": fresh["following"],
            "videoCount": (
                fresh.get("total_videos")
                or max(len(merged), (prev.get("profile") or {}).get("videoCount", 0))
            ),
        },
        "instagram": merge_instagram(fresh.get("instagram"), prev.get("instagram")),
        "videos": merged,
    }, new_ids


def write_history(payload: dict) -> None:
    f = DATA / "history.json"
    hist = []
    if f.exists():
        try:
            hist = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            hist = []

    today = dt.date.today().isoformat()
    snap = {
        "date": today,
        "followers": payload["profile"]["followers"],
        "likes": payload["profile"]["likes"],
        "videos": len(payload["videos"]),
        "views": sum(v["views"] for v in payload["videos"]),
    }
    if payload.get("instagram"):
        snap["ig_followers"] = payload["instagram"].get("followers")

    hist = [h for h in hist if h.get("date") != today]  # one row per day
    hist.append(snap)
    hist.sort(key=lambda h: h["date"])
    f.write_text(json.dumps(hist, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="report changes, write nothing")
    args = ap.parse_args()

    DATA.mkdir(exist_ok=True)
    ASSETS.mkdir(exist_ok=True)

    prev = load_previous()
    overrides = {}
    ov = DATA / "overrides.json"
    if ov.exists():
        try:
            overrides = json.loads(ov.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print("! overrides.json is not valid JSON - ignoring it")

    print(f"→ fetching {EMBED_URL}")
    try:
        fresh = scrape_tiktok()
    except Exception as e:  # noqa: BLE001 - a clean message beats a traceback in CI
        print(f"\n✗ could not read TikTok: {e}", file=sys.stderr)
        print("  The site still has its last good data; nothing was overwritten.",
              file=sys.stderr)
        print("  If this repeats for days, TikTok likely changed the embed page "
              "and scripts/update.py needs a fix.", file=sys.stderr)
        return 1

    print(f"  got {fresh['followers']} followers, {fresh['likes']} likes, "
          f"{len(fresh['videos'])} videos in the feed")

    # Instagram is strictly optional and never fails the run.
    if IG_HANDLE:
        print(f"→ fetching instagram @{IG_HANDLE}")
        fresh["instagram"] = scrape_instagram()
        if fresh["instagram"]:
            ig = fresh["instagram"]
            print(f"  got {ig['followers']} followers, {ig['postsTracked']} "
                  f"of {ig['postCount']} posts visible")

    problems = validate(fresh, prev)
    if problems:
        print("\n✗ scrape failed validation - keeping existing data:", file=sys.stderr)
        for p in problems:
            print(f"    - {p}", file=sys.stderr)
        return 1

    payload, new_ids = merge(fresh, prev, overrides)

    old_p = prev.get("profile") or {}
    d_follow = payload["profile"]["followers"] - (old_p.get("followers") or 0)
    d_likes = payload["profile"]["likes"] - (old_p.get("likes") or 0)
    if prev:
        print(f"  followers {old_p.get('followers')} → {payload['profile']['followers']} ({d_follow:+d})")
        print(f"  likes     {old_p.get('likes')} → {payload['profile']['likes']} ({d_likes:+d})")

    if new_ids:
        print(f"\n★ {len(new_ids)} new video(s):")
        for vid in new_ids:
            v = next(x for x in payload["videos"] if x["id"] == vid)
            print(f"    {vid}  [{v['label']}]  {v['cap'][:60]!r}")
    else:
        print("  no new videos")

    if args.dry_run:
        print("\n(dry run - nothing written)")
        return 0

    covers = {v["id"]: v.get("cover") for v in fresh["videos"]}
    missing = [v["id"] for v in payload["videos"]
               if not (ASSETS / f"thumb-{v['id']}.jpg").exists()]
    if missing:
        print(f"\n→ fetching {len(missing)} thumbnail(s)")
        for vid in missing:
            fetch_thumb(vid, covers.get(vid))

    # Drop any video we could not get an image for, rather than shipping a hole
    # in the grid.
    keep = [v for v in payload["videos"]
            if (ASSETS / f"thumb-{v['id']}.jpg").exists()]
    dropped = len(payload["videos"]) - len(keep)
    if dropped:
        print(f"  holding back {dropped} video(s) with no thumbnail yet")
    payload["videos"] = keep

    (DATA / "site.js").write_text(
        "// Generated by scripts/update.py - do not edit by hand.\n"
        "// To pin a video's category, use data/overrides.json instead.\n"
        "window.SITE_DATA = " + json.dumps(payload, indent=2) + ";\n",
        encoding="utf-8",
    )
    write_history(payload)
    refresh_auto_ratings(new_ids, payload)

    print(f"\n✓ wrote data/site.js ({len(payload['videos'])} videos) and data/history.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
