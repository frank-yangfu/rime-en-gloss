#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Rebuild the expanded simplified, toneless Pinyin dictionary ("pinyin_simp expanded").

Why
---
The stock pinyin_simp.dict.yaml (Android PinyinIME derived) has 65k entries and
stops at 4-character words, so ordinary modern vocabulary cannot be typed at all
(tangping / dianzan / zhibojian / tanzhonghe / duanshipin / dashuju / yunjisuan /
qukuailian ...).  This script merges the stock dictionary with CC-CEDICT so the
result can be dropped in as a replacement *without touching any schema*.

What it produces
----------------
    name: pinyin_simp          <- identical to the stock file, so the existing
    sort: by_weight               wubi_pinyin schema (dictionary: pinyin_simp)
                                  picks it up with no dependency changes.
    <word>  <toneless pinyin>  <weight>

Layers
------
1. the stock pinyin_simp.dict.yaml verbatim - all 65,125 entries, real per
   character frequencies untouched (de 4828294 ...).
2. CC-CEDICT simplified headwords with tones stripped, added only when the same
   (word, pinyin) code is not already present.  Weight is assigned by word
   length (--w2/--w3/--w4/--w5).  Lengths are compared in *syllables*, not
   characters, because erhua syllables were split (hua1r -> "hua er").

Reproducibility
---------------
Deterministic and idempotent: identical inputs always produce a byte-identical
file (no timestamps, no set iteration order in the output).  After writing, the
file is re-read and checked for NUL bytes, for the expected entry count and for
the expected name field; a non-zero exit means the artifact is not usable.

Usage
-----
    python build_pinyin_exp.py
    python build_pinyin_exp.py --source cedict.txt.gz --out ..\..\词表快照\pinyin_simp_expanded.dict.yaml
    python build_pinyin_exp.py --cedict-json data/cedict.json     # offline fallback

This script never writes anywhere near the Rime user directory (APPDATA/Rime).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, os.pardir))
DEFAULT_OUT = os.path.join(os.path.dirname(REPO), "词表快照", "pinyin_simp_expanded.dict.yaml")

URL = ("https://www.mdbg.net/chinese/export/cedict/"
       "cedict_1_0_ts_utf-8_mdbg.txt.gz")
DEFAULT_SOURCE = os.path.join(REPO, "data", "cedict.txt.gz")
DEFAULT_JSON = os.path.join(REPO, "data", "cedict.json")
DEFAULT_PINYIN_SIMP = os.path.join(
    os.environ.get("APPDATA", ""), "Rime", "pinyin_simp.dict.yaml")

CEDICT_RE = re.compile(r"^(\S+)\s+(\S+)\s+\[([^\]]*)\]\s+/(.*)/\s*$")

# Readings that are real but are missing from the character table.  Keeping
# them means those words are still emitted; the character table may not be able
# to spell every one of them yet.
EXTRA_SYLLABLES = {
    "nue", "lue", "rua", "bia", "hng", "xx", "yo", "lo", "ei", "den", "nen",
    "kei", "tei", "shei", "zhei", "fiao", "dia", "eng",
}

LENGTH_WEIGHTS = {2: 20000, 3: 15000, 4: 10000}


def is_han(ch):
    o = ord(ch)
    return (0x3400 <= o <= 0x4DBF or 0x4E00 <= o <= 0x9FFF
            or 0xF900 <= o <= 0xFAFF or 0x20000 <= o <= 0x2FA1F)


def all_han(s):
    return bool(s) and all(is_han(c) for c in s)


def log(msg):
    sys.stderr.write(msg + "\n")


# --------------------------------------------------------------------------
# stock dictionary
# --------------------------------------------------------------------------
def load_stock(path):
    """Read a Rime dict -> (header_lines, entries, char_pinyin, syllables).

    entries is an ordered list of (word, pinyin, weight_string); the original
    text and weight of every verbatim entry is preserved.
    """
    if not path or not os.path.exists(path):
        raise SystemExit("stock dictionary not found: %s" % path)
    with io.open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    lines = text.splitlines()
    head = []
    entries = []
    started = False
    for line in lines:
        if not started:
            head.append(line)
            if line.strip() == "...":
                started = True
            continue
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        word, pinyin = parts[0], parts[1]
        weight = parts[2].strip() if len(parts) > 2 else "0"
        if not word or not pinyin:
            continue
        entries.append((word, pinyin, weight))
    # strip the "..." from the head so it can be re-emitted after the metadata
    if head and head[-1].strip() == "...":
        head = head[:-1]
    char_pinyin = defaultdict(list)
    syllables = set()
    for word, pinyin, weight in entries:
        toks = pinyin.split()
        if len(word) == 1 and len(toks) == 1:
            char_pinyin[word].append(toks[0])
            syllables.add(toks[0])
        for t in toks:
            syllables.add(t)
    return head, entries, char_pinyin, syllables


# --------------------------------------------------------------------------
# CC-CEDICT
# --------------------------------------------------------------------------
def iter_cedict_lines(path, url=None, cache_dir=None):
    if path:
        opener = gzip.open if path.endswith(".gz") else io.open
        if path.endswith(".gz"):
            with opener(path, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    yield line
        else:
            with opener(path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    yield line
        return
    if cache_dir:
        cached = os.path.join(cache_dir, "cedict.txt.gz")
        if os.path.exists(cached):
            log("using cached %s" % cached)
            with gzip.open(cached, "rt", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    yield line
            return
    target = url or URL
    log("downloading %s" % target)
    req = urllib.request.Request(target, headers={"User-Agent": "rime-en-gloss/pinyin_exp"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        blob = resp.read()
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        with open(os.path.join(cache_dir, "cedict.txt.gz"), "wb") as fh:
            fh.write(blob)
    for line in blob.decode("utf-8", "replace").splitlines():
        yield line


def parse_cedict(lines):
    """-> [(simplified, toneless_syllables)] in first-seen order, deduplicated."""
    out = []
    seen = set()
    for raw in lines:
        if not raw or raw.startswith("#"):
            continue
        m = CEDICT_RE.match(raw.strip())
        if not m:
            continue
        _trad, simp, pinyin, _defs = m.groups()
        if not pinyin.strip():
            continue
        key = (simp, pinyin)
        if key in seen:
            continue
        seen.add(key)
        out.append((simp, pinyin))
    return out


def normalise_readings(pinyin, syllables, allow_unknown):
    """CC-CEDICT pinyin -> toneless syllables, or None when unusable.

    Tones are removed, u:/ü becomes v (matching the stock spelling 女=nv,
    略=lue), and erhua is split so hua1r -> "hua er".
    """
    toks = []
    for raw in pinyin.split():
        t = raw.strip().lower().replace("u:", "v").replace("ü", "v")
        t = re.sub(r"[1-5]", "", t)
        if not t:
            return None
        toks.append(t)
    if not toks:
        return None
    out = []
    for t in toks:
        if t in syllables:
            out.append(t)
        elif t.endswith("r") and t[:-1] in syllables:
            out.append(t[:-1])
            out.append("er")
        elif t == "r" and "er" in syllables:
            out.append("er")
        elif allow_unknown and re.fullmatch(r"[a-z]{1,8}", t):
            out.append(t)
        else:
            return None
    return out


def load_cedict_json(path, char_pinyin):
    """Offline fallback: cedict.json has no pinyin, so guess it per character."""
    with io.open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    out = []
    for word in data:
        if not all_han(word):
            continue
        reading = []
        for c in word:
            plist = char_pinyin.get(c)
            if not plist:
                reading = None
                break
            reading.append(plist[0])
        if reading:
            out.append((word, " ".join(reading)))
    return out


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------
def build(args):
    head, stock, char_pinyin, syllables = load_stock(args.pinyin_simp)
    syllables = set(syllables) | EXTRA_SYLLABLES
    log("stock: %d entries, %d syllables" % (len(stock), len(syllables)))
    if len(stock) > 100000:
        log("WARNING: the stock dictionary looks like it is already the expanded "
            "version (%d entries).  Re-run with --pinyin-simp pointing at the "
            "original pinyin_simp.dict.yaml so the layers do not double up."
            % len(stock))

    seen = set((w, p) for w, p, _ in stock)
    added = 0
    skipped = Counter()
    lengths = Counter()
    layers = Counter()

    for word, pinyin, _weight in stock:
        layers["stock"] += 1

    if args.source:
        cedict = parse_cedict(iter_cedict_lines(args.source, args.url, args.cache_dir))
    elif args.url or args.cache_dir:
        cedict = parse_cedict(iter_cedict_lines(None, args.url, args.cache_dir))
    elif args.cedict_json and os.path.exists(args.cedict_json):
        log("using %s as the CC-CEDICT source (no pinyin there; readings are "
            "guessed from the character table)" % args.cedict_json)
        cedict = load_cedict_json(args.cedict_json, char_pinyin)
    else:
        raise SystemExit("no CC-CEDICT source: pass --source, --url or --cedict-json")

    extra = []
    for word, pinyin in cedict:
        if not all_han(word):
            skipped["non_han"] += 1
            continue
        norm = normalise_readings(pinyin, syllables, args.allow_unknown_syllables)
        if norm is None:
            skipped["pinyin"] += 1
            continue
        n = len(norm)
        if n < args.min_len or n > args.max_len:
            skipped["length"] += 1
            continue
        code = " ".join(norm)
        if (word, code) in seen:
            skipped["duplicate"] += 1
            continue
        seen.add((word, code))
        weight = LENGTH_WEIGHTS.get(n, args.w5)
        extra.append((word, code, str(weight)))
        added += 1
        lengths[n] += 1

    entries = stock + extra
    log("CC-CEDICT headwords: %d, added %d (skipped %s)"
        % (len(cedict), added, dict(skipped)))

    # ---- emit ------------------------------------------------------------
    out = io.StringIO()
    out.write("# Rime dictionary\n")
    out.write("# encoding: utf-8\n")
    out.write("#\n")
    out.write("# pinyin_simp expanded - stock PinyinIME dictionary + CC-CEDICT phrases\n")
    out.write("#\n")
    out.write("#   chars+phrases : pinyin_simp.dict.yaml (Android PinyinIME, Apache-2.0)\n")
    out.write("#   extra phrases : CC-CEDICT (https://cc-cedict.org, CC BY-SA 4.0), tones stripped\n")
    out.write("#   weights       : stock frequencies kept verbatim; CC-CEDICT by syllable count\n")
    out.write("#                   (%s)\n" % ", ".join(
        "%d->%d" % (k, v) for k, v in sorted(LENGTH_WEIGHTS.items())))
    out.write("#\n")
    out.write("# This file is a drop-in replacement for pinyin_simp.dict.yaml: the name field is\n")
    out.write("# kept identical on purpose, so no schema or dependencies change is needed.\n")
    out.write("#\n")
    out.write("# generated by rime-en-gloss/tools/build_pinyin_exp.py - do not edit by hand\n")
    out.write("#\n")
    out.write("---\n")
    out.write("name: %s\n" % args.name)
    out.write('version: "%s"\n' % args.version)
    out.write("sort: by_weight\n")
    out.write("...\n")
    for word, code, weight in entries:
        out.write("%s\t%s\t%s\n" % (word, code, weight))
    text = out.getvalue()

    # ---- write + self check ---------------------------------------------
    stats = {
        "stock_entries": len(stock),
        "cedict_headwords": len(cedict),
        "added": added,
        "total": len(entries),
        "skipped": dict(skipped),
        "by_syllable_count": {str(k): v for k, v in sorted(lengths.items())},
    }
    blob = text.encode("utf-8")
    if args.dry_run:
        log("dry run: %d entries, %d bytes" % (len(entries), len(blob)))
        return stats

    outdir = os.path.dirname(os.path.abspath(args.out))
    if outdir:
        os.makedirs(outdir, exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(blob)

    # verify what actually landed on disk
    disk = open(args.out, "rb").read()
    problems = []
    if len(disk) != len(blob) or disk != blob:
        problems.append("written file differs from the generated buffer")
    if disk.count(b"\x00"):
        problems.append("written file contains %d NUL bytes" % disk.count(b"\x00"))
    if disk != text.encode("utf-8") and not problems:
        problems.append("encoding mismatch")
    if ("name: %s\n" % args.name).encode("utf-8") not in disk:
        problems.append("name field missing")
    body = disk.split(b"...\n", 1)
    if len(body) != 2:
        problems.append("missing ... header terminator")
    else:
        got = len([l for l in body[1].split(b"\n") if l.strip()])
        if got != len(entries):
            problems.append("entry count on disk %d != %d" % (got, len(entries)))
    stats["bytes"] = len(disk)
    stats["nul"] = disk.count(b"\x00")
    stats["on_disk_entries"] = got
    stats["self_check"] = "FAIL: " + "; ".join(problems) if problems else "PASS"
    if problems:
        log("SELF CHECK FAILED: " + "; ".join(problems))
    else:
        log("wrote %s (%d entries, %d bytes, self check PASS)"
            % (args.out, len(entries), len(disk)))
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT,
                    help="output path (default: 词表快照/pinyin_simp_expanded.dict.yaml); "
                         "never writes into the Rime user directory")
    ap.add_argument("--name", default="pinyin_simp",
                    help="dictionary name; keep pinyin_simp for a drop-in replacement")
    ap.add_argument("--version", default="0.2")
    ap.add_argument("--source", default=None,
                    help="CC-CEDICT .txt / .txt.gz (default: data/cedict.txt.gz if present)")
    ap.add_argument("--url", default=None, help="download URL when --source is absent")
    ap.add_argument("--cache-dir", default=os.path.join(REPO, "data"),
                    help="where a downloaded archive is cached ('' disables)")
    ap.add_argument("--cedict-json", default=DEFAULT_JSON,
                    help="offline fallback JSON (no pinyin; readings guessed)")
    ap.add_argument("--pinyin-simp", default=DEFAULT_PINYIN_SIMP,
                    help="stock dictionary to build on top of")
    ap.add_argument("--min-len", type=int, default=2,
                    help="minimum syllable count for CC-CEDICT additions")
    ap.add_argument("--max-len", type=int, default=16)
    ap.add_argument("--w2", type=int, default=20000)
    ap.add_argument("--w3", type=int, default=15000)
    ap.add_argument("--w4", type=int, default=10000)
    ap.add_argument("--w5", type=int, default=6000,
                    help="weight for 5+ syllable additions")
    ap.add_argument("--allow-unknown-syllables", action="store_true", default=True)
    ap.add_argument("--report", default=None, help="write a JSON statistics file")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    global LENGTH_WEIGHTS
    LENGTH_WEIGHTS = {2: args.w2, 3: args.w3, 4: args.w4}

    if args.source and not os.path.exists(args.source):
        log("source %s not found" % args.source)
        args.source = None
    if args.source is None and args.cache_dir and os.path.exists(
            os.path.join(args.cache_dir, "cedict.txt.gz")):
        args.source = os.path.join(args.cache_dir, "cedict.txt.gz")
    if args.source is None and os.path.exists(DEFAULT_SOURCE):
        args.source = DEFAULT_SOURCE
    if args.cache_dir == "":
        args.cache_dir = None

    stats = build(args)
    log("stats: " + json.dumps(stats, ensure_ascii=False, sort_keys=True))
    if args.report:
        with io.open(args.report, "w", encoding="utf-8") as fh:
            json.dump(stats, fh, ensure_ascii=False, indent=1, sort_keys=True)
    return 1 if str(stats.get("self_check", "")).startswith("FAIL") else 0


if __name__ == "__main__":
    sys.exit(main())
