# -*- coding: utf-8 -*-
"""Regression test for the hand-checked glossary and the sense picker.

Runs with no data files at all, so it can be executed in CI:

    python tools/selftest.py

Every case below is a real bug that was found during the quality review, so a
failure here means the table regressed.
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import glossary  # noqa: E402

FAILED = []


def check(label, got, want):
    ok = got == want
    print("%s %-28s %s" % ("PASS" if ok else "FAIL", label, got))
    if not ok:
        FAILED.append("%s: got %r, want %r" % (label, got, want))


def main():
    print("-- hand-checked single characters --")
    for ch, want in [
        ("打", "to hit; to play"),          # was "dozen"
        ("吧", "(sentence particle)"),      # was "bar"
        ("小", "small; little"),            # was "few"
        ("可", "can; may; -able"),          # was "but; however"
        ("电", "electricity"),              # was "lightning"
        ("篇", "article; chapter"),         # was "sheet"
        ("刘", "(surname Liu)"),            # was "a type of battle-ax"
        ("士", "scholar; person; soldier"),  # was a classical rank, 40 chars long
    ]:
        check("char " + ch, glossary.refine_char(ch, "something"), want)

    print("-- hand-checked words --")
    for word, want in [
        ("告诉", "to tell; to inform"),      # was "to press charges"
        ("东西", "thing; stuff"),            # was "east and west"
        ("结果", "result; outcome"),         # was "to bear fruit"
        ("一次", "once; one time"),          # was "first"
        ("都是", "all are; both are"),       # not in CC-CEDICT at all
        ("广州", "Guangzhou"),
        ("香港", "Hong Kong, China"),
    ]:
        check("word " + word, glossary.refine_word(word, "something"), want)

    print("-- sense picker --")
    table = {
        "告诉": ["to press charges; to file a complaint", "to tell; to inform"],
        "测验": ["to weigh in a balance or on a scale", "water"],
        "这里": ["variant of 這裡|这里[zhe4 li3]"],
        "這裡": ["here"],
        "东奔西走": ["also"],
        "没有": ["haven't", "to not have"],
    }
    check("picks the everyday sense", glossary.best_gloss("告诉", table),
          "to tell; to inform")
    check("prefers the everyday sense over the wordy one",
          glossary.best_gloss("测验", table), "water")
    check("hand-checked word table wins over the picker",
          glossary.refine_word("活动", glossary.best_gloss("活动", table)),
          "activity; event")
    check("resolves variant chains", glossary.best_gloss("这里", table), "here")
    check("drops placeholder senses", glossary.best_gloss("东奔西走", table), None)

    print("-- noise filter --")
    noisy = {
        "犭": ['"dog" radical in Chinese characters'],
        "它 ": ["variant of 它[ta1]"],
        "缶 ": ["see 缶[ fou3]"],
    }
    for word in noisy:
        check("drop noise for %r" % word.rstrip(),
              glossary.best_gloss(word, noisy), None)
    clean = {"缶 ": ["pottery; jar"]}
    check("keep a clean gloss", glossary.best_gloss("缶 ", clean), "pottery; jar")

    print("-- traditional-only characters are dropped --")
    for ch in ("後", "於", "徵"):
        check("drop " + ch, glossary.refine_char(ch, "???", ), None)

    print("-- candidate range preservation (name-typing regression) --")
    # Regression: rebuilding candidates with Candidate("table", 0, #code, ...)
    # marked every candidate as covering the whole input, so composing a name
    # like 李林菲 (lilinfei) and picking 李 swallowed the rest of the code.
    # The fix wraps candidates in ShadowCandidate, which must preserve each
    # candidate's own input range. The lua source is checked textually because
    # CI has no librime-lua runtime; the semantics were verified against a
    # real Lua (lupa) simulation of a multi-segment composition.
    lua_path = os.path.join(HERE, "..", "lua", "input_text.lua")
    with open(lua_path, encoding="utf-8") as f:
        lua_src = f.read()
    # ignore the explanatory comment block: only real code must not hand-build
    code_only = "\n".join(l for l in lua_src.splitlines()
                          if not l.lstrip().startswith("--"))
    check("filter wraps candidates with ShadowCandidate",
          "ShadowCandidate(cand" in code_only, True)
    check("filter does not hand-build candidate ranges",
          'Candidate("table", 0' not in code_only, True)

    print("-- table sizes --")
    print("   SINGLE %d | WORD %d | COLLOQUIAL %d | LEGACY %d"
          % (len(glossary.SINGLE), len(glossary.WORD),
             len(glossary.COLLOQUIAL), len(glossary._LEGACY)))
    if len(glossary.SINGLE) < 1000 or len(glossary.WORD) < 300:
        FAILED.append("hand-checked tables look truncated")

    print()
    if FAILED:
        print("FAILED (%d):" % len(FAILED))
        for line in FAILED:
            print("  -", line)
        return 1
    print("all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
