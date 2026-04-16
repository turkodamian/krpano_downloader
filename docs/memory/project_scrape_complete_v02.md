---
name: 360cities full scrape v02 complete
description: Full 360cities catalog scraped (450k panoramas, 204k tags). DB uploaded to Drive as 360cities_v02.db.zip
type: project
originSessionId: 3119cbb0-317f-4497-a688-5bd55c8cf173
---
Full 360cities catalog scraped to SQLite DB on 2026-04-16 (session of Apr 14-16).

**Why:** Damian wanted a local searchable database of all 360cities panoramas with metadata + tags to find content easily without depending on 360cities site.

**How to apply:** Use `C:\Appz\krpanoDownloader-main\panoramas.db` (SQLite, WAL mode) as the canonical reference. Public Drive backup: https://drive.google.com/file/d/1m8M1Yobyye72YttdEWDIdywPUMos2gBW/view (360cities_v02.db.zip, 202 MB zipped). Direct download: https://drive.google.com/uc?id=1m8M1Yobyye72YttdEWDIdywPUMos2gBW&export=download

**Scale discovered:**
- 360cities has **450,000 panoramas** total (from sitemap)
- 15 image sitemaps × 30k URLs each
- 766 geographic areas + 15,791 author profiles
- Sitemap: https://www.360cities.net/sitemap.xml (requires fresh cookies)

**DB contents (final):**
- 451,004 panoramas records (some duplicates from expansion scan)
- 449,914 with full schema (99.76% success)
- 1,563,835 tag entries
- **204,253 unique tags**
- 61 set/collection entries
- ~590 errors total (0.13%)

**Fields captured (22 + tags + sets):**
- Identity: slug, url, title, og_title
- Author: author, author_handle, copyright
- Content: description (meta, truncated), description_full (full long-form)
- Geo: lat, lon (from og:latitude/longitude, more reliable than ICBM)
- Image: resolution, res_w, res_h, pano_type (Spherical 76% / Cylindrical 16% / Partial 8%), thumbnail_url, gigapixel_real (res_w*res_h >= 1B)
- Dates: date_taken, date_uploaded, date_published (71.5% coverage)
- Engagement: views (from /data/get_no_of_views AJAX), likes, image_id
- Legal: license_url
- Useless fields: editor_pick and is_gigapixel always 0 (server-side HTML doesn't expose them, JS sets via async)
