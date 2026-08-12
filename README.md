# JVALID FOOD REVIEWS — fan site

A one-page, heavily animated site for [@jvalidfoodreviews](https://www.tiktok.com/@jvalidfoodreviews) on TikTok.

## Run it

Just double-click `index.html`, or serve it locally:

```bash
python3 -m http.server 8777
```

Then open http://localhost:8777

## What's here

```
index.html          all the markup
css/style.css       all the styling + animation
js/main.js          video data, counters, filters, lightbox, cursor
assets/             avatar + 10 video thumbnails (downloaded locally)
```

## Where the content came from

Everything on the page is real data pulled from the public TikTok profile:

| Thing | Value |
|---|---|
| Display name | Jvalidfoodreviews |
| Bio | "What's a food review without a little laughter" |
| Followers | 398 |
| Likes | 5,940 |
| Videos | 31 total (the 10 most recent are embedded) |
| Counties | Bergen (NJ), Rockland (NY), Westchester (NY), Orange (NY) |

The menu counts (3 burgers / 2 pizza / 2 ice cream / 3 off-menu) and the turf
counts are tallied straight from the real hashtags on those 10 captions.

**Thumbnails are stored locally on purpose.** TikTok's CDN URLs are signed and
expire in about 24 hours, so hot-linking them would leave you with broken
images by tomorrow. The videos themselves stream live from TikTok's official
embed player when you click a card.

## Updating it later

When he posts new videos, edit the `VIDEOS` array at the top of
`js/main.js` — each entry needs an `id`, `cap`, `views`, `cat`
(`pizza` | `burger` | `dessert` | `misc`) and `label`. Then drop the new
thumbnail into `assets/` as `thumb-<id>.jpg`.

To grab a thumbnail for a new video:

```bash
curl -s "https://www.tiktok.com/oembed?url=https://www.tiktok.com/@jvalidfoodreviews/video/VIDEO_ID" | python3 -c "import sys,json;print(json.load(sys.stdin)['thumbnail_url'])"
```

Also bump the follower/like/video numbers in the `data-count` attributes in
`index.html` so the counters stay accurate.

## Little things

- Press **F** anywhere on the page for a food rain easter egg.
- Everything respects `prefers-reduced-motion`.
- Fonts load from Google Fonts, so first paint needs a connection.
