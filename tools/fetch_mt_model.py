# -*- coding: utf-8 -*-
"""
Download the zh->en model used by optional_mt_server.py (Argos Translate, MIT
licensed, ~74 MB) and unpack it into ./models/zh_en.

    python fetch_mt_model.py             # linux / macos (needs tar)
    python fetch_mt_model.py --keep-pkg  # keep the downloaded archive

The model is optional: rime-en-gloss works without it.
"""
import json
import os
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS_DIR = os.path.join(HERE, "models")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

INDEX_MIRRORS = [
    "https://cdn.jsdelivr.net/gh/argosopentech/argospm-index@main/index.json",
    "https://fastly.jsdelivr.net/gh/argosopentech/argospm-index@main/index.json",
    "https://raw.githubusercontent.com/argosopentech/argospm-index/main/index.json",
]


def fetch(url, timeout=600):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def load_index():
    err = None
    for url in INDEX_MIRRORS:
        try:
            data = json.loads(fetch(url, 60).decode("utf-8"))
            print("index ok:", url)
            return data
        except Exception as exc:
            err = exc
            print("index failed:", url, exc)
    raise SystemExit("cannot fetch index: %s" % err)


def main():
    os.makedirs(MODELS_DIR, exist_ok=True)

    index = load_index()
    cands = [
        p
        for p in index
        if p.get("type", "translate") in ("translate", None)
        and p.get("from_code") == "zh"
        and p.get("to_code") == "en"
    ]
    if not cands:
        raise SystemExit("zh->en not found in index")
    pkg = sorted(cands, key=lambda p: str(p.get("package_version", "")))[-1]
    print("package:", pkg.get("from_code"), "->", pkg.get("to_code"), pkg.get("package_version"))

    links = pkg.get("links") or []
    blob = None
    for url in links:
        try:
            print("downloading:", url)
            blob = fetch(url, 900)
            print("got", len(blob), "bytes")
            break
        except Exception as exc:
            print("link failed:", url, exc)
    if blob is None:
        raise SystemExit("all links failed")

    pkg_path = os.path.join(MODELS_DIR, "translate-zh_en.argosmodel")
    with open(pkg_path, "wb") as fh:
        fh.write(blob)
    print("saved:", pkg_path)

    out_dir = os.path.join(MODELS_DIR, "zh_en")
    os.makedirs(out_dir, exist_ok=True)
    with zipfile.ZipFile(pkg_path) as zf:
        zf.extractall(out_dir)
        print("extracted to:", out_dir)
        for n in zf.namelist()[:30]:
            print("  ", n)


if __name__ == "__main__":
    main()
