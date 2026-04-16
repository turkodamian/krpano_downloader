# krpanoDownloader

Descargador de panoramas 360 desde 360cities.net y otros sitios que usan krpano, más herramientas para scrapear metadata del catálogo completo.

## 📦 Base de datos pública

Scrapeo completo del catálogo de 360cities (**~450,000 panoramas** con tags, autor, fechas, resolución, geo, views, likes, thumbnail, licencia).

- **Descarga directa** (SQLite zippeada, 202 MB):
  [360cities_v02.db.zip](https://drive.google.com/uc?id=1m8M1Yobyye72YttdEWDIdywPUMos2gBW&export=download)
- **Ver en Drive**:
  [drive.google.com/file/d/1m8M1Yobyye72YttdEWDIdywPUMos2gBW](https://drive.google.com/file/d/1m8M1Yobyye72YttdEWDIdywPUMos2gBW/view)

### Estructura de la DB

```sql
-- Tabla principal (22 columnas + metadata)
panoramas(slug, url, title, og_title, author, author_handle, copyright,
          description, description_full, lat, lon, pano_type,
          resolution, res_w, res_h, date_taken, date_uploaded, date_published,
          views, likes, thumbnail_url, license_url, image_id, gigapixel_real,
          editor_pick, is_gigapixel, scraped_at, http_status, error)

-- Tags many-to-many (204k tags únicos)
tags(panorama_slug, tag_slug, tag_name)

-- Colecciones/series
sets(panorama_slug, set_slug)
```

### Ejemplos de consulta

```sql
-- Top 50 por vistas
SELECT slug, title, views FROM panoramas ORDER BY views DESC LIMIT 50;

-- Panoramas con tag específico
SELECT p.slug, p.title FROM panoramas p
JOIN tags t ON p.slug = t.panorama_slug
WHERE t.tag_slug = 'aerial';

-- Gigapixel (>= 1 billion píxeles)
SELECT slug, resolution FROM panoramas WHERE gigapixel_real = 1;

-- Más vistos por autor
SELECT author, SUM(views) total_views FROM panoramas
GROUP BY author ORDER BY total_views DESC LIMIT 20;
```

## 🛠️ Scripts

| Script | Descripción |
|---|---|
| `krpano_downloader.py` | Descarga tiles + stitch cube → equirectangular (conserva `cube_strip.png` + `{slug}_equirectangular.png`) |
| `resume_download.py` | Reanuda batch leyendo `remaining_urls.txt`, scanea carpetas `output-*` |
| `scrape_tags.py` | Scrapea metadata del catálogo completo a SQLite |
| `expand_urls.py` | Expande lista de URLs via "Editors' Picks" relacionados |
| `upload_to_drive.py` | Sube `*_equirectangular.png` a Drive (`FOOTAGE/360Cities/`) |
| `upload_cubes.py` | Sube `cube_strip.png` renombrados a `{slug}_cube_strip.png` (`FOOTAGE/360Cities/cubes/`) |

## Uso

```bash
pip install pillow numpy requests google-api-python-client google-auth

# Descargar 1 panorama
python krpano_downloader.py --parallel 1 --batch https://www.360cities.net/image/<slug>

# Descargar batch desde archivo
python krpano_downloader.py --parallel 6 --batch-file urls.txt

# Scrape metadata (requiere 360cities_cookies_fresh.txt de browser logueado)
python scrape_tags.py --parallel 12 --urls all_urls_full.txt
```

## Scraper — campos y endpoints

Ver [docs/memory/reference_scrape_endpoints.md](docs/memory/reference_scrape_endpoints.md) para:
- Endpoints que funcionan (sitemap, AJAX views, etc.)
- Endpoints bloqueados por Cloudflare
- Patrones HTML para extracción

## Requisitos

- Python 3.8+
- Pillow, NumPy, Requests
- `google-api-python-client` (solo para uploads a Drive)
- Cookies válidas de sesión logueada en 360cities.net (usar extensión "Get cookies.txt LOCALLY")

## Notas

- Scrape del catálogo completo: ~8-15 horas con 4 procesos paralelos de 12 workers cada uno (450k panoramas × 2 requests = 900k calls)
- Cloudflare throttlea per-IP; rotar IP (VPN, hotspot, ISP alternativo) resetea el bucket
- Views vienen de endpoint AJAX `/data/get_no_of_views?id={image_id}`, requiere `Referer` + `X-Requested-With: XMLHttpRequest`
- Editor's Pick y Gigapixel flags NO son scrapables del HTML (JS los setea async)
