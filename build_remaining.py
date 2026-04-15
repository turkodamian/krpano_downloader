import os, glob

done = set()
base = "c:/Appz/krpanoDownloader-main"
for d in glob.glob(os.path.join(base, "output-*")):
    slug = os.path.basename(d).replace("output-", "")
    pngs = glob.glob(os.path.join(d, "*_equirectangular.png"))
    jpgs = glob.glob(os.path.join(d, "*_equirectangular.jpg"))
    if pngs or jpgs:
        done.add(slug)

with open(os.path.join(base, "all_urls.txt")) as f:
    all_urls = [l.strip() for l in f if l.strip()]

remaining = []
for url in all_urls:
    slug = url.rstrip("/").split("/")[-1]
    if slug not in done:
        remaining.append(url)

with open(os.path.join(base, "remaining_urls.txt"), "w") as f:
    for url in remaining:
        f.write(url + "\n")

print(f"Total: {len(all_urls)}")
print(f"Already done: {len(done)}")
print(f"Remaining: {len(remaining)}")
