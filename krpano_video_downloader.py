# -*- coding: utf-8 -*-
"""
krpano 360cities.net video downloader.
Downloads 360 videos at the highest available quality from krpano tours.
Automatically merges separate video and audio tracks using ffmpeg.

The CDN requires a session cookie from visiting the page first.
Higher resolutions (4K/8K) are ACL-restricted on S3 and require a
--cookies flag pointing to a browser-exported cookies file (Netscape format)
from a logged-in session with a licensing account.

Usage:
    python krpano_video_downloader.py <360cities_video_url>
    python krpano_video_downloader.py --cookies cookies.txt <url>
    python krpano_video_downloader.py --batch <url1> <url2> ...
    python krpano_video_downloader.py --batch-file urls.txt
"""

import os
import sys
import re
import logging
import time
import json
import subprocess
import tempfile
from datetime import datetime

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(SCRIPT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, f"krpano_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

logger = logging.getLogger("krpano_video")
logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(LOG_FILE, encoding='utf-8')
fh.setLevel(logging.DEBUG)
fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
logger.addHandler(fh)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter('%(message)s'))
logger.addHandler(ch)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CURL_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'

# Resolutions to probe (ascending), covering 2K through 12K equirectangular
PROBE_RESOLUTIONS = [
    (2560, 1280), (2880, 1440),
    (3072, 1536), (3200, 1600),
    (3840, 1920), (4096, 2048),
    (4800, 2400), (5120, 2560),
    (5760, 2880), (6144, 3072),
    (7680, 3840), (8192, 4096),
    (10240, 5120), (11520, 5760),
]


# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

class Session:
    """Manages curl cookies for 360cities.net requests."""

    def __init__(self, cookies_file=None):
        self.user_cookies = cookies_file
        self._temp_cookie = None
        self._session_cookie = None

    @property
    def cookie_file(self):
        if self.user_cookies:
            return self.user_cookies
        if self._session_cookie:
            return self._session_cookie
        return None

    def init_session(self, page_url):
        """Visit the page to obtain a session cookie from 360cities."""
        if self.user_cookies:
            logger.info("Using provided cookies file")
            return

        logger.debug("Initializing session cookie...")
        self._temp_cookie = tempfile.NamedTemporaryFile(
            mode='w', suffix='.txt', prefix='360cookies_', delete=False
        )
        self._temp_cookie.close()
        self._session_cookie = self._temp_cookie.name

        try:
            subprocess.run(
                ['curl', '-s', '-L',
                 '-c', self._session_cookie,
                 '-H', f'User-Agent: {CURL_UA}',
                 '-H', 'Accept: text/html,application/xhtml+xml',
                 '-o', '/dev/null' if os.name != 'nt' else 'NUL',
                 page_url],
                capture_output=True, timeout=30
            )
            logger.debug(f"Session cookie saved to {self._session_cookie}")
        except Exception as e:
            logger.warning(f"Failed to init session: {e}")

    def curl_args(self):
        """Return cookie-related curl arguments."""
        args = []
        cf = self.cookie_file
        if cf:
            args.extend(['-b', cf])
        return args

    def cleanup(self):
        if self._session_cookie and os.path.exists(self._session_cookie):
            try:
                os.unlink(self._session_cookie)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def curl_fetch(url, session=None, binary=False):
    """Fetch a URL using curl (360cities blocks python requests)."""
    logger.debug(f"curl fetch: {url}")
    cmd = [
        'curl', '-s', '-L',
        '-H', f'User-Agent: {CURL_UA}',
        '-H', 'Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        '-H', 'Referer: https://www.360cities.net/',
    ]
    if session:
        cmd.extend(session.curl_args())
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=30)
        if binary:
            return result.stdout
        return result.stdout.decode('utf-8', errors='ignore')
    except Exception as e:
        raise ValueError(f"Failed to fetch {url}: {e}")


def curl_head_status(url, session=None):
    """Get HTTP status code for a URL without downloading the body."""
    cmd = [
        'curl', '-s', '-o', '/dev/null' if os.name != 'nt' else 'NUL',
        '-w', '%{http_code}',
        '-H', f'User-Agent: {CURL_UA}',
        '-H', 'Referer: https://www.360cities.net/',
    ]
    if session:
        cmd.extend(session.curl_args())
    cmd.append(url)

    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        return result.stdout.decode().strip()
    except Exception:
        return '000'


def extract_slug(page_url):
    """Extract the video slug from a 360cities URL."""
    match = re.search(r'360cities\.net/video/([^/?#]+)', page_url)
    if match:
        return match.group(1)
    raise ValueError(f"Could not extract video slug from: {page_url}")


def check_ffmpeg():
    """Check if ffmpeg is available."""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, timeout=10)
        return result.returncode == 0
    except FileNotFoundError:
        return False


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def fetch_video_xml(page_url, slug, session):
    """Fetch and parse the krpano XML config for a video."""
    xml_url = f"https://www.360cities.net/video/{slug}.xml"
    xml_text = curl_fetch(xml_url, session)

    if not xml_text or len(xml_text) < 50 or '<krpano' not in xml_text:
        logger.debug("Direct XML fetch failed, trying page extraction...")
        html = curl_fetch(page_url, session)
        match = re.search(r'xml:\s*["\']([^"\']+\.xml[^"\']*)["\']', html)
        if match:
            xml_path = match.group(1)
            if xml_path.startswith('/'):
                xml_url = f"https://www.360cities.net{xml_path}"
            else:
                xml_url = xml_path
            xml_text = curl_fetch(xml_url, session)
        else:
            raise ValueError(f"Could not find video XML config for {page_url}")

    if '<krpano' not in xml_text:
        raise ValueError(f"Invalid XML response from {xml_url}")

    logger.debug(f"XML config fetched ({len(xml_text)} bytes)")
    logger.debug(f"XML content:\n{xml_text[:3000]}")
    return xml_text


def extract_video_base_url(mp4_url):
    """Extract base URL and extension from a video URL like ...name-1920x960.mp4"""
    match = re.match(r'(.*?)-\d+x\d+\.(mp4|webm)$', mp4_url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def probe_all_resolutions(base_url, ext, m4a_url, session):
    """
    Probe for ALL available resolutions on the CDN.
    Uses session cookies which are required for CDN access.
    The CDN sits behind Cloudflare - without valid cookies, all requests
    get a Cloudflare challenge page (403). With cookies, accessible files
    return 200 and restricted ones return a proper S3 403 (small XML body).
    Returns list of available source dicts.
    """
    found = []

    for w, h in PROBE_RESOLUTIONS:
        probe_url = f"{base_url}-{w}x{h}.{ext}"
        code = curl_head_status(probe_url, session)

        if code == '200':
            logger.info(f"  [+] {w}x{h} - AVAILABLE")
            found.append({
                'label': f'{w}x{h}',
                'width': w,
                'height': h,
                'mp4': probe_url if ext == 'mp4' else f"{base_url}-{w}x{h}.mp4",
                'webm': f"{base_url}-{w}x{h}.webm",
                'm4a': m4a_url,
            })
        elif code == '403':
            # 403 can mean: Cloudflare challenge (no cookies), S3 ACL denied,
            # or file doesn't exist (S3 returns 403 for non-existent objects
            # when ListBucket is not granted). We can't distinguish these cases
            # without passing the Cloudflare challenge first.
            logger.debug(f"  [?] {w}x{h} - denied (may or may not exist)")
        else:
            logger.debug(f"  [-] {w}x{h} - HTTP {code}")

    return found


def parse_video_sources(xml_text):
    """
    Parse video source URLs and metadata from the krpano XML.
    Returns: list of dicts with keys: label, width, height, mp4, webm, m4a
    """
    sources = []

    pattern = re.compile(
        r"videointerface_addsource\(\s*'([^']+)'\s*,\s*'([^']+)'"
    )

    for match in pattern.finditer(xml_text):
        label = match.group(1)
        urls_str = match.group(2)

        parts = urls_str.split('|')
        mp4_url = parts[0] if len(parts) > 0 else None
        webm_url = parts[1] if len(parts) > 1 else None
        m4a_url = parts[2] if len(parts) > 2 else None

        width, height = 0, 0
        res_match = re.search(r'(\d{3,5})x(\d{3,5})', label)
        if res_match:
            width, height = int(res_match.group(1)), int(res_match.group(2))
        elif mp4_url:
            res_match = re.search(r'(\d{3,5})x(\d{3,5})', mp4_url)
            if res_match:
                width, height = int(res_match.group(1)), int(res_match.group(2))

        source = {
            'label': label,
            'width': width,
            'height': height,
            'mp4': mp4_url,
            'webm': webm_url,
            'm4a': m4a_url,
        }
        sources.append(source)
        logger.debug(f"Found source: {label} ({width}x{height})")

    if not sources:
        video_urls = re.findall(
            r'(https?://video\.360cities\.net/[^\s"\'<>|]+\.mp4)',
            xml_text
        )
        m4a_urls = re.findall(
            r'(https?://video\.360cities\.net/[^\s"\'<>|]+\.m4a)',
            xml_text
        )
        m4a_url = m4a_urls[0] if m4a_urls else None

        for url in video_urls:
            res_match = re.search(r'(\d{3,5})x(\d{3,5})', url)
            width, height = 0, 0
            if res_match:
                width, height = int(res_match.group(1)), int(res_match.group(2))
            sources.append({
                'label': f"{width}x{height}" if width else os.path.basename(url),
                'width': width,
                'height': height,
                'mp4': url,
                'webm': None,
                'm4a': m4a_url,
            })

    if not sources:
        raise ValueError("No video sources found in XML config")

    # Deduplicate by resolution (iOS and non-iOS blocks produce duplicates)
    seen = set()
    unique = []
    for s in sources:
        key = f"{s['width']}x{s['height']}"
        if key not in seen:
            seen.add(key)
            unique.append(s)
    sources = unique

    return sources


def parse_metadata(xml_text):
    """Extract metadata (title, author, description) from the XML."""
    metadata = {}

    meta_match = re.search(r'<data\s+name="metadata"[^>]*>\s*<!\[CDATA\[(.*?)\]\]>', xml_text, re.DOTALL)
    if meta_match:
        try:
            meta_json = json.loads(meta_match.group(1))
            metadata['title'] = meta_json.get('title', '')
            metadata['author'] = meta_json.get('author', {}).get('display_name', '')
            metadata['description'] = meta_json.get('description', '')
            metadata['id'] = meta_json.get('id', '')
            logger.debug(f"Metadata: title={metadata.get('title')}, author={metadata.get('author')}")
        except json.JSONDecodeError:
            logger.debug("Failed to parse metadata JSON")

    return metadata


def select_best_source(sources):
    """Select the highest resolution accessible source."""
    if not sources:
        return None

    # Filter to accessible (non-restricted) sources
    accessible = [s for s in sources if not s.get('restricted')]
    if accessible:
        best = max(accessible, key=lambda s: s['width'] * s['height'])
    else:
        best = max(sources, key=lambda s: s['width'] * s['height'])

    logger.info(f"Best quality: {best['label']} ({best['width']}x{best['height']})")
    return best


def download_file(url, output_path, session, label="file"):
    """Download a file using curl with progress indication."""
    if not url:
        return False

    if os.path.exists(output_path):
        size = os.path.getsize(output_path)
        if size > 1000:
            logger.info(f"  {label} already downloaded ({size:,} bytes), skipping")
            return True
        else:
            os.remove(output_path)

    logger.info(f"  Downloading {label}...")
    logger.debug(f"  URL: {url}")
    logger.debug(f"  Output: {output_path}")

    cmd = [
        'curl', '-L', '-#',
        '-H', f'User-Agent: {CURL_UA}',
        '-H', 'Referer: https://www.360cities.net/',
    ]
    if session:
        cmd.extend(session.curl_args())
    cmd.extend(['-o', output_path, url])

    try:
        result = subprocess.run(cmd, capture_output=False, timeout=1800)
        if result.returncode != 0:
            logger.error(f"  curl failed with return code {result.returncode}")
            return False

        if os.path.exists(output_path):
            size = os.path.getsize(output_path)
            if size > 1000:
                logger.info(f"  {label} downloaded ({size:,} bytes)")
                return True
            else:
                # Probably an error page, not a video
                os.remove(output_path)
                logger.error(f"  Downloaded file too small ({size} bytes) - access denied?")
                return False
        return False

    except subprocess.TimeoutExpired:
        logger.error(f"  Download timed out")
        return False
    except Exception as e:
        logger.error(f"  Download failed: {e}")
        return False


def merge_video_audio(video_path, audio_path, output_path):
    """Merge video and audio tracks using ffmpeg."""
    logger.info("  Merging video + audio with ffmpeg...")
    try:
        result = subprocess.run(
            ['ffmpeg', '-y',
             '-i', video_path,
             '-i', audio_path,
             '-c', 'copy',
             '-map', '0:v:0',
             '-map', '1:a:0',
             output_path],
            capture_output=True, timeout=600
        )
        if result.returncode == 0 and os.path.exists(output_path):
            size = os.path.getsize(output_path)
            logger.info(f"  Merged output: {size:,} bytes")
            return True
        else:
            stderr = result.stderr.decode('utf-8', errors='ignore')
            logger.error(f"  ffmpeg merge failed: {stderr[-500:]}")
            return False
    except Exception as e:
        logger.error(f"  ffmpeg merge failed: {e}")
        return False


# ---------------------------------------------------------------------------
# Main download function
# ---------------------------------------------------------------------------

def download_video(page_url, session):
    """Download a 360 video from a 360cities.net URL."""
    start_time = time.time()
    slug = extract_slug(page_url)
    logger.info(f"{'='*60}")
    logger.info(f"Video: {slug}")
    logger.info(f"URL:   {page_url}")
    logger.info(f"{'='*60}")

    has_ffmpeg = check_ffmpeg()
    if not has_ffmpeg:
        logger.warning("ffmpeg not found - video and audio will be saved separately")
        logger.warning("Install ffmpeg to automatically merge video+audio")

    # Initialize session (get cookies)
    session.init_session(page_url)

    # Create output directory
    out_dir = os.path.join(SCRIPT_DIR, f"output-video-{slug}")
    os.makedirs(out_dir, exist_ok=True)

    # Fetch and parse XML config
    xml_text = fetch_video_xml(page_url, slug, session)
    sources = parse_video_sources(xml_text)
    metadata = parse_metadata(xml_text)

    logger.info(f"Found {len(sources)} quality level(s) in XML:")
    for s in sorted(sources, key=lambda x: x['width'] * x['height']):
        logger.info(f"  - {s['label']}")

    # Probe for ALL resolutions on CDN (including restricted ones)
    best_listed = max(sources, key=lambda s: s['width'] * s['height'])
    m4a_url = best_listed.get('m4a')
    mp4_url = best_listed.get('mp4')

    if mp4_url:
        base_url, ext = extract_video_base_url(mp4_url)
        if base_url:
            logger.info("")
            logger.info("Probing CDN for all available resolutions...")
            probed = probe_all_resolutions(base_url, ext, m4a_url, session)

            # Add newly discovered sources
            existing_res = {f"{s['width']}x{s['height']}" for s in sources}
            for p in probed:
                key = f"{p['width']}x{p['height']}"
                if key not in existing_res:
                    sources.append(p)
                    existing_res.add(key)

    # Report what we found
    accessible = [s for s in sources if not s.get('restricted')]

    if not accessible:
        accessible = sources

    logger.info("")

    # Select best accessible quality
    best = select_best_source(sources)
    if not best:
        raise ValueError("No valid video sources found")

    if best.get('restricted'):
        logger.error(f"Best resolution {best['label']} requires licensed cookies!")
        logger.error(f"Falling back to best accessible resolution...")
        accessible_best = max(accessible, key=lambda s: s['width'] * s['height']) if accessible else None
        if accessible_best:
            best = accessible_best
            logger.info(f"Using: {best['label']} ({best['width']}x{best['height']})")
        else:
            raise ValueError("No accessible video sources found. Use --cookies flag.")

    # Save metadata
    meta_file = os.path.join(out_dir, "metadata.json")
    with open(meta_file, 'w', encoding='utf-8') as f:
        json.dump({
            'url': page_url,
            'slug': slug,
            'metadata': metadata,
            'selected_quality': best['label'],
            'resolution': f"{best['width']}x{best['height']}",
            'all_sources': sources,
            'download_date': datetime.now().isoformat(),
        }, f, indent=2, ensure_ascii=False)

    # Download video (prefer MP4)
    video_ext = 'mp4'
    video_url = best.get('mp4')
    if not video_url:
        video_url = best.get('webm')
        video_ext = 'webm'

    if not video_url:
        raise ValueError("No video URL found in best source")

    video_file = os.path.join(out_dir, f"{slug}_video.{video_ext}")
    video_ok = download_file(video_url, video_file, session, f"video ({best['label']})")

    if not video_ok:
        raise ValueError(f"Failed to download video from {video_url}")

    # Download audio track
    audio_url = best.get('m4a')
    audio_file = None
    audio_ok = False

    if audio_url:
        audio_file = os.path.join(out_dir, f"{slug}_audio.m4a")
        audio_ok = download_file(audio_url, audio_file, session, "audio")

    # Merge video + audio if both available and ffmpeg exists
    final_file = None
    if video_ok and audio_ok and has_ffmpeg:
        final_file = os.path.join(out_dir, f"{slug}_{best['width']}x{best['height']}.{video_ext}")
        if os.path.exists(final_file) and os.path.getsize(final_file) > 1000:
            logger.info(f"  Merged file already exists, skipping merge")
        else:
            merge_ok = merge_video_audio(video_file, audio_file, final_file)
            if merge_ok:
                logger.debug("  Merge successful, keeping separate tracks as backup")
            else:
                final_file = video_file
                logger.warning("  Merge failed, keeping separate video and audio files")
    elif video_ok and not audio_ok:
        final_file = os.path.join(out_dir, f"{slug}_{best['width']}x{best['height']}.{video_ext}")
        if not os.path.exists(final_file):
            os.rename(video_file, final_file)
        logger.info("  No audio track available - video saved without audio")
    elif video_ok and audio_ok and not has_ffmpeg:
        final_file = video_file
        logger.info("  Video and audio saved separately (install ffmpeg to merge)")
    else:
        final_file = video_file

    elapsed = time.time() - start_time

    logger.info(f"")
    logger.info(f"--- Download complete ---")
    if metadata.get('title'):
        logger.info(f"  Title:      {metadata['title']}")
    if metadata.get('author'):
        logger.info(f"  Author:     {metadata['author']}")
    logger.info(f"  Resolution: {best['width']}x{best['height']}")
    logger.info(f"  Output:     {out_dir}")
    if final_file and os.path.exists(final_file):
        logger.info(f"  File:       {os.path.basename(final_file)} ({os.path.getsize(final_file):,} bytes)")
    logger.info(f"  Time:       {elapsed:.1f}s")
    logger.info(f"")

    return {
        'status': 'ok',
        'slug': slug,
        'resolution': f"{best['width']}x{best['height']}",
        'output_dir': out_dir,
        'final_file': final_file,
        'elapsed': elapsed,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # Parse --cookies flag
    cookies_file = None
    args = sys.argv[1:]
    if '--cookies' in args:
        idx = args.index('--cookies')
        if idx + 1 < len(args):
            cookies_file = args[idx + 1]
            if not os.path.exists(cookies_file):
                print(f"Cookies file not found: {cookies_file}")
                sys.exit(1)
            args = args[:idx] + args[idx+2:]
        else:
            print("--cookies requires a file path argument")
            sys.exit(1)

    session = Session(cookies_file)

    urls = []

    if not args:
        print(__doc__)
        sys.exit(1)

    if args[0] == '--batch-file':
        if len(args) < 2:
            print("Usage: python krpano_video_downloader.py --batch-file urls.txt")
            sys.exit(1)
        filepath = args[1]
        if not os.path.exists(filepath):
            print(f"File not found: {filepath}")
            sys.exit(1)
        with open(filepath, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

    elif args[0] == '--batch':
        urls = [u for u in args[1:] if u.strip()]

    else:
        urls = [args[0]]

    if not urls:
        print("No URLs provided")
        sys.exit(1)

    results = []
    for i, url in enumerate(urls, 1):
        if '/video/' not in url:
            logger.warning(f"Skipping non-video URL: {url}")
            logger.warning(f"  (expected format: https://www.360cities.net/video/...)")
            results.append({'url': url, 'status': 'skipped', 'reason': 'not a video URL'})
            continue

        logger.info(f"[{i}/{len(urls)}] Processing: {url}")
        try:
            result = download_video(url, session)
            result['url'] = url
            results.append(result)
        except Exception as e:
            logger.error(f"FAILED: {e}")
            logger.debug(f"Exception details:", exc_info=True)
            results.append({'url': url, 'status': 'error', 'error': str(e)})

    # Summary for batch
    if len(urls) > 1:
        logger.info(f"\n{'='*60}")
        logger.info(f"BATCH SUMMARY: {len(urls)} video(s)")
        ok = sum(1 for r in results if r.get('status') == 'ok')
        fail = sum(1 for r in results if r.get('status') == 'error')
        skip = sum(1 for r in results if r.get('status') == 'skipped')
        logger.info(f"  Success: {ok}  Failed: {fail}  Skipped: {skip}")

        results_file = os.path.join(SCRIPT_DIR, f"video_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info(f"  Results: {results_file}")

    session.cleanup()


if __name__ == '__main__':
    main()
