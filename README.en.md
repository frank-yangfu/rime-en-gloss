# rime-en-gloss

[![Release](https://img.shields.io/github/v/release/frank-yangfu/rime-en-gloss?sort=semver&color=green)](https://github.com/frank-yangfu/rime-en-gloss/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)](#install-manual-any-platform)
[![Rime](https://img.shields.io/badge/Rime-Weasel%20%7C%20Squirrel%20%7C%20ibus--rime%20%7C%20fcitx5-informational)](#install-manual-any-platform)
[![Dependencies](https://img.shields.io/badge/dependencies-none-success)](#how-it-works)
[![Table](https://img.shields.io/badge/table-96k%20entries-orange)](docs/quality-review.md)

> Show the **English meaning of every Chinese candidate** in the Rime candidate
> window (Weasel / Squirrel / ibus-rime / fcitx5-rime). Offline, no API key, no
> noticeable typing lag.

![English comments in the candidate window: typing "fg" gives 二 fg, two / 十 ~h, ten / 博 ~e, broad; extensive](docs/images/candidate-english.png)

*Real screenshot: the English sits in the candidate comment slot, so pressing
space still commits the Chinese word.*

```
┌─────────────────────────────────────────────┐
│ wjjg                                        │
├─────────────────────────────────────────────┤
│ 1. 告诉    wjjg, to tell; to inform         │
│ 2. 东西    aiit, thing; stuff               │
│ 3. 结果    xfjs, result; outcome            │
└─────────────────────────────────────────────┘
```

## Why another one?

Most existing solutions either call an online translation API (key required,
often unreachable) or print the first CC-CEDICT sense verbatim, which is usually
the wrong one — `打 → dozen`, `告诉 → to press charges`, `吧 → bar`.
rime-en-gloss focuses on two things: **gloss quality** and **never freezing the
host application**.

## Install (manual, any platform)

```bash
# 1) the filter
cp lua/input_text.lua <rime user dir>/lua/

# 2) the table
cd tools
python fetch_cedict.py        # CC-CEDICT ~200k entries -> ../data/cedict.json
python build_cache.py        # -> $TMPDIR/rime_argos/cache.txt (96,784 entries)
#    add --dict-dir <rime user dir> to use the dictionary's real word weights
#    for ordering, and --out to write somewhere else

# 3) register the filter: save as <schema>.custom.yaml, then redeploy
#    patch:
#      "engine/filters/+":
#        - lua_filter@*input_text*filter
```

On Windows there is a one-shot installer: `powershell -File scripts\install.ps1`.

## How it works

```
CC-CEDICT ──► tools/glossary.py ──► tools/build_cache.py ──► cache.txt
              (sense picker +        (pure stdlib)            │
               hand-checked tables)                           │ incremental read
                                                              ▼
                                        lua/input_text.lua (candidate filter)
                                                              │ cache miss
                                                              ▼
                                          request.txt ── optional local MT
```

The filter runs **synchronously inside the input thread** of whatever program
you type into, so it does no HTTP, never execs a process, inspects at most 30
candidates, reads the disk only on a cache miss, and parses at most 40k lines
per keystroke. See `docs/how-it-works.md`.

## Data quality

| word | first CEDICT sense | what you get |
|---|---|---|
| 打 | dozen | to hit; to play |
| 告诉 | to press charges | to tell; to inform |
| 东西 | east and west | thing; stuff |
| 一次 | first | once; one time |
| 刘 | a type of battle-ax | (surname Liu) |

Achieved by: merging all dictionary entries of a word (CC-CEDICT splits one word
over several entries and the file order is not "most common sense first"),
resolving `variant of` chains including self-references, scoring every candidate
sense against a common-English word list, demoting proper-noun senses (otherwise
比萨 becomes "Pisa" and 大拇指 "Tom Thumb"), 1,700+ hand-checked overrides, and
dropping dictionary noise. Machine translation is deliberately **not** used to
generate entries — it produced things like `人不 → No, no, no`, `就能 → Yeah`.
See `docs/quality-review.md`.

## Layout

```
lua/input_text.lua          the only runtime component
tools/glossary.py           hand-checked tables + sense picker
tools/build_cache.py        rebuild the table
tools/fetch_cedict.py       download/convert CC-CEDICT
tools/optional_mt_server.py optional offline model service (long-tail words)
schema/add_filter.patch.yaml how to attach the filter
scripts/                    Windows installer & service launchers
docs/                       design notes, quality review, troubleshooting
docs/releases/v1.0.0.md     release notes, offline
```

## Author

Frank ([@frank-yangfu](https://github.com/frank-yangfu))

## License

Code: MIT. Dictionary data: [CC-CEDICT](https://cc-cedict.org/) (CC BY-SA 4.0),
downloaded locally at build time and not redistributed here.
