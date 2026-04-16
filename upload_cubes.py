"""Upload cube_strip.png files to Drive as {slug}_cube_strip.png in FOOTAGE/360Cities/cubes/"""
import os, sys, glob
sys.path.insert(0, "c:/Appz/krpanoDownloader-main")
from upload_to_drive import get_service, find_or_create_folder, file_exists_in_folder, upload_file
from googleapiclient.http import MediaFileUpload

BASE = "c:/Appz/krpanoDownloader-main"

def main():
    svc = get_service()
    footage = find_or_create_folder(svc, "FOOTAGE")
    cities = find_or_create_folder(svc, "360Cities", parent_id=footage)
    cubes = find_or_create_folder(svc, "cubes", parent_id=cities)
    print(f"Target: FOOTAGE/360Cities/cubes (id={cubes})")

    cube_files = sorted(glob.glob(os.path.join(BASE, "output-*", "cube_strip.png")))
    print(f"Found {len(cube_files)} cube_strip.png files")

    for i, path in enumerate(cube_files, 1):
        # Parent dir name: output-<slug>
        parent = os.path.basename(os.path.dirname(path))
        slug = parent[len("output-"):] if parent.startswith("output-") else parent
        target_name = f"{slug}_cube_strip.png"
        print(f"\n[{i}/{len(cube_files)}] {target_name}")
        if file_exists_in_folder(svc, target_name, cubes):
            print(f"  SKIP (exists)")
            continue
        size = os.path.getsize(path)
        media = MediaFileUpload(path, resumable=True, chunksize=10*1024*1024)
        metadata = {"name": target_name, "parents": [cubes]}
        req = svc.files().create(body=metadata, media_body=media, fields="id")
        resp = None
        while resp is None:
            s, resp = req.next_chunk()
            if s:
                print(f"  Uploading {target_name}: {int(s.progress()*100)}%", end="\r")
        print(f"  UPLOADED: {target_name} ({size/1024/1024:.1f} MB)")

if __name__ == "__main__":
    main()
