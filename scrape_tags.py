"""Scrape full metadata from 360cities panorama pages into SQLite.

Usage:  python scrape_tags.py [--parallel N] [--limit N] [--urls FILE] [--force]
  --force : re-scrape even if already http_status=200
"""
import os, re, sys, time, sqlite3, socket
import http.cookiejar, urllib.request
import http.client
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Global bind source IP (if set by --bind-ip, all outgoing HTTPS sockets bind to it)
BIND_SOURCE_IP = None

class BoundHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        if BIND_SOURCE_IP:
            kwargs['source_address'] = (BIND_SOURCE_IP, 0)
        super().__init__(*args, **kwargs)

class BoundHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(BoundHTTPSConnection, req)

BASE = os.path.dirname(os.path.abspath(__file__))
URLS_FILE = os.path.join(BASE, "all_urls.txt")
COOKIES_FILE = os.path.join(BASE, "360cities_cookies.txt")
DB_FILE = os.path.join(BASE, "panoramas.db")
_fresh = os.path.join(BASE, "360cities_cookies_fresh.txt")
if os.path.exists(_fresh):
    COOKIES_FILE = _fresh
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

SCHEMA = """
CREATE TABLE IF NOT EXISTS panoramas (
    slug          TEXT PRIMARY KEY,
    url           TEXT NOT NULL,
    title         TEXT,
    og_title      TEXT,
    author        TEXT,
    author_handle TEXT,
    copyright     TEXT,
    description   TEXT,
    lat           REAL,
    lon           REAL,
    pano_type     TEXT,
    resolution    TEXT,
    res_w         INTEGER,
    res_h         INTEGER,
    date_taken    TEXT,
    date_uploaded TEXT,
    date_published TEXT,
    views         INTEGER,
    thumbnail_url TEXT,
    license_url   TEXT,
    editor_pick   INTEGER,
    is_gigapixel  INTEGER,
    image_id      INTEGER,
    likes         INTEGER,
    views         INTEGER,
    description_full TEXT,
    gigapixel_real INTEGER,
    scraped_at    INTEGER,
    http_status   INTEGER,
    error         TEXT
);
CREATE TABLE IF NOT EXISTS sets (
    panorama_slug TEXT,
    set_slug      TEXT,
    PRIMARY KEY (panorama_slug, set_slug),
    FOREIGN KEY (panorama_slug) REFERENCES panoramas(slug)
);
CREATE INDEX IF NOT EXISTS idx_sets_slug ON sets(set_slug);
CREATE TABLE IF NOT EXISTS tags (
    panorama_slug TEXT,
    tag_slug      TEXT,
    tag_name      TEXT,
    PRIMARY KEY (panorama_slug, tag_slug),
    FOREIGN KEY (panorama_slug) REFERENCES panoramas(slug)
);
CREATE INDEX IF NOT EXISTS idx_tags_tagslug ON tags(tag_slug);
CREATE INDEX IF NOT EXISTS idx_tags_panoslug ON tags(panorama_slug);
"""

POST_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_panos_author ON panoramas(author)",
    "CREATE INDEX IF NOT EXISTS idx_panos_uploaded ON panoramas(date_uploaded)",
]

MIGRATIONS = [
    "ALTER TABLE panoramas ADD COLUMN og_title TEXT",
    "ALTER TABLE panoramas ADD COLUMN copyright TEXT",
    "ALTER TABLE panoramas ADD COLUMN pano_type TEXT",
    "ALTER TABLE panoramas ADD COLUMN resolution TEXT",
    "ALTER TABLE panoramas ADD COLUMN res_w INTEGER",
    "ALTER TABLE panoramas ADD COLUMN res_h INTEGER",
    "ALTER TABLE panoramas ADD COLUMN date_taken TEXT",
    "ALTER TABLE panoramas ADD COLUMN date_uploaded TEXT",
    "ALTER TABLE panoramas ADD COLUMN date_published TEXT",
    "ALTER TABLE panoramas ADD COLUMN thumbnail_url TEXT",
    "ALTER TABLE panoramas ADD COLUMN license_url TEXT",
    "ALTER TABLE panoramas ADD COLUMN author_handle TEXT",
    "ALTER TABLE panoramas ADD COLUMN editor_pick INTEGER",
    "ALTER TABLE panoramas ADD COLUMN is_gigapixel INTEGER",
    "ALTER TABLE panoramas ADD COLUMN image_id INTEGER",
    "ALTER TABLE panoramas ADD COLUMN likes INTEGER",
    "ALTER TABLE panoramas ADD COLUMN description_full TEXT",
    "ALTER TABLE panoramas ADD COLUMN gigapixel_real INTEGER",
]

def load_cookie_jar(path):
    cj = http.cookiejar.MozillaCookieJar()
    cj.load(path, ignore_discard=True, ignore_expires=True)
    return cj

def fetch(url, opener, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"})
    with opener.open(req, timeout=timeout) as r:
        data = r.read()
        return r.status, data.decode("utf-8", errors="replace")

TAG_RE = re.compile(r"<a href='/search/@tags-([^']+)'>([^<]+)</a>", re.IGNORECASE)
TITLE_RE = re.compile(r"<title>\s*([^<]+?)\s*</title>", re.IGNORECASE | re.DOTALL)
OG_TITLE_RE = re.compile(r'property="og:title"\s+content="([^"]+)"', re.IGNORECASE)
OG_IMAGE_RE = re.compile(r'property="og:image"\s+content="([^"]+)"', re.IGNORECASE)
OG_DESC_RE = re.compile(r'property="og:description"\s+content="([^"]+)"', re.IGNORECASE)
OG_LAT_RE = re.compile(r'property="og:latitude"\s+content="([^"]+)"', re.IGNORECASE)
OG_LON_RE = re.compile(r'property="og:longitude"\s+content="([^"]+)"', re.IGNORECASE)
AUTHOR_RE = re.compile(r'<meta name="author" content="([^"]+)"', re.IGNORECASE)
DESC_RE = re.compile(r'<meta name="description" content="([^"]+)"', re.IGNORECASE)
# Metadata panel fields (within data_list div)
FIELD_RE = lambda label: re.compile(
    r'<span class="title">\s*' + label + r':\s*</span>\s*([^<]+?)(?:<)', re.IGNORECASE)
COPYRIGHT_RE = FIELD_RE('Copyright')
TYPE_RE = FIELD_RE('Type')
RES_RE = FIELD_RE('Resolution')
TAKEN_RE = FIELD_RE('Taken')
UPLOADED_RE = FIELD_RE('Uploaded')
PUBLISHED_RE = FIELD_RE('Published')
LICENSE_RE = re.compile(r'"license":\s*"([^"]+)"')
AUTHOR_HANDLE_RE = re.compile(r"user\s*=\s*'([a-z0-9][a-z0-9_-]*)'")
SET_RE = re.compile(r'href=["\'](?:https://www\.360cities\.net)?/sets/([a-z0-9][a-z0-9_-]+)', re.IGNORECASE)
COMMENDATION_PICK_RE = re.compile(r'pano_commendation\s+commendation_pick[^"]*', re.IGNORECASE)
COMMENDATION_GIGA_RE = re.compile(r'pano_commendation\s+commendation_gigapixel[^"]*', re.IGNORECASE)
LIKES_RE = re.compile(r'image-popularity-score["\' >][^>]*>(\d+)\s*Like', re.IGNORECASE)
IMAGE_ID_RE = re.compile(r"/data/get_no_of_views['\"]\s*,\s*\{\s*id:\s*(\d+)")
DESC_FULL_RE = re.compile(r'<div class="col-md-12 collapse-group">(.*?)</div>\s*</div>', re.DOTALL)

def parse(html):
    tags = []
    for m in TAG_RE.finditer(html):
        s = m.group(1)
        if s.startswith("%40") or s.startswith("@"):
            continue
        tags.append((s, m.group(2).strip()))
    seen = set(); uniq = []
    for t in tags:
        if t[0] in seen: continue
        seen.add(t[0]); uniq.append(t)

    def g(r):
        m = r.search(html)
        return m.group(1).strip() if m else None

    title = g(TITLE_RE)
    og_title = g(OG_TITLE_RE)
    og_image = g(OG_IMAGE_RE)
    og_desc = g(OG_DESC_RE)
    og_lat = g(OG_LAT_RE); og_lon = g(OG_LON_RE)
    author = g(AUTHOR_RE)
    desc = g(DESC_RE) or og_desc
    copyright = g(COPYRIGHT_RE)
    pano_type = g(TYPE_RE)
    resolution = g(RES_RE)
    date_taken = g(TAKEN_RE)
    date_uploaded = g(UPLOADED_RE)
    date_published = g(PUBLISHED_RE)
    license_url = g(LICENSE_RE)

    # Parse resolution into w, h
    res_w = res_h = None
    if resolution:
        m = re.match(r'(\d+)\s*x\s*(\d+)', resolution)
        if m: res_w, res_h = int(m.group(1)), int(m.group(2))

    # Geolocation: prefer og:latitude/longitude over ICBM
    lat = lon = None
    try:
        if og_lat: lat = float(og_lat)
        if og_lon: lon = float(og_lon)
    except (ValueError, TypeError): pass
    if lat is None or lon is None:
        m = re.search(r'<meta name="ICBM" content="([^"]+)"', html, re.IGNORECASE)
        if m:
            try:
                parts = m.group(1).split(",")
                lat = float(parts[0].strip()); lon = float(parts[1].strip())
            except Exception: pass

    # Author handle (from JS 'user=' or first /profile/ link)
    author_handle = None
    m = AUTHOR_HANDLE_RE.search(html)
    if m: author_handle = m.group(1)
    if not author_handle:
        m = re.search(r'href=["\']/profile/([a-z0-9][a-z0-9_-]+)["\']', html, re.IGNORECASE)
        if m: author_handle = m.group(1)

    # Sets (collections) - dedupe
    sets_ = list({m.group(1) for m in SET_RE.finditer(html)})

    # Editor's pick flag: find the pano_commendations block with commendation_pick
    # If the div has 'disp_none' class -> NOT a pick; else -> IS a pick
    editor_pick = 0
    m = COMMENDATION_PICK_RE.search(html)
    if m:
        editor_pick = 0 if 'disp_none' in m.group(0) else 1
    is_gigapixel = 0
    m = COMMENDATION_GIGA_RE.search(html)
    if m:
        is_gigapixel = 0 if 'disp_none' in m.group(0) else 1

    # Likes count (server-rendered)
    likes = None
    m = LIKES_RE.search(html)
    if m:
        try: likes = int(m.group(1))
        except: pass

    # Image numeric id (used for AJAX views endpoint)
    image_id = None
    m = IMAGE_ID_RE.search(html)
    if m:
        try: image_id = int(m.group(1))
        except: pass

    # Full description (long form)
    description_full = None
    m = DESC_FULL_RE.search(html)
    if m:
        raw = m.group(1)
        # Strip HTML tags, collapse whitespace
        text = re.sub(r'<br\s*/?>', '\n', raw)
        text = re.sub(r'</p>', '\n\n', text)
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = text.strip()
        if text:
            description_full = text

    return {
        "tags": uniq,
        "sets": sets_,
        "title": title,
        "og_title": og_title,
        "author": author or copyright,
        "author_handle": author_handle,
        "copyright": copyright,
        "description": desc,
        "lat": lat, "lon": lon,
        "pano_type": pano_type,
        "resolution": resolution,
        "res_w": res_w, "res_h": res_h,
        "date_taken": date_taken,
        "date_uploaded": date_uploaded,
        "date_published": date_published,
        "views": None,  # loaded via JS, not in HTML
        "thumbnail_url": og_image,
        "license_url": license_url,
        "editor_pick": editor_pick,
        "is_gigapixel": is_gigapixel,
        "likes": likes,
        "image_id": image_id,
        "description_full": description_full,
    }

def main():
    parallel = 6
    limit = None
    urls_file = URLS_FILE
    force = False
    args = sys.argv[1:]
    if "--parallel" in args: parallel = int(args[args.index("--parallel") + 1])
    if "--limit" in args: limit = int(args[args.index("--limit") + 1])
    if "--urls" in args: urls_file = args[args.index("--urls") + 1]
    if "--force" in args: force = True
    if "--bind-ip" in args:
        global BIND_SOURCE_IP
        BIND_SOURCE_IP = args[args.index("--bind-ip") + 1]
        print(f"Binding outgoing connections to source IP: {BIND_SOURCE_IP}")

    conn = sqlite3.connect(DB_FILE)
    conn.executescript(SCHEMA)
    for m in MIGRATIONS:
        try: conn.execute(m)
        except sqlite3.OperationalError: pass  # already applied
    for ix in POST_INDEXES:
        try: conn.execute(ix)
        except sqlite3.OperationalError: pass
    conn.commit()

    urls = [l.strip() for l in open(urls_file, encoding="utf-8") if l.strip()]
    slug_of = lambda u: u.rstrip("/").rsplit("/", 1)[-1]

    if force:
        todo = urls
    else:
        # Skip rows with new schema filled (thumbnail_url IS NOT NULL OR error)
        done = {r[0] for r in conn.execute(
            "SELECT slug FROM panoramas WHERE http_status=200 AND image_id IS NOT NULL"
        )}
        todo = [u for u in urls if slug_of(u) not in done]
    if limit: todo = todo[:limit]
    print(f"Total URLs: {len(urls)} | To scrape (full schema): {len(todo)} | Workers: {parallel}")

    cj = load_cookie_jar(COOKIES_FILE)
    handlers = [urllib.request.HTTPCookieProcessor(cj)]
    if BIND_SOURCE_IP:
        handlers.append(BoundHTTPSHandler())
    opener = urllib.request.build_opener(*handlers)
    db_lock = Lock(); ctr_lock = Lock()
    counter = {"ok": 0, "err": 0, "total": len(todo)}

    def fetch_views(image_id, referer):
        if not image_id: return None
        try:
            req = urllib.request.Request(
                f"https://www.360cities.net/data/get_no_of_views?id={image_id}",
                headers={"User-Agent": UA, "X-Requested-With": "XMLHttpRequest",
                         "Referer": referer, "Accept": "application/json"})
            with opener.open(req, timeout=15) as r:
                if r.status == 200:
                    import json
                    data = json.loads(r.read())
                    return int(data.get("view_count", 0))
        except Exception: pass
        return None

    def worker(url):
        slug = slug_of(url)
        try:
            status, html = fetch(url, opener)
            if status != 200:
                return slug, url, None, f"HTTP {status}", status
            data = parse(html)
            # Second request for views
            data["views"] = fetch_views(data.get("image_id"), url)
            return slug, url, data, None, status
        except Exception as e:
            return slug, url, None, str(e)[:200], 0

    def write(slug, url, d, err, status):
        with db_lock:
            ts = int(time.time())
            if d:
                # Compute gigapixel_real (>= 1 billion pixels)
                gpr = 1 if (d.get("res_w") and d.get("res_h") and d["res_w"]*d["res_h"] >= 1_000_000_000) else 0
                conn.execute("""INSERT OR REPLACE INTO panoramas
                    (slug,url,title,og_title,author,author_handle,copyright,description,lat,lon,
                     pano_type,resolution,res_w,res_h,date_taken,date_uploaded,date_published,
                     views,thumbnail_url,license_url,editor_pick,is_gigapixel,
                     image_id,likes,description_full,gigapixel_real,
                     scraped_at,http_status,error)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (slug, url, d["title"], d["og_title"], d["author"], d["author_handle"], d["copyright"], d["description"],
                     d["lat"], d["lon"], d["pano_type"], d["resolution"], d["res_w"], d["res_h"],
                     d["date_taken"], d["date_uploaded"], d["date_published"],
                     d["views"], d["thumbnail_url"], d["license_url"], d["editor_pick"], d["is_gigapixel"],
                     d["image_id"], d["likes"], d["description_full"], gpr,
                     ts, status, None))
                conn.execute("DELETE FROM tags WHERE panorama_slug=?", (slug,))
                for ts_, tn in d["tags"]:
                    conn.execute("INSERT OR IGNORE INTO tags VALUES (?,?,?)", (slug, ts_, tn))
                conn.execute("DELETE FROM sets WHERE panorama_slug=?", (slug,))
                for set_slug in d["sets"]:
                    conn.execute("INSERT OR IGNORE INTO sets VALUES (?,?)", (slug, set_slug))
            else:
                conn.execute("""INSERT OR REPLACE INTO panoramas
                    (slug,url,scraped_at,http_status,error) VALUES (?,?,?,?,?)""",
                    (slug, url, ts, status, err))
            conn.commit()

    start = time.time()
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        futs = {ex.submit(worker, u): u for u in todo}
        for fut in as_completed(futs):
            slug, url, d, err, status = fut.result()
            write(slug, url, d, err, status)
            with ctr_lock:
                if err: counter["err"] += 1
                else: counter["ok"] += 1
                n = counter["ok"] + counter["err"]
                if n % 50 == 0 or n == counter["total"]:
                    el = time.time() - start
                    rate = n/el if el > 0 else 0
                    eta = (counter["total"] - n) / rate if rate > 0 else 0
                    print(f"[{n}/{counter['total']}] OK={counter['ok']} ERR={counter['err']} | {rate:.1f}/s | ETA {eta/60:.1f}min")

    el = time.time() - start
    print(f"\nDone in {el/60:.1f} min | OK={counter['ok']} ERR={counter['err']}")
    # Summary
    c = conn.execute("SELECT COUNT(*) FROM panoramas WHERE http_status=200").fetchone()[0]
    full = conn.execute("SELECT COUNT(*) FROM panoramas WHERE thumbnail_url IS NOT NULL").fetchone()[0]
    t = conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    ut = conn.execute("SELECT COUNT(DISTINCT tag_slug) FROM tags").fetchone()[0]
    print(f"Panoramas stored: {c} | Full-schema: {full} | Tag entries: {t} | Unique tags: {ut}")

if __name__ == "__main__":
    main()
