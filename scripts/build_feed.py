#!/usr/bin/env python3
"""Build the succession.org content feed.

Reads feeds.json, pulls each RSS/Atom source, filters for relevance, de-duplicates,
and writes two things:

  feed/feed.json   machine-readable list of items
  index.html       the region between <!--FEED:START--> and <!--FEED:END-->
                   (plus the "updated" stamp) is regenerated as static HTML

Static output means the page needs no JavaScript or cross-origin requests to show
the feed, works from a file:// preview, and is visible to search engines.

Only the headline, publisher, date and a link back to the original are kept; no
article text is copied. Standard library only. Run:  python3 scripts/build_feed.py
"""
import html
import json
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "feeds.json"
OUT_JSON = ROOT / "feed" / "feed.json"
INDEX = ROOT / "index.html"
UA = "succession.org-feed-builder/1.0 (+https://github.com/randy-sailor/succession)"
ATOM = "{http://www.w3.org/2005/Atom}"


def log(msg):
    print(msg, file=sys.stderr)


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def gnews_url(query):
    q = urllib.parse.quote_plus(query + " when:60d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def parse_date(text):
    if not text:
        return None
    text = text.strip()
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def safe_url(url):
    """Only plain http(s) links are ever emitted."""
    if not url:
        return None
    p = urllib.parse.urlparse(url.strip())
    return url.strip() if p.scheme in ("http", "https") and p.netloc else None


def parse_items(raw):
    root = ET.fromstring(raw)
    out = []
    for it in root.iter("item"):  # RSS
        src = it.find("source")
        out.append({
            "title": it.findtext("title") or "",
            "link": it.findtext("link") or "",
            "date": parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")),
            "publisher": (src.text or "").strip() if src is not None else "",
        })
    for en in root.iter(ATOM + "entry"):  # Atom
        link = ""
        for l in en.findall(ATOM + "link"):
            if l.get("rel") in (None, "alternate"):
                link = l.get("href") or ""
                break
        out.append({
            "title": en.findtext(ATOM + "title") or "",
            "link": link,
            "date": parse_date(en.findtext(ATOM + "published") or en.findtext(ATOM + "updated")),
            "publisher": "",
        })
    return out


def clean_title(title, publisher):
    title = html.unescape(re.sub(r"\s+", " ", title)).strip()
    # Google News appends " - Publisher"
    if publisher and title.endswith(" - " + publisher):
        title = title[: -(len(publisher) + 3)].rstrip()
    return title


def norm(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def contains_any(text, terms):
    t = text.lower()
    return any(term.lower() in t for term in terms)


def tag_for(source, item):
    link = item["link"].lower()
    title = item["title"].lower()
    if "/podcast" in link or title.startswith("episode ") or "podcast" in title:
        return "Podcast"
    return source.get("tag", "News")


STOPWORDS = set("""a an and are as at be by for from has have how in into is it its more new of on one or our out over
says say than that the their them this to up was were what when where which who why will with without you your
family business businesses succession successor planning plan plans ceo leadership leader leaders owner owners
company companies news""".split())


def tokens(title):
    return {w for w in norm(title).split() if len(w) >= 3 and w not in STOPWORDS}


def same_story(a, b, threshold):
    """True when two headlines are probably about the same event."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= threshold


def collect(cfg):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cfg["max_age_days"])
    quota_cutoff = now - timedelta(days=cfg["quota_max_age_days"])
    items, ok_sources = [], 0
    for src in cfg["sources"]:
        url = gnews_url(src["query"]) if src.get("type") == "gnews" else src["url"]
        label = src.get("query") or src["name"]
        try:
            parsed = parse_items(fetch(url))
        except Exception as e:  # one bad source must never sink the build
            log(f"  ! {label[:60]}: {e}")
            continue
        ok_sources += 1
        kept = []
        for it in parsed:
            link = safe_url(it["link"])
            if not link or not it["date"]:
                continue
            publisher = it["publisher"] or src["name"]
            if contains_any(publisher, cfg.get("exclude_publisher", [])):
                continue
            title = clean_title(it["title"], publisher)
            if not title:
                continue
            if contains_any(title, cfg.get("global_exclude", [])) or contains_any(title, src.get("exclude", [])):
                continue
            if any(frag in link for frag in src.get("exclude_url", [])):
                continue
            if not src.get("trusted") and src.get("require") and not contains_any(title, src["require"]):
                continue
            kept.append({
                "title": title, "url": link, "date": it["date"], "source": publisher,
                "category": src["category"], "tag": tag_for(src, {"link": link, "title": title}),
            })
        kept.sort(key=lambda x: x["date"], reverse=True)
        quota = src.get("quota", 0)
        chosen = []
        for rank, k in enumerate(kept):
            if k["date"] >= cutoff:
                chosen.append({**k, "guaranteed": rank < quota})
            elif rank < quota and k["date"] >= quota_cutoff:
                # a quiet primary source still gets its latest items, within reason
                chosen.append({**k, "guaranteed": True})
        items.extend(chosen)
        log(f"  ok {label[:58]:58} {len(parsed):3} parsed -> {len(kept):3} relevant, {len(chosen):3} in window")
    return items, ok_sources


def dedupe_and_rank(items, cfg):
    """Primary sources get their guaranteed slots first; news fills the rest."""
    items.sort(key=lambda x: x["date"], reverse=True)
    primary = {s["name"] for s in cfg["sources"] if s.get("type") != "gnews"}
    threshold = cfg.get("cluster_threshold", 0.5)
    out, per_pub = [], {}

    def duplicate(it):
        key = norm(it["title"])
        return any(norm(o["title"])[:48] == key[:48] or same_story(o["title"], it["title"], threshold) for o in out)

    for it in (i for i in items if i["guaranteed"]):
        if not duplicate(it):
            out.append(it)
            per_pub[it["source"].lower()] = per_pub.get(it["source"].lower(), 0) + 1
    # Fill the remaining slots round-robin across topics so no single topic floods the feed.
    queues = {c: [i for i in items if not i["guaranteed"] and i["category"] == c] for c in cfg["categories"]}
    while len(out) < cfg["max_items"] and any(queues.values()):
        for cat in cfg["categories"]:
            q = queues[cat]
            while q:
                it = q.pop(0)
                pub = it["source"].lower()
                if per_pub.get(pub, 0) >= cfg["max_per_publisher"] and it["source"] not in primary:
                    continue
                if duplicate(it):
                    continue
                out.append(it)
                per_pub[pub] = per_pub.get(pub, 0) + 1
                break
            if len(out) >= cfg["max_items"]:
                break
    out.sort(key=lambda x: x["date"], reverse=True)
    return out[: cfg["max_items"]]


def render(items, cats):
    rows = []
    for it in items:
        d = it["date"]
        rows.append(
            '        <li class="feed-item" data-cat="%s">\n'
            '          <time datetime="%s">%s</time>\n'
            '          <a class="feed-title" href="%s" target="_blank" rel="noopener">%s</a>\n'
            '          <span class="feed-meta"><span class="feed-src">%s</span><span class="feed-tag">%s</span></span>\n'
            '        </li>' % (
                html.escape(it["category"], quote=True), d.strftime("%Y-%m-%d"), d.strftime("%b %-d"),
                html.escape(it["url"], quote=True), html.escape(it["title"]),
                html.escape(it["source"]), html.escape(it["tag"]),
            ))
    return "\n".join(rows)


def splice(text, start, end, body):
    pat = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
    if not pat.search(text):
        raise SystemExit(f"marker {start} not found in index.html")
    return pat.sub(lambda _m: start + "\n" + body + "\n        " + end, text, count=1)


def main():
    cfg = json.loads(CONFIG.read_text())
    log("Fetching sources:")
    items, ok = collect(cfg)
    ranked = dedupe_and_rank(items, cfg)
    log(f"{ok}/{len(cfg['sources'])} sources reachable; {len(ranked)} items selected")
    if ok == 0 or len(ranked) < 5:
        log("Too little data returned; leaving the existing feed untouched.")
        return 1

    now = datetime.now(timezone.utc)
    new_items = [{**i, "date": i["date"].strftime("%Y-%m-%d")} for i in ranked]
    for i in new_items:
        i.pop("guaranteed", None)
    if OUT_JSON.exists() and "--force" not in sys.argv:  # --force re-renders after a template change
        try:
            if json.loads(OUT_JSON.read_text()).get("items") == new_items:
                log("No new items since the last build; nothing to write.")
                return 0
        except ValueError:
            pass
    OUT_JSON.parent.mkdir(exist_ok=True)
    OUT_JSON.write_text(json.dumps({
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "items": new_items,
    }, indent=2, ensure_ascii=False) + "\n")

    text = INDEX.read_text()
    text = splice(text, "<!--FEED:START-->", "<!--FEED:END-->", render(ranked, cfg["categories"]))
    stamp = '<time datetime="%s">%s</time>' % (now.strftime("%Y-%m-%d"), now.strftime("%B %-d, %Y"))
    text = splice(text, "<!--FEED:UPDATED-->", "<!--/FEED:UPDATED-->", "        " + stamp)
    INDEX.write_text(text)
    log("Wrote feed/feed.json and refreshed index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main())
