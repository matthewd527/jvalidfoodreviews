# JVALID FOOD REVIEWS — fan site

A one-page, heavily animated site for [@jvalidfoodreviews](https://www.tiktok.com/@jvalidfoodreviews),
which **refreshes its own numbers once a day** with no human involvement.

## Run it locally

Double-click `index.html`, or serve it:

```bash
python3 -m http.server 8777
```

## Layout

```
index.html            markup (numbers are placeholders, filled at runtime)
css/style.css         styling + animation
js/main.js            reads window.SITE_DATA and renders everything
data/site.js            ← SCRAPED DATA. Regenerated daily. Do not hand-edit.
data/ratings.js         ← RESEARCHED DATA. Imported from the spreadsheet.
data/history.json       one dated snapshot per day, for growth over time
data/overrides.json     optional: pin a video's category by hand (see below)
assets/                 avatar + one committed thumbnail per video
scripts/update.py       the daily updater
scripts/import_ratings.py  spreadsheet → data/ratings.js
.github/workflows/      the daily job
```

The two data files are separate on purpose: one is rewritten by a robot every
morning, the other is hand-researched and must survive that.

Data is a plain `window.SITE_DATA = {...}` assignment rather than JSON fetched at
runtime, specifically so the page still works when opened straight off the disk.
A `fetch()` would hit CORS on `file://`.

## How the refresh works

One request to `https://www.tiktok.com/embed/@jvalidfoodreviews` returns
everything: follower count, total likes, and the 10 newest videos with captions
and play counts. No API key, no OAuth, no login, nothing that expires. A second
best-effort request to the profile page picks up his true total video count.

Each run:

1. Fetches and parses the embed payload.
2. **Validates before trusting it** — see below.
3. Merges into the existing data, keeping videos that have scrolled out of the
   10-item window so the archive only grows.
4. Categorises any new video from its caption.
5. Downloads thumbnails for new videos only.
6. Writes `data/site.js`, appends to `data/history.json`, commits, pushes.
7. GitHub Pages redeploys.

### It cannot corrupt the site

This is the important part of an unattended job. A run is **rejected outright**,
leaving the previous data untouched and exiting non-zero, if:

- the follower or like count comes back as 0
- the video list is empty, or every video reports 0 views
- followers or likes fell by more than 50% since yesterday

Per-video view counts are also clamped so they can only ever move up — a
transient bad read can't erase a real number. Videos whose thumbnail failed to
download are held back rather than shipped as a hole in the grid.

Tested by pointing it at a dead handle and by feeding it faked payloads:
`data/site.js` came back byte-identical every time.

### Categorising

Hashtags are the primary signal, since he tags nearly every post. An explicit
`#burger` wins outright. Failing that, the food word that appears **earliest** in
the caption wins — that's what separates "smash burger and a milkshake" (burger)
from "milkshake, then a burger" (dessert). Nothing matches → `misc`.

Counties are extracted separately and are multi-valued, since one post is tagged
both `#orangecounty` and `#rocklandcounty`.

Scores 13/13 on a spot-check set including tricky overlaps.

To override a call, create `data/overrides.json` — it is read but never written,
so your pins survive every future run:

```json
{
  "7673101535743577375": { "cat": "pizza", "label": "Pizza", "counties": ["bergen"] }
}
```

## The ranking

`THE RANKING` orders every place he has given a number to, best to worst, with
the item-by-item breakdown behind each row.

It has two sources, merged on the page:

- **Curated** (`data/ratings.js`) — imported from the research spreadsheet with
  `python3 scripts/import_ratings.py <sheet.xlsx>`. The job never touches it,
  and it always wins for a video it covers.
- **Automatic** (`data/ratings_auto.js`) — for every video the spreadsheet
  doesn't cover, the job fetches the video page once, reads TikTok's place tag
  (restaurant name + address) and the auto-generated transcript, and extracts
  the scores he says out loud ("4.8 stars", "I'm gonna give them 4.9"). A score
  aimed at the bathroom or the nightlife is ignored — the LongHorn video rates
  a toilet, not the food. These rows wear an **AUTO** badge.

So new uploads rank themselves within a few hours of being posted, with no
human involved. Accuracy, measured against the hand-curated spreadsheet: all
ten scoreable videos land within 0.01 of the curated average. When ASR fails
or he never says a number, the video is listed under "not in the ranking"
rather than guessed at. A transcript that isn't ready yet (common right after
posting) is retried on later runs, up to five times.

To correct an auto entry, add its video id to `data/overrides.json`:

```json
{ "7673829157733666079": { "name": "Zio's Pizzeria", "score": 4.8 } }
```

A few decisions baked in:

- **Off-scale scores are kept as stated.** Little Caesars at `0.0` and Little
  Blue Menu at `−5.0` are flagged `OFF SCALE` rather than clamped into 1–5,
  because the joke is the point. Bars bottom out at zero so a negative can't
  invert them.
- **Ties share a rank** and the next rank skips, so three places at 4.5 are all
  `#7` and the next is `#10`.
- **Videos with no number are excluded and explained**, not silently dropped —
  LongHorn Steakhouse is missing because he only rated the bathroom.
- Every caveat from the spreadsheet's `Method & Gaps` sheet is surfaced in the
  expanded row, so unresolved item names and branches stay visible instead of
  looking like facts.

## Adding Instagram

Instagram support is written and off by default. Set `IG_HANDLE` to switch it on:

```bash
IG_HANDLE=hishandle python3 scripts/update.py --dry-run
```

**Read this before relying on it.** Unlike TikTok, there is no dependable free
and hands-off route:

- The anonymous endpoint the site uses (`/api/v1/users/web_profile_info/`) works
  with no token and nothing that expires — but it is metered hard per IP. In
  testing it returned `200` twice from CI, then `429` from every subsequent
  runner, and `401` from a home connection for 40+ minutes after a burst of
  requests. **Expect it to fail on plenty of days.**
- The code treats that as normal: on a 401/429 it keeps yesterday's Instagram
  numbers, flags them `stale`, and retries tomorrow from a different IP. TikTok
  is unaffected either way — the two run independently.
- It is also against Meta's terms of service, which is worth deciding on
  knowingly rather than by accident.
- Instagram publishes no lifetime-likes figure, so `likesTracked` is a sum over
  only the ~12 posts the endpoint returns. Label it as such; it is not
  comparable to TikTok's total.

The dependable alternative is Meta's official API, which needs his account to be
a Business/Creator account and a one-time OAuth grant **from him**. Its long-lived
token lasts 60 days and auto-refreshes, but if the refresh ever fails for 60
straight days the token dies for good and only he can restore it.

## Updating it by hand

You shouldn't need to, but:

```bash
python3 scripts/update.py --dry-run   # show what would change
python3 scripts/update.py             # do it
```

## Maintenance, honestly

Nothing here expires — no token, no card, no annual renewal. But TikTok changes
the shape of that embed payload a few times a year without warning. When it does,
the job fails loudly (red X, failure email) rather than writing garbage, and the
fix is usually a small path correction in `scrape_tiktok()`.

Budget one or two of those a year. Everything else runs itself.
