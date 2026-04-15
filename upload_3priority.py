import sys
sys.path.insert(0, "c:/Appz/krpanoDownloader-main")
from upload_to_drive import get_service, find_or_create_folder, upload_file

SLUGS = [
    "intercontinental-thalasso-borabora-diamond-villa-lounge",
    "cafe-design",
    "stylish-lounge-in-an-apartment-with-large-tv-overlooking-city",
]
FOLDER_ID = "1vjMmwfNlkzHKsLoixCZ1EZqprBIeYm7q"  # FOOTAGE/360Cities

svc = get_service()
for slug in SLUGS:
    path = f"c:/Appz/krpanoDownloader-main/output-{slug}/{slug}_equirectangular.png"
    print(f"\n>>> {slug}")
    upload_file(svc, path, FOLDER_ID)

print("\n=== LINKS ===")
for slug in SLUGS:
    name = f"{slug}_equirectangular.png"
    q = f"name='{name}' and '{FOLDER_ID}' in parents and trashed=false"
    r = svc.files().list(q=q, fields="files(id,name,webViewLink,size)").execute()
    for f in r.get("files", []):
        mb = int(f.get("size",0))/1024/1024
        print(f"{f['name']} ({mb:.1f} MB)")
        print(f"  {f['webViewLink']}")
