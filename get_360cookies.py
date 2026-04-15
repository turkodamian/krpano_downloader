# -*- coding: utf-8 -*-
"""
Log in to 360cities.net and export cookies using your real Chrome browser
via Chrome DevTools Protocol (bypasses Cloudflare bot detection).

STEPS:
  1. Close ALL Chrome windows
  2. Run this script - it will launch Chrome with remote debugging
  3. Log in manually if needed, then the script probes video resolutions

Usage: python get_360cookies.py <email> <password> [output_cookies_file]
       python get_360cookies.py --probe-only   (skip login, just test with existing session)
"""

import sys
import os
import time
import subprocess
import json
import re

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')


def find_chrome():
    """Find Chrome executable on Windows."""
    paths = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for p in paths:
        if os.path.exists(p):
            return p
    return "chrome"


def main():
    probe_only = '--probe-only' in sys.argv

    if not probe_only and len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    email = sys.argv[1] if not probe_only else None
    password = sys.argv[2] if not probe_only else None
    output = "360cities_cookies.txt"
    for i, arg in enumerate(sys.argv):
        if arg not in ('--probe-only',) and i >= 3:
            output = arg
            break

    chrome_path = find_chrome()
    debug_port = 9222
    user_data = os.path.join(SCRIPT_DIR, "chrome_profile_360")

    print("="*60)
    print("360Cities Cookie Extractor & Resolution Prober")
    print("="*60)
    print()
    print("IMPORTANT: Close ALL other Chrome windows first!")
    print()

    # Launch Chrome with remote debugging and a dedicated profile
    print(f"Launching Chrome with remote debugging on port {debug_port}...")
    chrome_proc = subprocess.Popen([
        chrome_path,
        f"--remote-debugging-port={debug_port}",
        f"--user-data-dir={user_data}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank"
    ])
    time.sleep(3)

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            print("Connecting to Chrome via CDP...")
            browser = p.chromium.connect_over_cdp(f"http://localhost:{debug_port}")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()

            if not probe_only:
                # Navigate to login
                print(f"\nNavigating to login page...")
                page.goto("https://www.360cities.net/account/login", timeout=60000)

                # Wait for Cloudflare challenge to pass
                print("Waiting for Cloudflare verification...")
                for i in range(30):
                    time.sleep(2)
                    title = page.title()
                    if 'moment' not in title.lower() and 'verif' not in title.lower():
                        break
                    if i % 5 == 0:
                        print(f"  Still waiting... ({title})")

                print(f"Page title: {page.title()}")
                time.sleep(2)

                # Check if we're on the login page
                if page.locator('#user_email').count() > 0:
                    print("Filling login credentials...")
                    page.locator('#user_email').fill(email)
                    page.locator('#user_password').fill(password)
                    page.locator('input[type="submit"]').click()
                    time.sleep(5)

                    # Wait for Cloudflare again after login submit
                    for i in range(20):
                        time.sleep(2)
                        title = page.title()
                        url = page.url
                        if 'moment' not in title.lower() and '/account/login' not in url:
                            break

                    print(f"Post-login URL: {page.url}")
                else:
                    print("Login form not found - may already be logged in")

                # Check login status
                cookies = context.cookies()
                logged_in = next((c for c in cookies if c['name'] == 'logged_in'), None)
                if logged_in:
                    print(f"logged_in = {logged_in['value']}")
                    if logged_in['value'] == '1':
                        print("LOGIN SUCCESSFUL!")
                    else:
                        print("Login may have failed. Check the Chrome window.")
                        print("You can log in manually in the Chrome window,")
                        input("then press Enter here to continue...")
                else:
                    print("No login cookie found")
                    input("Log in manually in Chrome, then press Enter...")

            # Visit video page
            print("\nNavigating to video page...")
            page.goto("https://www.360cities.net/video/andean-amazon-rainforest", timeout=60000)

            # Wait for Cloudflare
            for i in range(30):
                time.sleep(2)
                title = page.title()
                if 'moment' not in title.lower() and 'verif' not in title.lower():
                    break

            print(f"Page: {page.title()}")
            time.sleep(3)

            # Export cookies
            cookies = context.cookies()
            print(f"\nExporting {len(cookies)} cookies...")

            with open(output, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# https://curl.se/docs/http-cookies.html\n\n")
                for c in cookies:
                    domain_flag = 'TRUE' if c['domain'].startswith('.') else 'FALSE'
                    secure = 'TRUE' if c.get('secure') else 'FALSE'
                    expires = str(int(c.get('expires', 0)))
                    prefix = '#HttpOnly_' if c.get('httpOnly', False) else ''
                    f.write(f"{prefix}{c['domain']}\t{domain_flag}\t{c['path']}\t{secure}\t{expires}\t{c['name']}\t{c['value']}\n")

            print(f"Cookies saved to: {output}")

            # Get the video XML to find the base URL pattern
            print("\nFetching video XML config...")
            xml_response = page.request.get("https://www.360cities.net/video/andean-amazon-rainforest.xml")
            xml_text = xml_response.text()

            if '<krpano' in xml_text:
                print("XML config loaded successfully")
                # Extract base video URL
                match = re.search(r"(https://video\.360cities\.net/[^'|\"]+)-\d+x\d+\.mp4", xml_text)
                if match:
                    base_url = match.group(1)
                    print(f"Video base: {base_url}")
                else:
                    print("Could not extract video base URL from XML")
                    base_url = None
            else:
                print(f"XML fetch failed (got {len(xml_text)} bytes, no <krpano>)")
                base_url = None

            if not base_url:
                # Fallback
                base_url = "https://video.360cities.net/rogergiraldolovera/02069529_bosque_andino_amazonico_8k"

            # First, visit the video CDN domain to get Cloudflare clearance
            print("\nClearing Cloudflare on video CDN domain...")
            # Open a known-good video URL to trigger Cloudflare challenge in the browser
            known_good = f"{base_url}-1024x512.mp4"
            cdn_page = context.new_page()
            cdn_page.goto(known_good, timeout=60000)

            # Wait for Cloudflare challenge to complete
            for i in range(30):
                time.sleep(2)
                title = cdn_page.title()
                url_now = cdn_page.url
                ct = ""
                try:
                    ct = cdn_page.evaluate("document.contentType") or ""
                except:
                    pass
                if 'video' in ct or 'octet' in ct:
                    print("  Cloudflare cleared - video accessible!")
                    break
                if 'moment' in title.lower() or 'verif' in title.lower():
                    if i % 5 == 0:
                        print(f"  Waiting for Cloudflare... ({title})")
                else:
                    # Might have passed
                    break

            cdn_page.close()
            time.sleep(1)

            # Re-export cookies (now includes cf_clearance for video.360cities.net)
            cookies = context.cookies()
            with open(output, 'w') as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# https://curl.se/docs/http-cookies.html\n\n")
                for c in cookies:
                    domain_flag = 'TRUE' if c['domain'].startswith('.') else 'FALSE'
                    secure = 'TRUE' if c.get('secure') else 'FALSE'
                    expires = str(int(c.get('expires', 0)))
                    prefix = '#HttpOnly_' if c.get('httpOnly', False) else ''
                    f.write(f"{prefix}{c['domain']}\t{domain_flag}\t{c['path']}\t{secure}\t{expires}\t{c['name']}\t{c['value']}\n")
            print(f"Updated cookies saved ({len(cookies)} cookies)")

            # Probe resolutions using JavaScript fetch() from the video page
            # This uses the browser's full cookie jar including Cloudflare clearance
            print("\n" + "="*60)
            print("PROBING ALL RESOLUTIONS via browser fetch()")
            print("="*60)

            resolutions = [
                "1024x512", "1344x672", "1920x960", "2048x1024",
                "2560x1280", "2880x1440", "3072x1536", "3200x1600",
                "3840x1920", "4096x2048", "4800x2400", "5120x2560",
                "5760x2880", "6144x3072", "7680x3840", "8192x4096",
                "10240x5120", "11520x5760",
            ]

            available = []
            for res in resolutions:
                url = f"{base_url}-{res}.mp4"
                try:
                    # Use JavaScript fetch with HEAD method from page context
                    result = page.evaluate(f"""
                        async () => {{
                            try {{
                                const r = await fetch("{url}", {{method: "HEAD", mode: "cors"}});
                                return {{
                                    status: r.status,
                                    contentLength: r.headers.get("content-length") || "",
                                    contentType: r.headers.get("content-type") || ""
                                }};
                            }} catch(e) {{
                                return {{status: 0, error: e.message, contentLength: "", contentType: ""}};
                            }}
                        }}
                    """)

                    status = result.get('status', 0)
                    content_length = result.get('contentLength', '')
                    content_type = result.get('contentType', '')
                    error = result.get('error', '')

                    if status == 200 and content_length:
                        size_mb = int(content_length) / (1024*1024)
                        print(f"  [+] {res}: AVAILABLE ({size_mb:.0f} MB)")
                        available.append({'res': res, 'url': url, 'size': int(content_length)})
                    elif status == 200:
                        print(f"  [+] {res}: AVAILABLE (size unknown)")
                        available.append({'res': res, 'url': url, 'size': 0})
                    elif status == 403:
                        print(f"  [-] {res}: DENIED")
                    elif status == 404:
                        print(f"  [ ] {res}: does not exist")
                    elif status == 0 and error:
                        # CORS error usually means the resource exists but cross-origin
                        print(f"  [?] {res}: CORS blocked ({error[:50]})")
                    else:
                        print(f"  [?] {res}: HTTP {status}")
                except Exception as e:
                    print(f"  [!] {res}: Error - {e}")

            print(f"\n{'='*60}")
            if available:
                best = max(available, key=lambda x: x['size'])
                print(f"BEST AVAILABLE: {best['res']} ({best['size']/(1024*1024):.0f} MB)")
                print(f"\nTo download the best quality:")
                print(f"  python krpano_video_downloader.py --cookies {output} <video_url>")
            else:
                print("No video files were directly accessible.")
                print("The CDN may require Cloudflare clearance cookies.")
                print("Try using --cookies with the exported cookie file.")

            # Also probe the audio
            m4a_match = re.search(r"(https://video\.360cities\.net/[^'|\"]+\.m4a)", xml_text if '<krpano' in xml_text else '')
            if m4a_match:
                print(f"\nAudio track: {m4a_match.group(1)}")

            # Don't close browser - leave Chrome open for user
            browser.contexts  # keep alive
            print("\nChrome window left open. Close it manually when done.")

    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Don't kill chrome - let user close it
        pass

    print("\nDone!")


if __name__ == '__main__':
    main()
