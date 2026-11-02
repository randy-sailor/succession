# succession.org

A single-page reference library on leadership and ownership transition, plus a daily-updated feed of current coverage.

## How it is built

- `index.html` is the whole site: inline CSS and a small inline script, no build tooling.
- **The feed** is generated, not fetched in the browser. `scripts/build_feed.py` pulls the sources listed in `feeds.json`, filters them for relevance, and writes the result into `index.html` (between the `<!--FEED:START-->` and `<!--FEED:END-->` markers) and into `feed/feed.json`. Because the output is plain HTML, the page needs no JavaScript or cross-origin requests to show the feed, works when opened from disk, and is readable by search engines. Only headlines, publisher names, dates and links back to the originals are stored.
- `.github/workflows/update-feed.yml` runs the builder every day at 11:17 UTC and commits when something new arrives. It can also be run on demand from the repository's **Actions** tab.

## Run the feed builder locally

```bash
python3 scripts/build_feed.py
```

Standard library only (Python 3.9+). If too few items come back, it leaves the existing feed untouched and exits non-zero. When nothing new has arrived it writes nothing, so the repository does not collect empty commits; add `--force` to re-render anyway (for example after changing the item markup).

## Add or tune a source

Edit `feeds.json`:

| Field | Meaning |
| --- | --- |
| `url` / `query` | An RSS or Atom URL, or (with `"type": "gnews"`) a Google News search |
| `category` | `exit`, `family`, `ceo`, or `research` (these drive the filter chips) |
| `quota` | Guarantee the source its latest N items, so primary sources are not drowned out by news |
| `trusted` | Skip keyword filtering (use for sources that are entirely on-topic) |
| `require` / `exclude` | Keep only titles containing a term / drop titles containing a term |
| `exclude_url` | Drop items whose link contains a fragment |

Global noise filters (`global_exclude`, `exclude_publisher`) and the story de-duplication threshold also live in this file.

## Keeping the data current

The statistics in "The case" are checked by hand against their primary sources and dated on the page ("Figures reviewed ..."). The feed keeps the page current between those reviews; it does not change the statistics. Re-verify the stat cards whenever Deloitte, EPI, McKinsey or Challenger publish new editions.
