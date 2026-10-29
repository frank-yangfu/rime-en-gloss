#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Build a supplemental Wubi word dictionary.

The classic ibus-table wubi86.dict.yaml word list is old: many ordinary
modern words are missing.  For example 骑行 (cdtf) is absent, so typing cdtf
shows 参选; 车店 (lgyh) is absent, so the code produces nothing at all.

This tool takes one or more Chinese word lists, computes the standard Wubi
word code for every 2-4+ character word (AaAbBaBb / AaBaCaCb / AaBaCaZa), and
writes a supplemental dictionary that imports the base table:

    ---
    name: wubi86.extended
    import_tables:
      - wubi86
    ...
    骑行    cdtf    50000000

Weighting
---------
* words for codes that are currently empty get --low (visible, harmless);
* words for codes whose best entry is weak (< --floor) get --floor;
* codes that already have a strong entry are left alone (no noise), unless
  --include-strong is given.

An optional weights file (word<TAB>weight) overrides the defaults, so you can
plug in your own frequency list.

Usage
-----
    python tools/build_wubi_words.py \
        --wubi-dict "%APPDATA%\\Rime\\wubi86.dict.yaml" \
        --words     words.txt \
        --extra     data/wubi_words_extra.txt \
        --out       "%APPDATA%\\Rime\\wubi86.extended.dict.yaml"

Then point the schema at the extended dictionary and redeploy:

    patch:
      translator/dictionary: wubi86.extended

See docs/wubi-words.md for the full story (and the prebuilt dictionary in
the v1.4.0 release).
"""
import argparse
import collections
import io
import os
import sys

HANZI_LO, HANZI_HI = "\u4e00", "\u9fff"


def iter_dict_body(path):
    started = False
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not started:
                if line.strip() == "...":
                    started = True
                continue
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                yield parts


def is_hanzi(word):
    return bool(word) and all(HANZI_LO <= ch <= HANZI_HI for ch in word)


def load_wubi(path):
    char_codes = collections.defaultdict(list)
    code_best = {}
    word_code = {}
    for parts in iter_dict_body(path):
        word, code = parts[0], parts[1]
        if not code:
            continue
        try:
            weight = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            weight = 0
        if len(word) == 1:
            char_codes[word].append(code)
        cur = code_best.get(code)
        if cur is None or weight > cur[0]:
            code_best[code] = (weight, word)
        key = (word, code)
        if weight > word_code.get(key, -1):
            word_code[key] = weight
    return char_codes, code_best, word_code


def full_code(char_codes, ch):
    codes = [c for c in char_codes.get(ch, []) if c and c.islower()]
    if not codes:
        return None
    return max(codes, key=lambda c: (len(c), c))


def wubi_word_code(char_codes, word):
    """Standard Wubi word code."""
    if len(word) == 2:
        a, b = full_code(char_codes, word[0]), full_code(char_codes, word[1])
        if not a or not b or len(a) < 2 or len(b) < 2:
            return None
        return a[0] + a[1] + b[0] + b[1]
    if len(word) == 3:
        a, b, c = (full_code(char_codes, ch) for ch in word)
        if not a or not b or not c or len(c) < 2:
            return None
        return a[0] + b[0] + c[0] + c[1]
    if len(word) >= 4:
        a, b, c = (full_code(char_codes, ch) for ch in word[:3])
        z = full_code(char_codes, word[-1])
        if not a or not b or not c or not z:
            return None
        return a[0] + b[0] + c[0] + z[0]
    return None


def load_word_lists(paths, min_len, max_len):
    seen = set()
    words = []
    for path in paths:
        with io.open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#"):
                    continue
                word = line.split("\t")[0].split()[0] if line.split() else ""
                if min_len <= len(word) <= max_len and is_hanzi(word) and word not in seen:
                    seen.add(word)
                    words.append(word)
    return words


def load_weights(path):
    weights = {}
    if not path or not os.path.isfile(path):
        return weights
    with io.open(path, encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) < 2:
                continue
            try:
                weights[parts[0]] = int(float(parts[1]))
            except ValueError:
                continue
    return weights


def load_extra(paths):
    """Read hand-made entries (word<TAB>code[<TAB>weight]); headers optional."""
    entries = []
    for path in paths or []:
        if not path or not os.path.isfile(path):
            continue
        with io.open(path, encoding="utf-8", errors="replace") as f:
            for raw in f:
                line = raw.strip()
                if not line or line.startswith("#") or line in ("---", "..."):
                    continue
                parts = line.split("\t")
                if len(parts) < 2:
                    continue
                word, code = parts[0], parts[1]
                try:
                    weight = int(parts[2]) if len(parts) > 2 else 0
                except ValueError:
                    weight = 0
                entries.append((word, code, weight))
    return entries


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a supplemental Wubi word dictionary")
    ap.add_argument("--wubi-dict", required=True, help="base wubi86.dict.yaml")
    ap.add_argument("--words", action="append", required=True,
                    help="word list file (repeatable, one word per line; cache.txt works too)")
    ap.add_argument("--weights-file", default=None,
                    help="optional word<TAB>weight overrides")
    ap.add_argument("--extra", action="append", default=[],
                    help="existing dictionary with hand-made entries to keep (repeatable)")
    ap.add_argument("--out", required=True, help="output .dict.yaml")
    ap.add_argument("--import-table", default="wubi86", help="import_tables name (default wubi86)")
    ap.add_argument("--name", default="wubi86.extended", help="dictionary name")
    ap.add_argument("--min-len", type=int, default=2)
    ap.add_argument("--max-len", type=int, default=4)
    ap.add_argument("--floor", type=int, default=5000000,
                    help="weight for words that should lead a weak code")
    ap.add_argument("--low", type=int, default=1000000,
                    help="weight for words added to an empty code")
    ap.add_argument("--include-strong", action="store_true",
                    help="also add words whose code already has a strong entry")
    args = ap.parse_args(argv)

    char_codes, code_best, word_code = load_wubi(args.wubi_dict)
    words = load_word_lists(args.words, args.min_len, args.max_len)
    weights = load_weights(args.weights_file)
    extra = load_extra(args.extra)
    extra_keys = {(w, c) for (w, c, _) in extra}
    base_words = {w for (w, _c) in word_code}

    print("wubi codes: %d, chars: %d" % (len(code_best), len(char_codes)))
    print("words: %d, extra entries: %d" % (len(words), len(extra)))

    added = []
    skipped = 0
    for word in words:
        if word in base_words:
            continue
        code = wubi_word_code(char_codes, word)
        if not code or len(code) != 4 or (word, code) in extra_keys:
            continue
        if (word, code) in word_code:
            continue
        best = code_best.get(code)
        if word in weights:
            weight = weights[word]
        elif best is None:
            weight = args.low
        elif best[0] < args.floor:
            weight = args.floor
        elif args.include_strong:
            weight = args.low
        else:
            skipped += 1
            continue
        added.append((word, code, weight))

    seen = set(extra_keys)
    uniq = []
    for entry in added:
        key = (entry[0], entry[1])
        if key not in seen:
            seen.add(key)
            uniq.append(entry)
    added = sorted(uniq, key=lambda e: (e[1], e[0]))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with io.open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Supplemental Wubi words generated by tools/build_wubi_words.py\n")
        f.write("---\n")
        f.write("name: %s\n" % args.name)
        f.write('version: "1.0"\n')
        f.write("sort: by_weight\n")
        f.write("import_tables:\n")
        f.write("  - %s\n" % args.import_table)
        f.write("...\n")
        for word, code, weight in extra:
            f.write("%s\t%s\t%d\n" % (word, code, weight))
        for word, code, weight in added:
            f.write("%s\t%s\t%d\n" % (word, code, weight))
    print("added %d words, skipped %d strong codes -> %s"
          % (len(added), skipped, args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
