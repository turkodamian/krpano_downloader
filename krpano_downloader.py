# -*- coding: utf-8 -*-
"""
krpano 360cities.net panorama downloader.
Downloads cube face tiles at the highest available quality,
stitches them, and converts to equirectangular projection.

Usage:
    python krpano_downloader.py <360cities_url>
    python krpano_downloader.py --batch <url1> <url2> ...
    python krpano_downloader.py --batch-file urls.txt
    python krpano_downloader.py --parallel 4 --batch-file urls.txt
"""

import os
import sys
import re
import logging
import time
import json
import subprocess
import requests
from io import BytesIO
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

from PIL import Image
import numpy as np

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f"krpano_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logger = logging.getLogger("krpano")
logger.setLevel(logging.DEBUG)

# File handler - verbose
fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(fh)

# Console handler - concise
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(ch)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'image/webp,image/*',
    'Referer': 'https://www.360cities.net/',
}

FACES = ['front', 'right', 'back', 'left', 'up', 'down']

# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def extract_base_url(page_url, session):
    """Extract the CDN base URL from a 360cities.net page."""
    logger.debug(f"Fetching page: {page_url}")

    # Use curl since 360cities blocks python requests
    try:
        result = subprocess.run(
            ['curl', '-s', '-L',
             '-H', 'User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
             '-H', 'Accept: text/html,application/xhtml+xml',
             page_url],
            capture_output=True, timeout=30
        )
        html = result.stdout.decode('utf-8', errors='ignore')
    except Exception as e:
        raise ValueError(f"Failed to fetch page: {e}")

    if not html or len(html) < 100:
        raise ValueError(f"Empty response from {page_url}")

    logger.debug(f"Page size: {len(html)} bytes")

    # Look for og:image meta tag which contains the CDN path
    match = re.search(
        r'content="(https://cloudflare\d*\.360gigapixels\.com/pano/[^"]+?)/equirect[^"]*"',
        html
    )
    if match:
        base = match.group(1)
        logger.debug(f"Found base URL via og:image: {base}")
        return base

    # Fallback: look for any 360gigapixels pano URL
    match = re.search(
        r'(https://cloudflare\d*\.360gigapixels\.com/pano/[^/]+/[^/"]+)',
        html
    )
    if match:
        base = match.group(1)
        logger.debug(f"Found base URL via fallback: {base}")
        return base

    logger.debug(f"HTML snippet (first 2000 chars): {html[:2000]}")
    raise ValueError(f"Could not find panorama CDN URL in {page_url}")


def detect_max_level(base_url, session):
    """Auto-detect the highest available tile level."""
    logger.debug(f"Detecting max level for: {base_url}")
    max_level = 0
    for level in range(1, 10):
        url = f"{base_url}/cube/front/tile/512/{level}/0/0.jpg"
        try:
            resp = session.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 100:
                max_level = level
                logger.debug(f"  Level {level}: OK ({len(resp.content)} bytes)")
            else:
                logger.debug(f"  Level {level}: HTTP {resp.status_code} - stopping")
                break
        except Exception as e:
            logger.debug(f"  Level {level}: Error - {e}")
            break
    if max_level == 0:
        raise ValueError("No tiles found at any level")
    return max_level


def detect_grid_size(base_url, level, face, session):
    """Detect the tile grid dimensions (rows x cols) for a given level and face."""
    logger.debug(f"Detecting grid size for face '{face}' at level {level}")

    cols = 0
    for col in range(30):
        url = f"{base_url}/cube/{face}/tile/512/{level}/0/{col}.jpg"
        try:
            resp = session.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 100:
                cols = col + 1
            else:
                break
        except:
            break

    rows = 0
    for row in range(30):
        url = f"{base_url}/cube/{face}/tile/512/{level}/{row}/0.jpg"
        try:
            resp = session.get(url, headers=HEADERS, timeout=10)
            if resp.status_code == 200 and len(resp.content) > 100:
                rows = row + 1
            else:
                break
        except:
            break

    logger.debug(f"  Face '{face}': {cols} cols x {rows} rows")
    return rows, cols


def download_tile(url, session, retries=3):
    """Download a single tile with retries. Returns PIL Image or None."""
    for attempt in range(retries):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 200 and len(resp.content) > 100:
                return Image.open(BytesIO(resp.content))
            elif resp.status_code == 403:
                logger.debug(f"  Tile 403: {url}")
                return None
            else:
                logger.debug(f"  Tile HTTP {resp.status_code}: {url} (attempt {attempt+1})")
        except Exception as e:
            logger.debug(f"  Tile error: {url} - {e} (attempt {attempt+1})")
            if attempt < retries - 1:
                time.sleep(1)
    return None


def download_and_stitch_face(base_url, face, level, rows, cols, session, output_dir):
    """Download all tiles for a face and stitch them together."""
    tiles_dir = os.path.join(output_dir, "tiles", face)
    os.makedirs(tiles_dir, exist_ok=True)

    tiles = {}
    missing = []
    logger.info(f"  [{face}] Downloading {cols}x{rows} tiles...")

    for row in range(rows):
        for col in range(cols):
            url = f"{base_url}/cube/{face}/tile/512/{level}/{row}/{col}.jpg"
            cache_path = os.path.join(tiles_dir, f"{row}_{col}.jpg")

            tile = None
            if os.path.exists(cache_path):
                try:
                    tile = Image.open(cache_path)
                except:
                    os.remove(cache_path)

            if tile is None:
                tile = download_tile(url, session)
                if tile:
                    tile.save(cache_path, quality=95)

            if tile:
                tiles[(row, col)] = tile
            else:
                missing.append((row, col))

    if missing:
        logger.warning(f"  [{face}] Missing {len(missing)} tiles: {missing}")

    if not tiles:
        logger.error(f"  [{face}] No tiles downloaded!")
        return None

    # Calculate total dimensions from actual tile sizes
    total_width = sum(tiles[(0, col)].size[0] for col in range(cols) if (0, col) in tiles)
    total_height = sum(tiles[(row, 0)].size[1] for row in range(rows) if (row, 0) in tiles)

    logger.info(f"  [{face}] Stitched: {total_width}x{total_height} ({len(tiles)}/{rows*cols} tiles)")

    # Log unique tile sizes for debugging
    tile_sizes = set(t.size for t in tiles.values())
    logger.debug(f"  [{face}] Unique tile sizes: {tile_sizes}")

    face_img = Image.new('RGB', (total_width, total_height))

    y_offset = 0
    for row in range(rows):
        x_offset = 0
        row_height = 0
        for col in range(cols):
            if (row, col) in tiles:
                tile = tiles[(row, col)]
                face_img.paste(tile, (x_offset, y_offset))
                x_offset += tile.size[0]
                row_height = max(row_height, tile.size[1])
            else:
                # Estimate missing tile width
                if (0, col) in tiles:
                    x_offset += tiles[(0, col)].size[0]
                else:
                    x_offset += 512
        if row_height == 0:
            row_height = tiles.get((row - 1, 0), tiles.get((0, 0))).size[1] if tiles else 512
        y_offset += row_height

    return face_img


def cube_to_equirectangular(cube_faces, face_size):
    """Convert cube map faces to equirectangular projection."""
    # Cap face size to avoid memory issues (50000x25000 @ float32x3 = ~14GB)
    MAX_EQUIRECT_FACE = 8192  # produces 32768x16384 equirect (~1.6 Gpixel)
    actual_face_size = face_size
    if face_size > MAX_EQUIRECT_FACE:
        actual_face_size = MAX_EQUIRECT_FACE
        logger.info(f"  Capping face size from {face_size} to {actual_face_size} for equirectangular (memory limit)")

    out_w = actual_face_size * 4
    out_h = actual_face_size * 2

    logger.info(f"\nConverting to equirectangular {out_w}x{out_h}...")

    faces_np = {}
    for name, img in cube_faces.items():
        if img.size != (actual_face_size, actual_face_size):
            logger.debug(f"  Resizing {name} from {img.size} to ({actual_face_size},{actual_face_size})")
            img = img.resize((actual_face_size, actual_face_size), Image.LANCZOS)
        faces_np[name] = np.array(img, dtype=np.uint8)

    y_idx = np.arange(out_h, dtype=np.float32)
    x_idx = np.arange(out_w, dtype=np.float32)
    xx, yy = np.meshgrid(x_idx, y_idx)

    lat = ((0.5 - yy / out_h) * np.pi).astype(np.float32)
    lon = ((xx / out_w) * 2 * np.pi - np.pi).astype(np.float32)
    del xx, yy

    cx = np.cos(lat) * np.sin(lon)
    cy = np.sin(lat)
    cz = np.cos(lat) * np.cos(lon)

    ax, ay, az = np.abs(cx), np.abs(cy), np.abs(cz)

    equirect = np.zeros((out_h, out_w, 3), dtype=np.uint8)

    face_configs = [
        ('front',  (az >= ax) & (az >= ay) & (cz > 0)),
        ('back',   (az >= ax) & (az >= ay) & (cz <= 0)),
        ('right',  (ax >= ay) & (ax >= az) & (cx > 0)),
        ('left',   (ax >= ay) & (ax >= az) & (cx <= 0)),
        ('up',     (ay >= ax) & (ay >= az) & (cy > 0)),
        ('down',   (ay >= ax) & (ay >= az) & (cy <= 0)),
    ]

    for idx, (face, mask) in enumerate(face_configs):
        if face not in faces_np:
            continue

        logger.info(f"  Processing {face}... ({idx+1}/6)")

        pos = np.where(mask)
        lat_m = lat[mask]
        lon_m = lon[mask]

        cx_m = np.cos(lat_m) * np.sin(lon_m)
        cy_m = np.sin(lat_m)
        cz_m = np.cos(lat_m) * np.cos(lon_m)

        if face == 'front':
            u, v = cx_m / cz_m, cy_m / cz_m
        elif face == 'back':
            u, v = -cx_m / (-cz_m), cy_m / (-cz_m)
        elif face == 'right':
            u, v = -cz_m / cx_m, cy_m / cx_m
        elif face == 'left':
            u, v = cz_m / (-cx_m), cy_m / (-cx_m)
        elif face == 'up':
            u, v = cx_m / cy_m, -cz_m / cy_m
        else:  # down
            u, v = cx_m / (-cy_m), cz_m / (-cy_m)

        fs = actual_face_size
        px = np.clip(((u + 1) / 2 * (fs - 1)).astype(np.int32), 0, fs - 1)
        py = np.clip(((1 - v) / 2 * (fs - 1)).astype(np.int32), 0, fs - 1)

        equirect[pos[0], pos[1]] = faces_np[face][py, px]

    return Image.fromarray(equirect)


def verify_quality(equirect, slug):
    """Verify the equirectangular image has no stitching issues."""
    arr = np.array(equirect)
    h, w = arr.shape[:2]
    total_pixels = h * w
    issues = []

    black_pixels = np.sum(np.all(arr == 0, axis=2))
    black_percent = black_pixels / total_pixels * 100
    logger.info(f"  Black pixels: {black_pixels} ({black_percent:.4f}%)")

    if black_percent > 0.5:
        issues.append(f"High black pixel ratio: {black_percent:.2f}%")

    # Check for black rows/columns (seams)
    row_means = np.mean(arr, axis=(1, 2))
    black_rows = np.where(row_means < 5)[0]
    if len(black_rows) > 0:
        issues.append(f"Black rows at: {black_rows.tolist()}")
        logger.warning(f"  Black rows at: {black_rows.tolist()}")

    col_means = np.mean(arr, axis=(0, 2))
    black_cols = np.where(col_means < 5)[0]
    if len(black_cols) > 0:
        issues.append(f"Black columns at: {black_cols.tolist()}")
        logger.warning(f"  Black cols at: {black_cols.tolist()}")

    if not issues:
        logger.info("  PASS - No stitching issues detected")
    else:
        for issue in issues:
            logger.warning(f"  FAIL - {issue}")

    return issues


def save_image(img, path_without_ext, force_png=False):
    """Save image, using PNG for large dimensions or when forced, JPEG otherwise."""
    w, h = img.size
    MAX_JPEG_DIM = 65500

    if force_png or w > MAX_JPEG_DIM or h > MAX_JPEG_DIM:
        path = path_without_ext + ".png"
        img.save(path)
        logger.debug(f"  Saved as PNG: {path} ({w}x{h})")
    else:
        path = path_without_ext + ".jpg"
        img.save(path, quality=95)
        logger.debug(f"  Saved as JPEG: {path} ({w}x{h})")
    return path


def download_panorama(page_url, output_base=None):
    """Download a single panorama. Returns a result dict."""
    slug = page_url.rstrip('/').split('/')[-1]
    if output_base is None:
        output_base = SCRIPT_DIR
    output_dir = os.path.join(output_base, f"output-{slug}")

    result = {
        'url': page_url,
        'slug': slug,
        'status': 'FAIL',
        'error': None,
        'base_url': None,
        'level': None,
        'grid': None,
        'face_size': None,
        'resolution': None,
        'file_size_mb': None,
        'black_percent': None,
        'issues': [],
        'time_seconds': 0,
    }

    start_time = time.time()

    logger.info("=" * 70)
    logger.info(f"Downloading: {slug}")
    logger.info(f"URL: {page_url}")
    logger.info("=" * 70)

    session = requests.Session()

    try:
        # Step 1: Extract CDN base URL
        logger.info("\n[1] Extracting panorama CDN URL...")
        base_url = extract_base_url(page_url, session)
        result['base_url'] = base_url
        logger.info(f"    Base URL: {base_url}")

        # Step 2: Detect max level
        logger.info("\n[2] Detecting best quality level...")
        max_level = detect_max_level(base_url, session)
        result['level'] = max_level
        logger.info(f"    Max level: {max_level}")

        # Step 3: Detect grid size using front face
        logger.info(f"\n[3] Detecting tile grid at level {max_level}...")
        rows, cols = detect_grid_size(base_url, max_level, 'front', session)
        result['grid'] = f"{cols}x{rows}"
        logger.info(f"    Grid: {cols} cols x {rows} rows")

        if rows == 0 or cols == 0:
            raise ValueError(f"Grid detection failed: {cols}x{rows}")

        os.makedirs(output_dir, exist_ok=True)

        # Step 4: Download and stitch all faces
        logger.info(f"\n[4] Downloading all 6 faces at level {max_level}...")
        raw_faces = {}
        sizes = []

        for face in FACES:
            # Detect per-face grid size (can vary between faces)
            f_rows, f_cols = detect_grid_size(base_url, max_level, face, session)
            if f_rows == 0 or f_cols == 0:
                logger.warning(f"  Face '{face}' grid failed, using front grid ({cols}x{rows})")
                f_rows, f_cols = rows, cols

            face_img = download_and_stitch_face(base_url, face, max_level, f_rows, f_cols, session, output_dir)
            if face_img:
                raw_faces[face] = face_img
                sizes.append(face_img.size)
                save_image(face_img, os.path.join(output_dir, f"raw_{face}"))
            else:
                logger.error(f"  Failed to download face '{face}'")

        if len(raw_faces) != 6:
            raise ValueError(f"Only {len(raw_faces)}/6 faces downloaded")

        # Step 5: Normalize faces to square
        face_size = min(min(w, h) for w, h in sizes)
        result['face_size'] = face_size
        logger.info(f"\n[5] Normalizing faces to {face_size}x{face_size}...")

        cube_faces = {}
        for face, img in raw_faces.items():
            w, h = img.size
            if w != h:
                size = min(w, h)
                left = (w - size) // 2
                top = (h - size) // 2
                img = img.crop((left, top, left + size, top + size))
                logger.debug(f"  Cropped {face} from ({w},{h}) to ({size},{size})")

            if img.size[0] != face_size:
                img = img.resize((face_size, face_size), Image.LANCZOS)

            cube_faces[face] = img
            # Save individual faces as PNG (lossless)
            save_image(img, os.path.join(output_dir, f"face_{face}"), force_png=True)
            logger.info(f"  {face}: {img.size[0]}x{img.size[1]}")

        # Step 6: Save cube strip as PNG (lossless)
        logger.info("\n[6] Saving cube strip (PNG)...")
        strip = Image.new('RGB', (face_size * 6, face_size))
        for i, face in enumerate(['right', 'left', 'up', 'down', 'front', 'back']):
            strip.paste(cube_faces[face], (i * face_size, 0))
        save_image(strip, os.path.join(output_dir, "cube_strip"), force_png=True)

        # Step 7: Convert to equirectangular and save as PNG
        logger.info("\n[7] Generating equirectangular...")
        equirect = cube_to_equirectangular(cube_faces, face_size)

        equirect_path = save_image(equirect, os.path.join(output_dir, f"{slug}_equirectangular"), force_png=True)

        size_mb = os.path.getsize(equirect_path) / 1024 / 1024
        result['resolution'] = f"{equirect.size[0]}x{equirect.size[1]}"
        result['file_size_mb'] = round(size_mb, 2)

        logger.info(f"\n  File: {equirect_path}")
        logger.info(f"  Resolution: {equirect.size[0]}x{equirect.size[1]}")
        logger.info(f"  Size: {size_mb:.2f} MB")

        # Step 8: Quality verification
        logger.info("\n[8] Verifying quality...")
        arr = np.array(equirect)
        black_pixels = np.sum(np.all(arr == 0, axis=2))
        total_pixels = arr.shape[0] * arr.shape[1]
        result['black_percent'] = round(black_pixels / total_pixels * 100, 4)

        issues = verify_quality(equirect, slug)
        result['issues'] = issues

        if not issues:
            result['status'] = 'OK'
        else:
            result['status'] = 'WARN'

        # Step 9: Cleanup intermediate files to save disk space
        # Keep the final equirectangular AND cube_strip; delete tiles cache, raw_, face_
        logger.info("\n[9] Cleaning up intermediate files...")
        try:
            import shutil
            tiles_dir = os.path.join(output_dir, "tiles")
            if os.path.exists(tiles_dir):
                shutil.rmtree(tiles_dir, ignore_errors=True)
            for f in os.listdir(output_dir):
                if f.startswith(("raw_", "face_")):
                    try:
                        os.remove(os.path.join(output_dir, f))
                    except:
                        pass
            logger.info("  Cleanup done (kept equirectangular + cube_strip)")
        except Exception as e:
            logger.warning(f"  Cleanup failed: {e}")

    except Exception as e:
        result['error'] = str(e)
        result['status'] = 'FAIL'
        logger.error(f"\nERROR: {e}")
        import traceback
        logger.debug(traceback.format_exc())

    elapsed = time.time() - start_time
    result['time_seconds'] = round(elapsed, 1)
    logger.info(f"\nTime: {elapsed:.1f}s | Status: {result['status']}")
    logger.info("")

    return result


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python krpano_downloader.py <360cities_url>")
        print("  python krpano_downloader.py --batch <url1> <url2> ...")
        print("  python krpano_downloader.py --batch-file urls.txt")
        print("  python krpano_downloader.py --parallel 4 --batch-file urls.txt")
        print("  python krpano_downloader.py --parallel 4 --batch <url1> <url2> ...")
        sys.exit(1)

    urls = []
    parallel = 1
    args = sys.argv[1:]

    # Parse --parallel N
    if '--parallel' in args:
        idx = args.index('--parallel')
        parallel = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    if args[0] == '--batch':
        urls = args[1:]
    elif args[0] == '--batch-file':
        with open(args[1], 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    else:
        urls = [args[0]]

    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"Panoramas to download: {len(urls)}")
    if parallel > 1:
        logger.info(f"Parallel workers: {parallel}")
    logger.info("")

    results = []

    if parallel > 1 and len(urls) > 1:
        # Parallel download
        with ThreadPoolExecutor(max_workers=parallel) as executor:
            future_to_url = {}
            for url in urls:
                future = executor.submit(download_panorama, url)
                future_to_url[future] = url

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    results.append(result)
                    logger.info(f"=== Completed: {result['slug']} -> {result['status']} ===")
                except Exception as e:
                    slug = url.rstrip('/').split('/')[-1]
                    logger.error(f"=== EXCEPTION for {slug}: {e} ===")
                    results.append({
                        'url': url, 'slug': slug, 'status': 'FAIL',
                        'error': str(e), 'base_url': None, 'level': None,
                        'grid': None, 'face_size': None, 'resolution': None,
                        'file_size_mb': None, 'black_percent': None,
                        'issues': [], 'time_seconds': 0,
                    })
    else:
        # Sequential download
        for i, url in enumerate(urls):
            logger.info(f">>> [{i+1}/{len(urls)}] {url}")
            result = download_panorama(url)
            results.append(result)

    # Sort results by input order
    url_order = {url: i for i, url in enumerate(urls)}
    results.sort(key=lambda r: url_order.get(r['url'], 999))

    # Summary report
    if len(urls) > 1:
        logger.info("\n" + "=" * 70)
        logger.info("BATCH SUMMARY")
        logger.info("=" * 70)

        ok = sum(1 for r in results if r['status'] == 'OK')
        warn = sum(1 for r in results if r['status'] == 'WARN')
        fail = sum(1 for r in results if r['status'] == 'FAIL')

        logger.info(f"  Total: {len(results)} | OK: {ok} | WARN: {warn} | FAIL: {fail}\n")

        for r in results:
            icon = {'OK': '+', 'WARN': '!', 'FAIL': 'X'}[r['status']]
            line = f"  [{icon}] {r['slug']}"
            if r['resolution']:
                line += f" | {r['resolution']}"
            if r['level']:
                line += f" | L{r['level']}"
            if r['black_percent'] is not None:
                line += f" | black:{r['black_percent']}%"
            if r['error']:
                line += f" | ERROR: {r['error']}"
            if r['issues']:
                line += f" | issues: {r['issues']}"
            line += f" | {r['time_seconds']}s"
            logger.info(line)

    # Save results JSON
    results_path = os.path.join(LOG_DIR, f"results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(results_path, 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info(f"\nResults saved to: {results_path}")
    logger.info(f"Full log: {LOG_FILE}")


if __name__ == "__main__":
    main()
