import sys
sys.path.insert(0, "c:/Appz/krpanoDownloader-main")
from upload_to_drive import get_service

FOLDER_ID = "1vjMmwfNlkzHKsLoixCZ1EZqprBIeYm7q"
NAMES = [
    "detske-ihrisko-sidlisko-snp-povazska-bystrica_equirectangular.png",
    "onde-koleji-acik-oyun-bahcesi_equirectangular.png",
    "parque-infantil-zarugalde_equirectangular.png",
    "panorama_tmp-9106_equirectangular.png",
]

svc = get_service()
for name in NAMES:
    q = f"name='{name}' and '{FOLDER_ID}' in parents and trashed=false"
    r = svc.files().list(q=q, fields="files(id,name,webViewLink,webContentLink,size)").execute()
    for f in r.get("files", []):
        print(f"{f['name']}")
        print(f"  view:     {f.get('webViewLink')}")
        print(f"  download: {f.get('webContentLink')}")
        print(f"  size:     {int(f.get('size',0))/1024/1024:.1f} MB")
        print()
