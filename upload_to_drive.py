"""
Upload all equirectangular PNGs to Google Drive.
Creates FOOTAGE/360Cities/ folder structure and uploads in parallel.

Usage:
    python upload_to_drive.py [--parallel N] [--account EMAIL]
"""
import os
import sys
import glob
import time
import json
import asyncio
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# Add R360AI MCP server path for google drive module
sys.path.insert(0, "C:/Appz/R360AI_VS/mcp_servers/google_drive")

# We'll use the Google Drive API directly with the stored credentials
from pathlib import Path

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ACCOUNT = "damian@realidad360.com.ar"
CRED_DIR = Path.home() / ".google_workspace_mcp" / "credentials"
CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")

def get_service():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    cred_file = CRED_DIR / f"{ACCOUNT}.json"
    data = json.loads(cred_file.read_text())

    creds = Credentials(
        token=data.get("token"),
        refresh_token=data.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=data.get("scopes", []),
    )

    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        creds.refresh(Request())
        data["token"] = creds.token
        cred_file.write_text(json.dumps(data, indent=2))

    return build("drive", "v3", credentials=creds)

def find_or_create_folder(service, name, parent_id="root"):
    """Find existing folder or create new one."""
    query = f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = service.files().list(q=query, fields="files(id,name)", spaces="drive").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]

def file_exists_in_folder(service, name, folder_id):
    """Check if file already exists in folder."""
    query = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    results = service.files().list(q=query, fields="files(id,name)", spaces="drive").execute()
    return len(results.get("files", [])) > 0

def upload_file(service, local_path, folder_id):
    """Upload a file to a specific Drive folder."""
    from googleapiclient.http import MediaFileUpload

    filename = os.path.basename(local_path)
    file_size = os.path.getsize(local_path)

    # Check if already uploaded
    if file_exists_in_folder(service, filename, folder_id):
        print(f"  SKIP (exists): {filename}")
        return {"status": "skipped", "name": filename}

    metadata = {"name": filename, "parents": [folder_id]}
    media = MediaFileUpload(local_path, mimetype="image/png", resumable=True, chunksize=10*1024*1024)

    request = service.files().create(body=metadata, media_body=media, fields="id,name,size")

    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  Uploading {filename}: {pct}%", end="\r")

    size_mb = file_size / 1024 / 1024
    print(f"  UPLOADED: {filename} ({size_mb:.1f} MB)")
    return {"status": "uploaded", "name": filename, "id": response["id"], "size_mb": round(size_mb, 1)}


def main():
    parallel = 2  # conservative for uploads
    for i, arg in enumerate(sys.argv):
        if arg == "--parallel" and i + 1 < len(sys.argv):
            parallel = int(sys.argv[i + 1])
        if arg == "--account" and i + 1 < len(sys.argv):
            global ACCOUNT
            ACCOUNT = sys.argv[i + 1]

    print(f"Account: {ACCOUNT}")
    print(f"Parallel uploads: {parallel}")

    # Find all equirectangular PNGs
    patterns = [
        os.path.join(SCRIPT_DIR, "output-*", "*_equirectangular.png"),
    ]
    png_files = []
    for pattern in patterns:
        png_files.extend(glob.glob(pattern))
    png_files.sort()

    print(f"Found {len(png_files)} equirectangular PNGs to upload")

    if not png_files:
        print("Nothing to upload!")
        return

    total_size = sum(os.path.getsize(f) for f in png_files) / 1024 / 1024 / 1024
    print(f"Total size: {total_size:.2f} GB")

    # Connect to Drive
    print("\nConnecting to Google Drive...")
    service = get_service()

    # Create folder structure: FOOTAGE/360Cities/
    print("Creating folder structure: FOOTAGE/360Cities/")
    footage_id = find_or_create_folder(service, "FOOTAGE")
    cities_id = find_or_create_folder(service, "360Cities", footage_id)
    print(f"  FOOTAGE folder ID: {footage_id}")
    print(f"  360Cities folder ID: {cities_id}")

    # Upload files
    print(f"\nStarting upload of {len(png_files)} files...")
    results = []
    uploaded = 0
    skipped = 0
    failed = 0

    for i, filepath in enumerate(png_files):
        filename = os.path.basename(filepath)
        print(f"\n[{i+1}/{len(png_files)}] {filename}")
        try:
            result = upload_file(service, filepath, cities_id)
            results.append(result)
            if result["status"] == "uploaded":
                uploaded += 1
            else:
                skipped += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            results.append({"status": "failed", "name": filename, "error": str(e)})
            failed += 1

    # Summary
    print("\n" + "=" * 60)
    print("UPLOAD SUMMARY")
    print("=" * 60)
    print(f"  Total: {len(png_files)} | Uploaded: {uploaded} | Skipped: {skipped} | Failed: {failed}")

    # Save results
    results_path = os.path.join(SCRIPT_DIR, "logs", f"upload_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results: {results_path}")


if __name__ == "__main__":
    main()
