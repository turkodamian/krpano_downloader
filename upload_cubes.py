"""Upload cube_strip.png files to Drive as {slug}_cube_strip.png in FOOTAGE/360Cities/cubes/
Usage: python upload_cubes.py [--parallel N]
"""
import os, sys, glob
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
sys.path.insert(0, "c:/Appz/krpanoDownloader-main")
from upload_to_drive import get_service, find_or_create_folder, file_exists_in_folder
from googleapiclient.http import MediaFileUpload

BASE = "c:/Appz/krpanoDownloader-main"

def upload_one(svc, path, folder_id, lock):
    parent = os.path.basename(os.path.dirname(path))
    slug = parent[len("output-"):] if parent.startswith("output-") else parent
    target = f"{slug}_cube_strip.png"
    # Check exists (thread-safe via API call itself)
    if file_exists_in_folder(svc, target, folder_id):
        with lock:
            print(f"  SKIP: {target}")
        return "skip"
    size = os.path.getsize(path)
    media = MediaFileUpload(path, resumable=True, chunksize=10*1024*1024)
    metadata = {"name": target, "parents": [folder_id]}
    req = svc.files().create(body=metadata, media_body=media, fields="id")
    resp = None
    while resp is None:
        _, resp = req.next_chunk()
    with lock:
        print(f"  UPLOADED: {target} ({size/1024/1024:.1f} MB)")
    return "ok"

def main():
    parallel = 1
    if "--parallel" in sys.argv:
        parallel = int(sys.argv[sys.argv.index("--parallel") + 1])
    svc = get_service()
    footage = find_or_create_folder(svc, "FOOTAGE")
    cities = find_or_create_folder(svc, "360Cities", parent_id=footage)
    cubes = find_or_create_folder(svc, "cubes", parent_id=cities)
    print(f"Target: FOOTAGE/360Cities/cubes (id={cubes}) | Workers: {parallel}")

    files = sorted(glob.glob(os.path.join(BASE, "output-*", "cube_strip.png")))
    print(f"Found {len(files)} cube_strip.png files")

    lock = Lock()
    counter = {"ok": 0, "skip": 0, "err": 0}
    with ThreadPoolExecutor(max_workers=parallel) as ex:
        # Each worker needs its own service (googleapi clients aren't thread-safe)
        def task(p):
            s = get_service()
            try:
                return upload_one(s, p, cubes, lock)
            except Exception as e:
                with lock:
                    print(f"  ERR {os.path.basename(os.path.dirname(p))}: {str(e)[:100]}")
                return "err"
        futs = [ex.submit(task, p) for p in files]
        for i, fut in enumerate(as_completed(futs), 1):
            r = fut.result()
            counter[r] += 1
            if i % 20 == 0:
                with lock:
                    print(f"  [{i}/{len(files)}] ok={counter['ok']} skip={counter['skip']} err={counter['err']}")
    print(f"\nDone: ok={counter['ok']} skip={counter['skip']} err={counter['err']}")

if __name__ == "__main__":
    main()
