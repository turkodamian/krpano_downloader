"""Upload specific priority panoramas to Drive (one-shot)."""
import sys
sys.path.insert(0, "c:/Appz/krpanoDownloader-main")

# Reuse functions from upload_to_drive.py
from upload_to_drive import get_service, find_or_create_folder, upload_file

SLUGS = [
    "detske-ihrisko-sidlisko-snp-povazska-bystrica",
    "onde-koleji-acik-oyun-bahcesi",
    "parque-infantil-zarugalde",
    "panorama_tmp-9106",
]

def main():
    svc = get_service()
    footage = find_or_create_folder(svc, "FOOTAGE")
    cities = find_or_create_folder(svc, "360Cities", parent_id=footage)
    print(f"Target folder: FOOTAGE/360Cities (id={cities})")
    for slug in SLUGS:
        path = f"c:/Appz/krpanoDownloader-main/output-{slug}/{slug}_equirectangular.png"
        print(f"\n>>> {slug}")
        upload_file(svc, path, cities)

if __name__ == "__main__":
    main()
