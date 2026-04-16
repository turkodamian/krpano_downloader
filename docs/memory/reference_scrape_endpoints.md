---
name: 360cities scrape endpoints and field extraction
description: Working endpoints, HTML patterns, AJAX calls for extracting panorama metadata
type: reference
originSessionId: 3119cbb0-317f-4497-a688-5bd55c8cf173
---
**Endpoints that work (with fresh logged-in cookies at 360cities_cookies_fresh.txt):**
- `https://www.360cities.net/sitemap.xml` — sitemap index listing all image.N.sitemap.xml
- `https://www.360cities.net/image.{1..15}.sitemap.xml` — 30k URLs each (450k total panoramas)
- `https://www.360cities.net/profile.1.sitemap.xml` — 15,791 author profiles
- `https://www.360cities.net/area.1.sitemap.xml` — 766 geographic areas
- `https://www.360cities.net/image/{slug}` — individual panorama HTML (main data source)
- `https://www.360cities.net/data/get_no_of_views?id={image_id}` — view count JSON. REQUIRES headers: `X-Requested-With: XMLHttpRequest`, `Referer: <panorama URL>`, `Accept: application/json`
- `https://www.360cities.net/profile/{handle}` — author pages (~1.8 MB each, lists all their panoramas)
- `https://www.360cities.net/image/load_thumbnails/{slug}?type=nearby&user_handle={handle}` — nearby panoramas AJAX

**Endpoints blocked by Cloudflare even with cookies:**
- `/search/@tags-<tag>` — tag browse pages (HTTP 403)

**HTML extraction patterns (inside panorama page):**
- `<meta property="og:image" content="...">` → thumbnail_url (CDN path)
- `<meta property="og:latitude" content="...">` and `og:longitude` → precise geo
- `<meta property="og:title" content="...">` → full title
- `<div class="col-md-12 data_list">` → contains Copyright, Type, Resolution, Taken, Uploaded, Published labels
- `<span class="title">{label}:</span>{value}<` — extract each metadata field
- `<a href='/search/@tags-{slug}'>{name}</a>` → tags (skip those starting with `%40` or `@`)
- `<a href='/sets/{slug}'>` → set memberships
- `<p class="mart10 text-center image-popularity-score">{N} Likes</p>` → likes count
- JS: `getJSON('/data/get_no_of_views', { id: {N}, timing_data: ... })` → extract numeric image_id
- `<div class="col-md-12 collapse-group">` → contains long-form description HTML

**NOT in HTML (cannot scrape):**
- Editor's Pick flag (div always has `disp_none`, JS shows via async)
- Gigapixel flag (same as editor's pick)
- Views count (loaded via AJAX — use /data/get_no_of_views endpoint)
- Comments count

**Code lives in:** `C:\Appz\krpanoDownloader-main\scrape_tags.py` (supports `--parallel N --urls FILE --force --bind-ip IP` flags).
