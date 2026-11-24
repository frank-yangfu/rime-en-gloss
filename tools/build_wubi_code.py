# -*- coding: utf-8 -*-
"""Build word -> wubi code table for the Rime comment filter.

Reads Rime wubi dictionaries (text<TAB>code<TAB>weight) and keeps the
highest-weight code for each word.  When --filter-cache is given, only words
that actually have an English gloss (i.e. appear in cache.txt) are kept -- no
point carrying codes for words that never get a comment.

Output format: word<TAB>wubi_code, sorted by weight (most useful first), so the
Lua filter can load it incrementally like cache.txt.

Usage:
  python build_wubi_code.py --dict-dir "%APPDATA%/Rime" \
      --filter-cache "%APPDATA%/Rime/rime_argos/cache.txt" \
      --out "%APPDATA%/Rime/rime_argos/wubi_code.txt"
"""
import argparse, io, os

DEFAULT_DICT = os.path.join(os.environ.get("APPDATA", ""), "Rime")
DEFAULT_MAILBOX = os.path.join(DEFAULT_DICT, "rime_argos")


def read_entries(path):
    entries = []
    if not path or not os.path.exists(path):
        return entries
    started = False
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            raw = line.rstrip("\n\r")
            if raw.strip() == "...":
                started = True
                continue
            if not started or not raw or raw.startswith("#"):
                continue
            parts = raw.split("\t")
            if len(parts) >= 3 and parts[0] and parts[1]:
                try:
                    weight = float(parts[2])
                except ValueError:
                    continue
                entries.append((parts[0], parts[1], weight))
    return entries


def read_words(path):
    words = set()
    if not path or not os.path.exists(path):
        return words
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            p = line.split("\t", 1)
            if len(p) == 2 and p[0]:
                words.add(p[0])
    return words


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dict-dir", default=DEFAULT_DICT)
    ap.add_argument("--out", default=os.path.join(DEFAULT_MAILBOX, "wubi_code.txt"))
    ap.add_argument("--filter-cache", default=os.path.join(DEFAULT_MAILBOX, "cache.txt"),
                    help="only emit codes for words present in this cache.txt")
    ap.add_argument("--dicts", nargs="+", default=["wubi86.dict.yaml", "wubi86.extended.dict.yaml"])
    args = ap.parse_args()

    keep = read_words(args.filter_cache) if args.filter_cache else None
    if keep is not None:
        print("cache words: %d" % len(keep))

    best = {}  # word -> (weight, code)
    for name in args.dicts:
        path = os.path.join(args.dict_dir, name)
        entries = read_entries(path)
        print("%s: %d entries" % (name, len(entries)))
        for word, code, weight in entries:
            if keep is not None and word not in keep:
                continue
            if word not in best or weight > best[word][0]:
                best[word] = (weight, code)

    # most useful first (same order idea as cache.txt)
    ordered = sorted(best.items(), key=lambda kv: -kv[1][0])
    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8", newline="\n") as fh:
        for word, (weight, code) in ordered:
            fh.write("%s\t%s\n" % (word, code))
    print("wrote %d words -> %s (%.2f MB)" % (len(ordered), out, os.path.getsize(out) / 1048576.0))
    for probe in ("我", "你", "学", "学生", "电脑", "告诉", "东西"):
        if probe in best:
            print("  %s -> %s" % (probe, best[probe][1]))


if __name__ == "__main__":
    main()
