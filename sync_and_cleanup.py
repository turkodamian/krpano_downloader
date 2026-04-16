"""Compare local files with Drive, delete verified uploads, maintain registry.

Registry format: CSV with slug, file_type, local_size, drive_size, drive_id, verified_at
Saves to: downloaded_uploaded_registry.csv
"""
import os, sys, csv, time, glob
sys.path.insert(0, "c:/Appz/krpanoDownloader-main")

# Requires GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET env vars

from upload_to_drive import get_service, find_or_create_folder

BASE = "c:/Appz/krpanoDownloader-main"
REGISTRY = os.path.join(BASE, "downloaded_uploaded_registry.csv")

def list_drive_folder(svc, folder_id):
    """List ALL files in a Drive folder (paginated)."""
    files = {}
    page_token = None
    while True:
        resp = svc.files().list(
            q=f"'{folder_id}' in parents and trashed=false",
            fields="nextPageToken, files(id, name, size)",
            pageSize=1000,
            pageToken=page_token
        ).execute()
        for f in resp.get("files", []):
            files[f["name"]] = {"id": f["id"], "size": int(f.get("size", 0))}
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files

def main():
    svc = get_service()
    footage = find_or_create_folder(svc, "FOOTAGE")
    cities = find_or_create_folder(svc, "360Cities", parent_id=footage)
    cubes_folder = find_or_create_folder(svc, "cubes", parent_id=cities)

    print("Listing Drive files...")
    drive_equirects = list_drive_folder(svc, cities)
    drive_cubes = list_drive_folder(svc, cubes_folder)
    print(f"  Drive equirects: {len(drive_equirects)}")
    print(f"  Drive cubes: {len(drive_cubes)}")

    # Load existing registry (to preserve history)
    existing_registry = {}
    if os.path.exists(REGISTRY):
        with open(REGISTRY, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                key = (row["slug"], row["file_type"])
                existing_registry[key] = row

    # Scan local output dirs
    output_dirs = sorted(glob.glob(os.path.join(BASE, "output-*")))
    print(f"  Local output dirs: {len(output_dirs)}")

    to_delete = []
    registry_updates = []
    skipped_size_mismatch = 0
    skipped_not_on_drive = 0
    already_clean = 0

    for d in output_dirs:
        slug = os.path.basename(d)
        if slug.startswith("output-"):
            slug = slug[len("output-"):]

        # Check equirectangular
        equi_name = f"{slug}_equirectangular.png"
        equi_local = os.path.join(d, equi_name)
        if os.path.exists(equi_local):
            local_size = os.path.getsize(equi_local)
            if equi_name in drive_equirects:
                drive_info = drive_equirects[equi_name]
                if local_size == drive_info["size"]:
                    to_delete.append(equi_local)
                    registry_updates.append({
                        "slug": slug, "file_type": "equirectangular",
                        "local_size": local_size, "drive_size": drive_info["size"],
                        "drive_id": drive_info["id"], "verified_at": int(time.time())
                    })
                else:
                    skipped_size_mismatch += 1
            else:
                skipped_not_on_drive += 1

        # Check cube_strip
        cube_local = os.path.join(d, "cube_strip.png")
        cube_drive_name = f"{slug}_cube_strip.png"
        if os.path.exists(cube_local):
            local_size = os.path.getsize(cube_local)
            if cube_drive_name in drive_cubes:
                drive_info = drive_cubes[cube_drive_name]
                if local_size == drive_info["size"]:
                    to_delete.append(cube_local)
                    registry_updates.append({
                        "slug": slug, "file_type": "cube_strip",
                        "local_size": local_size, "drive_size": drive_info["size"],
                        "drive_id": drive_info["id"], "verified_at": int(time.time())
                    })
                else:
                    skipped_size_mismatch += 1
            else:
                skipped_not_on_drive += 1

    total_bytes = sum(os.path.getsize(f) for f in to_delete)
    print(f"\n=== CLEANUP SUMMARY ===")
    print(f"  Files verified (size match): {len(to_delete)}")
    print(f"  Total space to free: {total_bytes/1024/1024/1024:.2f} GB")
    print(f"  Skipped (size mismatch): {skipped_size_mismatch}")
    print(f"  Skipped (not on Drive): {skipped_not_on_drive}")

    # Delete verified files
    deleted = 0
    for f in to_delete:
        try:
            os.remove(f)
            deleted += 1
        except Exception as e:
            print(f"  ERR deleting {f}: {e}")
    print(f"  Deleted: {deleted}")

    # Remove empty output dirs
    empty_removed = 0
    for d in output_dirs:
        try:
            remaining_files = os.listdir(d)
            if not remaining_files:
                os.rmdir(d)
                empty_removed += 1
        except Exception:
            pass
    print(f"  Empty dirs removed: {empty_removed}")

    # Update registry
    for update in registry_updates:
        key = (update["slug"], update["file_type"])
        existing_registry[key] = update

    # Write registry
    fieldnames = ["slug", "file_type", "local_size", "drive_size", "drive_id", "verified_at"]
    with open(REGISTRY, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(existing_registry.keys()):
            writer.writerow(existing_registry[key])
    print(f"\n  Registry: {len(existing_registry)} entries saved to {REGISTRY}")

    # Final disk check
    import shutil
    free = shutil.disk_usage("C:/").free / 1024 / 1024 / 1024
    print(f"  Disk free now: {free:.1f} GB")

if __name__ == "__main__":
    main()
