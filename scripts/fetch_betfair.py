#!/usr/bin/env python3
"""
Scrape Betfair WC2026 articles and save to data/betfair_feed.json
Runs in GitHub Actions where Betfair is accessible.
"""
import requests, json, re, os
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-GB,en;q=0.9",
}

def try_rss():
    """Try the Betfair RSS feed directly."""
    r = requests.get("https://betting.betfair.com/football/index.xml",
                     headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    items = []
    for m in re.finditer(r'<item>([\s\S]*?)</item>', r.text):
        b = m.group(1)
        title = (re.search(r'<title><!\[CDATA\[(.*?)\]\]></title>', b) or
                 re.search(r'<title>(.*?)</title>', b))
        link  = re.search(r'<link>(https?://[^<]+)</link>', b)
        date  = re.search(r'<pubDate>(.*?)</pubDate>', b)
        desc  = (re.search(r'<description><!\[CDATA\[([\s\S]*?)\]\]></description>', b) or
                 re.search(r'<description>([\s\S]*?)</description>', b))
        if title and link:
            d = re.sub(r'<[^>]+>', '', desc.group(1) if desc else '').strip()[:200]
            items.append({
                "title": title.group(1).strip(),
                "link":  link.group(1).strip(),
                "date":  date.group(1).strip() if date else "",
                "desc":  d,
                "isWC":  bool(re.search(r'world.cup|wc.?2026|copa', title.group(1), re.I)),
            })
    return items if items else None

def try_html():
    """Fallback: scrape WC2026 page."""
    r = requests.get("https://betting.betfair.com/football/world-cup-2026/",
                     headers=HEADERS, timeout=20)
    if r.status_code != 200:
        return None
    items = []
    seen = set()
    # Extract article links and titles
    for m in re.finditer(
        r'<a[^>]+href="(https://betting\.betfair\.com/football/world-cup-2026/[^"]{30,})"[^>]*>'
        r'\s*<(?:h\d|span)[^>]*>\s*([^<]{20,150})\s*</(?:h\d|span)>', r.text):
        url, title = m.group(1), m.group(2).strip()
        if url in seen: continue
        seen.add(url)
        items.append({"title": title, "link": url, "date": "", "desc": "", "isWC": True})
        if len(items) >= 15: break
    return items if items else None

items = try_rss() or try_html() or []

# Sort: WC first, then by date
items.sort(key=lambda x: (0 if x.get('isWC') else 1, x.get('date','')), reverse=False)
items = [x for x in items if x.get('isWC')] + [x for x in items if not x.get('isWC')]
items = items[:20]

out = {
    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    "source": "betting.betfair.com",
    "count": len(items),
    "items": items,
}

os.makedirs("data", exist_ok=True)
with open("data/betfair_feed.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print(f"✅ Saved {len(items)} articles to data/betfair_feed.json")
for it in items[:5]:
    print(f"  {'🏆' if it['isWC'] else '⚽'} {it['title'][:70]}")
