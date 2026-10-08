#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Download CC-CEDICT and convert it to the JSON shape used by build_cache.py.

CC-CEDICT is a free Chinese-English dictionary maintained by MDBG, released
under CC BY-SA 4.0 -- see https://cc-cedict.org/ .

Usage:
    python fetch_cedict.py                  # writes ../data/cedict.json
    python fetch_cedict.py --out custom.json
    python fetch_cedict.py --source local.txt.gz   # use a file you already have
"""
import argparse
import gzip
import json
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, os.pardir, "data", "cedict.json")
URL = ("https://www.mdbg.net/chinese/export/cedict/"
       "cedict_1_0_ts_utf-8_mdbg.txt.gz")

# Traditional Simplified [pin1 yin1] /def one/def two/
LINE_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.+)/\s*$")


def parse(lines):
    """-> {word: [definition, ...]}, keyed by both simplified and traditional."""
    table = {}
    for raw in lines:
        if raw.startswith("#"):
            continue
        m = LINE_RE.match(raw.strip())
        if not m:
            continue
        traditional, simplified, _pinyin, defs = m.groups()
        parts = [d.strip() for d in defs.split("/") if d.strip()]
        if not parts:
            continue
        table[simplified] = parts
        if traditional != simplified:
            table.setdefault(traditional, parts)
    return table


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT, help="output JSON path")
    ap.add_argument("--source", help="use a local .txt / .txt.gz instead of downloading")
    args = ap.parse_args()

    if args.source:
        path = args.source
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    else:
        sys.stderr.write("downloading %s ...\n" % URL)
        req = urllib.request.Request(URL, headers={"User-Agent": "rime-en-gloss"})
        with urllib.request.urlopen(req, timeout=120) as resp:
            blob = resp.read()
        text = gzip.decompress(blob).decode("utf-8", errors="replace")
        lines = text.splitlines()

    table = parse(lines)
    if not table:
        raise SystemExit("no entries parsed -- source looks wrong")

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(table, fh, ensure_ascii=False)
    print("entries : %d" % len(table))
    print("written : %s (%.1f MB)" % (out, os.path.getsize(out) / 1048576.0))
    for probe in ("你好", "学生", "打", "告诉"):
        print("  %s -> %s" % (probe, table.get(probe, ["(not found)"])[:3]))


if __name__ == "__main__":
    main()
