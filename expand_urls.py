"""Expand URL list by scraping 'Editors' Picks' links from each panorama page.

Usage:  python expand_urls.py [--parallel N] [--iter N] [--seed FILE]
  --iter N   : number of BFS expansion rounds (default 1)
  --seed F   : file with initial URLs (default all_urls.txt)
"""
import os, re, sys, time, sqlite3
import http.cookiejar, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

BASE = os.path.dirname(os.path.abspath(__file__))
SEED = os.path.join(BASE, "all_urls.txt")
COOKIES = os.path.join(BASE, "360cities_cookies.txt")
DB = os.path.join(BASE, "panoramas.db")
OUT = os.path.join(BASE, "expanded_urls.txt")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

SLUG_RE = re.compile(r"href=['\"](?:https://www\.360cities\.net)?/(?:[a-z]{2}/)?image/([a-z0-9][a-z0-9_-]+?)(?:\?|['\"])")
# The /xx/image/ (lang prefix) or /image/ — capture slug, skip language-prefixed "self" links

def load_cookies(path):
    cj = http.cookiejar.MozillaCookieJar()
    cj.load(path, ignore_discard=True, ignore_expires=True)
    return cj

def fetch(url, opener, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en"})
    with opener.open(req, timeout=timeout) as r:
        return r.status, r.read().decode("utf-8", errors="replace")

def slug_of(u): return u.rstrip("/").rsplit("/", 1)[-1].split("?")[0]

def main():
    parallel = 6
    iters = 1
    seed_file = SEED
    args = sys.argv[1:]
    if "--parallel" in args: parallel = int(args[args.index("--parallel")+1])
    if "--iter" in args: iters = int(args[args.index("--iter")+1])
    if "--seed" in args: seed_file = args[args.index("--seed")+1]

    known = set()
    # Already-known from seed
    for line in open(seed_file, encoding="utf-8"):
        s = line.strip()
        if s and "/image/" in s:
            known.add(slug_of(s))
    print(f"Seed: {len(known)} slugs from {seed_file}")

    # Already-scraped from DB (avoid refetching)
    conn = sqlite3.connect(DB)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS expansion (
            slug TEXT PRIMARY KEY,
            scraped_at INTEGER,
            http_status INTEGER,
            related_count INTEGER
        );
    """)
    already_expanded = {r[0] for r in conn.execute("SELECT slug FROM expansion WHERE http_status=200")}
    print(f"Already expanded in DB: {len(already_expanded)}")

    cj = load_cookies(COOKIES)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    discovered_total = set(known)
    db_lock = Lock()
    ctr_lock = Lock()

    def process(slug):
        url = f"https://www.360cities.net/image/{slug}"
        try:
            status, html = fetch(url, opener)
            if status != 200:
                return slug, status, set()
            new_slugs = set()
            for m in SLUG_RE.finditer(html):
                s = m.group(1)
                if s != slug:
                    new_slugs.add(s)
            return slug, status, new_slugs
        except Exception as e:
            return slug, 0, set()

    for it in range(iters):
        to_fetch = [s for s in (known - already_expanded)]
        if not to_fetch:
            print(f"Iter {it+1}: nothing to expand")
            break
        print(f"\n=== Iteration {it+1}/{iters}: expanding {len(to_fetch)} slugs ===")
        start = time.time()
        ctr = {"ok":0, "err":0, "total":len(to_fetch), "new":0}
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            futs = [ex.submit(process, s) for s in to_fetch]
            for fut in as_completed(futs):
                slug, status, new_slugs = fut.result()
                with db_lock:
                    conn.execute("INSERT OR REPLACE INTO expansion VALUES (?,?,?,?)",
                                 (slug, int(time.time()), status, len(new_slugs)))
                    conn.commit()
                with ctr_lock:
                    if status == 200: ctr["ok"] += 1
                    else: ctr["err"] += 1
                    for s in new_slugs:
                        if s not in discovered_total:
                            discovered_total.add(s)
                            ctr["new"] += 1
                    n = ctr["ok"] + ctr["err"]
                    if n % 50 == 0 or n == ctr["total"]:
                        el = time.time() - start
                        rate = n/el if el>0 else 0
                        eta = (ctr["total"]-n)/rate if rate>0 else 0
                        print(f"  [{n}/{ctr['total']}] OK={ctr['ok']} ERR={ctr['err']} new={ctr['new']} | {rate:.1f}/s | ETA {eta/60:.1f}min")
        known = discovered_total.copy()  # next iteration uses ALL known
        already_expanded.update(to_fetch)

    # Save expanded list
    with open(OUT, "w", encoding="utf-8") as f:
        for s in sorted(discovered_total):
            f.write(f"https://www.360cities.net/image/{s}\n")
    print(f"\n=== DONE ===")
    print(f"Total unique slugs: {len(discovered_total)}")
    print(f"Saved to: {OUT}")

if __name__ == "__main__":
    main()
