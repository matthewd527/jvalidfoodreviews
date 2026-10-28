# JVALID FOOD REVIEWS

**Live at [jvalidfoodreviews.com](https://jvalidfoodreviews.com)** — hosted on
Cloudflare Pages, which redeploys automatically on every push to this repo,
including the data refreshes GitHub Actions commits every three hours.

A one-page, heavily animated site for [@jvalidfoodreviews](https://www.tiktok.com/@jvalidfoodreviews),
which **refreshes its own numbers every three hours** with no human involvement.

## Caching (two settings, one in the repo and one not)

The site's whole promise is that it updates itself, so nothing may be cached
long enough to hide fresh data. Two things control that:

1. **`_headers`** (in this repo) tells Cloudflare Pages to serve `css/`, `js/`
   and `data/` with `max-age=0, must-revalidate` — the browser keeps the file
   and revalidates on each load, getting a small 304 when nothing changed.
   `assets/` keeps a one-day cache since thumbnails are written once per video.
2. **Browser Cache TTL** in the Cloudflare *zone*
   (Caching → Configuration) must be **"Respect Existing Headers"**.

The second one is not in this repo and is easy to miss. Cloudflare defaults it
to **4 hours**, and the zone setting *overrides* whatever `_headers` says — so
with the default, `data/site.js` sat in visitors' browsers for four hours and
they read stale follower counts no matter how often the job ran. The giveaway
is `cache-control: max-age=14400` on the custom domain while
`jvalidfoodreviews.pages.dev` correctly reports `max-age=0`.

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
data/site.js            ← SCRAPED DATA. Regenerated every run. Do not hand-edit.
data/ratings.js         ← RESEARCHED DATA. Imported from the spreadsheet.
data/history.json       one dated snapshot per day, for growth over time
data/view_checks.json   when each video's view count was last re-read
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
follower count, total likes, and his newest ten-or-so videos with captions and
play counts. No API key, no OAuth, no login, nothing that expires. A second
best-effort request to the profile page picks up his true total video count.

Each run:

1. Fetches and parses the embed payload.
2. **Validates before trusting it** — see below.
3. Merges into the existing data, keeping videos that have scrolled out of the
   embed's window so the archive only grows.
4. Categorises any new video from its caption, and re-tags the whole archive
   the same way, so a fix to the rules reaches old videos too.
5. Downloads thumbnails for new videos only.
6. **Re-reads ~20 older videos' view counts** — see below.
7. Reads each new video's page for its place tag and spoken scores.
8. Writes `data/site.js`, appends to `data/history.json`, commits, pushes.
9. Cloudflare Pages redeploys.

**Why every three hours:** by October 2026 he was posting about eight videos a
day, so the embed's window covers barely a day and a half. A video that scrolls
out of it between two good runs is never picked up. GitHub also quietly drops
about a quarter of scheduled runs, so the real gap is always longer than the
schedule says. Eight runs a day keeps even a bad stretch well inside the window,
and stays under Cloudflare's free 500 builds a month.

### Older videos keep their numbers current

The embed only carries the newest videos, so on its own every older video's
view count would freeze about a day into its life. Each run therefore re-reads
the ~20 most overdue videos from their own pages. A video falls due again once
its age has doubled since the last read, so a two-day-old video still climbing
is read daily while a two-month-old one waits weeks; nothing goes more than 60
days. A 429 from TikTok just ends the pass early; the rest wait for next run.

The same page says when a video has been **deleted** (`statusCode 10204`). Two
such reads in a row mark it `gone`: it leaves the grid, the counts and the
ranking's links, but stays in `data/site.js` so a wrong call can be undone.

### It cannot corrupt the site

This is the important part of an unattended job. A run is **rejected outright**,
leaving the previous data untouched, if:

- the follower or like count comes back as 0
- the video list is empty, or every video reports 0 views
- followers or likes fell by more than 50% since the last run

Per-video view counts are also clamped so they can only ever move up — a
transient bad read can't erase a real number. Videos whose thumbnail failed to
download are held back rather than shipped as a hole in the grid.

Tested by pointing it at a dead handle and by feeding it faked payloads:
`data/site.js` came back byte-identical every time.

### When it emails you

A rejected or failed run only goes red — which is what sends GitHub's failure
email — once the site has gone **18 hours** without a good run (about six
failures in a row). Before that it passes with a yellow warning on the run
page, because a single failure is almost always TikTok throttling one runner,
and the next run three hours later fixes it. So an email means it's really
broken, typically because TikTok changed the embed page.

Rate limits are handled rather than hammered: a 429 waits as long as TikTok's
`Retry-After` asks (or backs off 25s, then 50s, …), instead of retrying three
times in twenty seconds as it once did.

### Categorising

Hashtags are the primary signal, since he tags nearly every post. An explicit
`#burger` wins outright. Failing that, the food word that appears **earliest** in
the caption wins — that's what separates "smash burger and a milkshake" (burger)
from "milkshake, then a burger" (dessert). Nothing matches → `misc`.

Counties are extracted separately and are multi-valued, since one post is tagged
both `#orangecounty` and `#rocklandcounty`. Any `#somethingcounty` tag counts,
so new turf appears by itself. Misspellings he has used (`#dutchescounty`,
`#passiaccounty`, `#delewarecounty`) are folded into the real county by
`COUNTY_ALIASES` in `scripts/update.py`; add to it if a new one turns up.

Each county's state comes from the state he writes into the tag
(`#broomecountyny`), else a small table in the script, else the towns of the
videos tagged with it — so a county outside that table still gets labelled.

### Towns

Towns come from the venue's address in the TikTok place tag (or the curated
spreadsheet), never from guessing at hashtags. But he sometimes tags a chain's
generic page, which files the venue wherever that page says — a Sweet Frog in
Vestal came back as Lumberton, NC. So a town outside NY/NJ is only shown when
the video backs it up: the town or its state named in the caption (`#florida`),
a county tag in the same state, or another video that does. Unbacked ones are
listed in the run log as "left off as unbacked".

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

## The booking form

The **Book Jvalid** section posts to [Web3Forms](https://web3forms.com), chosen
because it needs no account, no dashboard and no server: submissions arrive as
plain emails, and the access key never expires. Free tier is 250/month, which is
far more than this will see.

**One-time setup — takes about a minute:**

1. Go to <https://web3forms.com> and put his email in the "Create your Access
   Key" box.
2. He gets an email with an access key (a UUID). Confirm it if prompted.
3. Open `index.html`, find `YOUR_WEB3FORMS_ACCESS_KEY`, and paste the key in
   its place.
4. Submit the form once yourself to confirm it lands in his inbox.

That's the whole setup. There's no account to maintain and nothing to renew.

Until the key is in place, the form refuses to send and says so on screen
rather than failing silently.

Notes:

- **The key is public on purpose.** It only permits submissions to the address
  it was issued to and can't read anything back, so it belongs in the HTML.
- A hidden honeypot field catches the bots that will inevitably find a public
  form; anything that fills it is dropped without a word.
- To change where mail goes, generate a new key against a different address and
  swap it — nothing else changes.

## Instagram

Instagram is stats-only — follower count, plus likes on the posts it lets us
see. Every video on the site comes from TikTok. It's on by default; set
`IG_HANDLE: ""` in the workflow to turn it off.

**It can't be refreshed automatically for free. This was tested, not assumed.**
Instagram turns datacenter networks away wholesale. On 2026-10-28, four GitHub
runners got `429` on all ten routes tried (the anonymous web API, the profile
page, and eight link-preview crawler user agents), and a Cloudflare Pages
Function got `401`s and login redirects. Only home connections get through.
So:

- Each run still tries once. It costs nothing, and it picks back up by itself
  if Instagram ever relents. On failure it keeps the last good numbers — they
  are never lost or zeroed — and TikTok is unaffected either way.
- Those numbers carry the time they were read (`fetchedAt`). Once they're more
  than three days old, the Instagram tile says "as of <date>" instead of
  passing them off as live.

**To refresh by hand**, from a home connection: `git pull`, then run
`python3 scripts/update.py`, then commit and push `data` and `assets`. If
Instagram refuses that too (`401`), save the response from a browser instead:
on instagram.com, run this in the developer console, which downloads `ig.json`:

```js
fetch('/api/v1/users/web_profile_info/?username=jvalidfoodreviews', {headers: {'x-ig-app-id': '936619743392459'}})
  .then(r => r.text()).then(t => Object.assign(document.createElement('a'),
    {href: URL.createObjectURL(new Blob([t])), download: 'ig.json'}).click())
```

and feed it to the updater:

```bash
IG_JSON=~/Downloads/ig.json python3 scripts/update.py
```

Notes:

- Reading Instagram this way is against Meta's terms of service, which is worth
  deciding on knowingly rather than by accident.
- Instagram publishes no lifetime-likes figure, so `likesTracked` is a sum over
  the posts we've seen (each read shows the ~12 newest). It is not comparable
  to TikTok's total.
- **For exact numbers that update themselves**, the only route is Meta's
  official Graph API ("Business Discovery"), which does answer servers. It needs
  an Instagram Business/Creator account linked to a Facebook Page, a Meta
  developer app, and a Page access token stored as a GitHub secret. A Page token
  made from a long-lived user token doesn't expire on a timer, so it's set up
  once — but it takes someone's Meta login, so it isn't wired in.

## Updating it by hand

You shouldn't need to, but:

```bash
python3 scripts/update.py --dry-run   # show what would change
python3 scripts/update.py             # do it
```

If videos ever go missing — say the job was off for days and they scrolled out
of the embed's window — `scripts/backfill.py` fetches them by id. Open his
profile in a browser (it lists video links even logged out), collect the ids
from the `/video/<id>` links, and pass the ones the site lacks:

```bash
python3 scripts/backfill.py 7675927453059108127 7675928047912029470
```

That is how the 48 videos from Aug 19–23, which predate the updater, were
recovered on 2026-10-28.

## Maintenance, honestly

Nothing in the pipeline expires — no token, no API key. The one renewal is the
**domain**: jvalidfoodreviews.com is registered at Porkbun until 2027-08-29 and
needs auto-renew on there (or a manual renewal) to keep the address. If it ever
lapses, the site itself stays up at <https://jvalidfoodreviews.pages.dev>.

TikTok changes the shape of that embed payload a few times a year without
warning. When it does,
the job keeps the old data rather than writing garbage, and once that has lasted
18 hours it fails loudly (red X, failure email). The fix is usually a small path
correction in `scrape_tiktok()`.

Budget one or two of those a year. Everything else runs itself — except the
Instagram numbers, which only move when someone refreshes them by hand (above).

The schedule itself can't quietly die after the handoff: GitHub switches off a
public repo's scheduled workflows after 60 days without activity, but every run
commits (data, or a heartbeat file when nothing changed), and those commits
count.
