#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build the translation cache that the Rime filter reads.

Output format (UTF-8, one entry per line, tab separated):

    你<TAB>you; I; me
    告诉<TAB>to tell; to inform

The file is sorted by how likely a word is to be typed, because the lua filter
reads it front to back in 40k-line chunks: the everyday vocabulary becomes
available within the first few keystrokes.

Nothing is machine translated here on purpose.  Every gloss comes either from
CC-CEDICT (passed through the sense picker in glossary.py) or from the
hand-checked tables in glossary.py / data/overrides_legacy.json.

Usage:
    python build_cache.py
    python build_cache.py --cedict ../data/cedict.json --out "%TEMP%/rime_argos/cache.txt"
    python build_cache.py --dict-dir "%APPDATA%/Rime"     # for a better sort order
"""
import argparse
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import glossary  # noqa: E402

DEFAULT_CEDICT = os.path.join(HERE, os.pardir, "data", "cedict.json")
DEFAULT_OUT = os.path.join(os.environ.get("TEMP", "."), "rime_argos", "cache.txt")

BIG_RANK = 10 ** 9
NOISE_IN_GLOSS = (
    "variant of", "old variant", "see ", "used in", "prefix used",
    "taiwan pr.", "classifier for", "(bound form)", "abbr. for",
    "dialectal", "erhua variant", "also written", "surname ",
)


def is_noisy_gloss(gloss):
    low = gloss.lower()
    return any(noise in low for noise in NOISE_IN_GLOSS)


def is_simplified(ch):
    """True for characters that exist in GB2312 (i.e. simplified/common)."""
    try:
        ch.encode("gb2312")
        return True
    except UnicodeEncodeError:
        return False


def keep_entry(word, gloss):
    if not word or not gloss or is_noisy_gloss(gloss):
        return False
    if not word.isascii() and not all(is_simplified(c) or c.isascii() for c in word):
        return False
    return True


def rank_map(weights):
    """word -> rank by frequency (0 = most frequent)."""
    ordered = sorted(weights.items(), key=lambda kv: -kv[1])
    return {word: i for i, (word, _w) in enumerate(ordered)}


def read_weights(path):
    """Word -> weight from a Rime dictionary (its weight column is real usage
    frequency harvested from a corpus)."""
    weights = {}
    if not path or not os.path.exists(path):
        return weights
    started = False
    with io.open(path, encoding="utf-8") as fh:
        for line in fh:
            raw = line.rstrip("\n")
            if raw.strip() == "...":
                started = True
                continue
            if not started or not raw or raw.startswith("#"):
                continue
            parts = raw.split("\t")
            if len(parts) >= 3:
                try:
                    weights[parts[0]] = float(parts[2])
                except ValueError:
                    pass
    return weights


def gloss_for(word, table):
    """Clean English for *word*: hand-checked first, else the best CEDICT sense."""
    raw = glossary.best_gloss(word, table)
    if len(word) == 1:
        return glossary.refine_char(word, raw)
    return glossary.refine_word(word, raw)


def build(table, wubi_dict=None, pinyin_dict=None, max_len=4):
    data = {}
    for word in table:
        if not (1 <= len(word) <= max_len):
            continue
        if not word.isascii() and not all(is_simplified(c) or c.isascii() for c in word):
            continue
        gloss = gloss_for(word, table)
        if gloss and keep_entry(word, gloss):
            data[word] = gloss

    # Hand-checked entries that CC-CEDICT does not contain at all (都是, 就能,
    # 我的, 广州 ...).  Without this pass they would never show up.
    for source in (glossary.WORD, glossary.COLLOQUIAL,
                   glossary.SINGLE, glossary._LEGACY):
        for key, gloss in source.items():
            if not (1 <= len(key) <= max_len) or not gloss:
                continue
            if all(is_simplified(c) or c.isascii() for c in key):
                data.setdefault(key, gloss)
    return data


def order(data, wubi_dict, pinyin_dict):
    """Sort by usefulness: dictionary frequency, then character frequency."""
    rank_wubi = rank_map(read_weights(wubi_dict))
    rank_pinyin = rank_map(read_weights(pinyin_dict))
    char_weight = {k: v for k, v in read_weights(wubi_dict).items() if len(k) == 1}
    rank_char = rank_map(char_weight)

    def word_rank(word):
        char_rank = max((rank_char.get(c, BIG_RANK) for c in word), default=BIG_RANK)
        # a longer word built from common characters is not automatically common
        char_rank += 400 * (len(word) - 1)
        return min(rank_wubi.get(word, BIG_RANK),
                   rank_pinyin.get(word, BIG_RANK),
                   char_rank)

    return sorted(data.items(), key=lambda kv: word_rank(kv[0]))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--cedict", default=DEFAULT_CEDICT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--dict-dir", default=os.path.join(os.environ.get("APPDATA", ""), "Rime"),
                    help="folder containing wubi86.dict.yaml / pinyin_simp.dict.yaml")
    ap.add_argument("--max-len", type=int, default=4)
    args = ap.parse_args()

    if not os.path.exists(args.cedict):
        raise SystemExit("CC-CEDICT not found: %s\nRun fetch_cedict.py first." % args.cedict)

    with io.open(args.cedict, encoding="utf-8") as fh:
        table = json.load(fh)
    print("cedict entries : %d" % len(table))

    data = build(table, max_len=args.max_len)
    ordered = order(data,
                    os.path.join(args.dict_dir, "wubi86.dict.yaml"),
                    os.path.join(args.dict_dir, "pinyin_simp.dict.yaml"))

    out = os.path.abspath(args.out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with io.open(out, "w", encoding="utf-8") as fh:
        for zh, en in ordered:
            fh.write("%s\t%s\n" % (zh, en))

    # the optional MT service uses these two files; keep them empty/clean
    mailbox = os.path.dirname(out)
    for extra in ("cache_extra.txt", "fresh.txt"):
        open(os.path.join(mailbox, extra), "w", encoding="utf-8").close()

    from collections import Counter
    print("entries written: %d -> %s" % (len(ordered), out))
    print("size           : %.1f MB" % (os.path.getsize(out) / 1048576.0))
    print("by length      : %s" % sorted(Counter(len(k) for k, _ in ordered).items()))
    print("top 12         : %s" % [w for w, _ in ordered[:12]])
    for probe in ("的", "在", "打", "吧", "告诉", "东西", "结果", "都是", "学生", "电脑"):
        print("  %s -> %s" % (probe, data.get(probe, "(none)")))


if __name__ == "__main__":
    main()
