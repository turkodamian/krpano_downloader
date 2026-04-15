"""
Resume script - rebuilds remaining URLs by scanning output directories
for completed equirectangular files, then launches parallel download.

Usage:
    python resume_download.py [--parallel N]
"""
import os
import sys
import glob

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def get_completed_slugs():
    """Scan output dirs for completed panoramas."""
    done = set()
    for d in glob.glob(os.path.join(SCRIPT_DIR, "output-*")):
        slug = os.path.basename(d).replace("output-", "")
        pngs = glob.glob(os.path.join(d, "*_equirectangular.png"))
        jpgs = glob.glob(os.path.join(d, "*_equirectangular.jpg"))
        if pngs or jpgs:
            done.add(slug)
    return done

def main():
    parallel = 6
    if "--parallel" in sys.argv:
        idx = sys.argv.index("--parallel")
        parallel = int(sys.argv[idx + 1])

    all_urls_path = os.path.join(SCRIPT_DIR, "all_urls.txt")
    if not os.path.exists(all_urls_path):
        print(f"ERROR: {all_urls_path} not found")
        sys.exit(1)

    with open(all_urls_path) as f:
        all_urls = [l.strip() for l in f if l.strip()]

    done = get_completed_slugs()
    remaining = [u for u in all_urls if u.rstrip("/").split("/")[-1] not in done]

    remaining_path = os.path.join(SCRIPT_DIR, "remaining_urls.txt")
    with open(remaining_path, "w") as f:
        for url in remaining:
            f.write(url + "\n")

    print(f"Total panoramas: {len(all_urls)}")
    print(f"Already completed: {len(done)}")
    print(f"Remaining: {len(remaining)}")
    print(f"Parallel workers: {parallel}")
    print(f"Remaining URLs saved to: {remaining_path}")
    print()

    if not remaining:
        print("All panoramas downloaded!")
        return

    # Launch the downloader
    import subprocess
    cmd = [
        sys.executable, os.path.join(SCRIPT_DIR, "krpano_downloader.py"),
        "--parallel", str(parallel),
        "--batch-file", remaining_path
    ]
    print(f"Launching: {' '.join(cmd)}")
    subprocess.run(cmd)

if __name__ == "__main__":
    main()
