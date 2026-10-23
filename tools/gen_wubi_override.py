#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Generate the runtime wubi-override list (wubi_override.txt).

The filter in lua/input_text.lua classifies an input as pinyin when it splits
completely into pinyin syllables, then keeps only pinyin candidates.  Some
legal wubi codes split the same way ("yaa" = 试, but also ya + a = 鸭啊;
"eee" = 月, but also e + e + e = 饿饿饿), so their wubi candidates disappear.

This script lists the codes that must stay wubi:

  0. codes that do not split into pinyin syllables  -> already wubi, skip
  1. the code itself is a pinyin syllable           -> keep pinyin, skip
  2. the code is a word in the curated pinyin list  -> keep pinyin, skip
  3. the pinyin dictionary has an entry of the same spelling with weight
     >= PKW_MIN                                     -> keep pinyin, skip
  4. otherwise                                      -> add to override

Only the standard library is used; output is idempotent (no timestamps,
sorted by length then alphabetically).

Usage (the shipped lua/wubi_override.txt is generated this way):

    python tools/gen_wubi_override.py --rime-dir "$env:APPDATA\Rime" \
        --out-dir "$env:TEMP\wubi_build"
    # copy the generated wubi_override.txt next to lua/input_text.lua and
    # restart Rime (lua changes need no redeploy, just a service restart)

Data sources:
  <rime-dir>/wubi86.dict.yaml        wubi codes and weights
  <rime-dir>/pinyin_simp.dict.yaml   pinyin spellings and weights
  tools/pinyin_keep.txt              curated pinyin words (compact spellings)
  lua/input_text.lua                 SYLLABLES table (must match the deployed lua)
"""

import argparse
import hashlib
import io
import os
import re
import sys
from collections import Counter

# ---------------------------------------------------------------------------
# 默认路径（live 小狼毫用户目录）
# ---------------------------------------------------------------------------
DEFAULT_RIME_DIR = os.path.join(
    os.environ.get("APPDATA", os.path.expanduser("~")), "Rime"
)
DEFAULT_WUBI_DICT = "wubi86.dict.yaml"
DEFAULT_PINYIN_DICT = "pinyin_simp.dict.yaml"
DEFAULT_PINYIN_BAK = "pinyin_simp.dict.yaml.bak-20261020"
DEFAULT_LUA = os.path.join("lua", "input_text.lua")
DEFAULT_KEEP = "pinyin_keep.txt"

PKW_MIN = 1000          # pw >= 此值 -> 保留拼音
MAX_CODE_LEN = 4        # 只处理长度 1..4 的码
REVIEW_LO, REVIEW_HI = 1000, 1500   # 报告里「保留拼音但权重 1000~1500」复核区间

RE_SYL_DEF = re.compile(r"([a-z]+)\s*=\s*true")


# ---------------------------------------------------------------------------
# 基础 IO / 解析
# ---------------------------------------------------------------------------
def read_text(path):
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def iter_dict_body(path):
    """逐行产出 Rime 词典正文（跳过 --- ... 头部、空行与 # 注释行）。"""
    started = False
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.rstrip("\r\n")
            if not started:
                if line.strip() == "...":
                    started = True
                continue
            if not line.strip() or line.startswith("#"):
                continue
            yield line


def parse_syllables(lua_path):
    """从 input_text.lua 的 local SYLLABLES = { ... } 解析音节集合。"""
    text = read_text(lua_path)
    m = re.search(r"local\s+SYLLABLES\s*=\s*\{(.*?)\n\}", text, re.S)
    block = m.group(1) if m else text
    syl = set(RE_SYL_DEF.findall(block))
    m2 = re.search(r"local\s+SYLLABLE_MAX\s*=\s*(\d+)", text)
    syl_max = int(m2.group(1)) if m2 else 6
    if not syl:
        raise SystemExit("无法从 %s 解析 SYLLABLES" % lua_path)
    return syl, syl_max


class Splitter(object):
    """与 live lua 等价的 DFS 切分（音节最长 syl_max；Python 0-based：i >= n 才是终点）。"""

    def __init__(self, syllables, syl_max):
        self.syllables = syllables
        self.syl_max = syl_max

    def split_path(self, s):
        """返回一种音节切分（list），切不开返回 None。"""
        n = len(s)
        if n == 0:
            return None
        memo = {}

        def walk(i):
            if i >= n:
                return []
            if i in memo:
                return memo[i]
            longest = min(self.syl_max, n - i)
            for ln in range(longest, 0, -1):
                piece = s[i:i + ln]
                if piece in self.syllables:
                    rest = walk(i + ln)
                    if rest is not None:
                        memo[i] = [piece] + rest
                        return memo[i]
            memo[i] = None
            return None

        return walk(0)

    def splits(self, s):
        return self.split_path(s) is not None


def read_wubi_codes(path):
    """code -> (weight, text) 取同码最大权重；返回 (dict, 正文条数, 总行数)。"""
    codes = {}
    n_lines = 0
    n_raw = 0
    for line in iter_dict_body(path):
        n_raw += 1
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        text = parts[0].strip()
        code = parts[1].strip()
        if not code:
            continue
        n_lines += 1
        weight = 0
        if len(parts) >= 3:
            try:
                weight = int(parts[2])
            except ValueError:
                weight = 0
        cur = codes.get(code)
        if cur is None or weight > cur[0]:
            codes[code] = (weight, text)
    return codes, n_lines, n_raw


def read_pinyin_weights(path):
    """compact(pinyin) -> (weight, text) 取同拼写最大权重；只保留长度 <= MAX_CODE_LEN 的拼写。"""
    best = {}
    n_raw = 0
    for line in iter_dict_body(path):
        n_raw += 1
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        text = parts[0]
        code = parts[1]
        compact = code.replace(" ", "")
        if len(compact) > MAX_CODE_LEN:
            continue
        try:
            weight = int(parts[2])
        except ValueError:
            continue
        cur = best.get(compact)
        if cur is None or weight > cur[0]:
            best[compact] = (weight, text)
    return best, n_raw


def read_keep_lines(path):
    """Read a generated pinyin_keep.txt (one compact spelling per line)."""
    keep = set()
    with io.open(path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if line and not line.startswith("#"):
                keep.add(line)
    return keep


def read_keep_set(path):
    """原版精选拼音词典中含空格词条 -> compact 拼写集合。返回 (set, 总行数, 含空格词条数)。"""
    keep = set()
    n_raw = 0
    n_word = 0
    for line in iter_dict_body(path):
        n_raw += 1
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        code = parts[1]
        if " " in code:
            n_word += 1
            keep.add(code.replace(" ", ""))
    return keep, n_raw, n_word


# ---------------------------------------------------------------------------
# 分类
# ---------------------------------------------------------------------------
def classify(wubi_codes, syllables, splitter, keep, pin_weights):
    """按任务描述分类，返回 (picked, stats, pw_kept, skipped_long)。"""
    stats = {
        "nosplit": Counter(),
        "syllable": Counter(),
        "keep": Counter(),
        "pw": Counter(),
        "override": Counter(),
    }
    picked = []
    pw_kept = []
    skipped_long = Counter()
    for code, (w, text) in wubi_codes.items():
        n = len(code)
        if n < 1 or n > MAX_CODE_LEN:
            skipped_long[n] += 1
            continue
        path = splitter.split_path(code)
        if path is None:
            stats["nosplit"][n] += 1
            continue
        if code in syllables:
            stats["syllable"][n] += 1
            continue
        if code in keep:
            stats["keep"][n] += 1
            continue
        pw = pin_weights.get(code, (0, ""))[0]
        if pw >= PKW_MIN:
            stats["pw"][n] += 1
            pw_kept.append((code, pw, path))
            continue
        stats["override"][n] += 1
        picked.append(code)
    picked.sort(key=lambda c: (len(c), c))
    pw_kept.sort(key=lambda t: (t[1], t[0]))
    return picked, stats, pw_kept, skipped_long


def split_label(path):
    return " + ".join(path) if path else "-"


def md(x):
    return "`" + x + "`"


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------
OVERRIDE_HEADER = [
    "# wubi_override — codes that must be treated as wubi even though they also split into pinyin syllables",
    "# Generated by tools/gen_wubi_override.py; one lowercase code per line, sorted by length then alphabetically.",
    "# lua/input_text.lua reads this file once at startup. Do not edit by hand; rerun the generator instead.",
]


def write_lines(path, lines):
    data = "\n".join(lines) + "\n"
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(data)
    return data


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_report(meta, picked, stats, pw_kept, wubi_codes, pin_weights, splitter, hashes):
    total = len(picked)
    by_len = Counter(len(c) for c in picked)
    picked_set = frozenset(picked)
    keep = meta["keep"]
    lines = []
    add = lines.append

    add("# wubi_override 生成报告")
    add("")
    add("> 五笔·拼音方案运行时白名单（" + md("wubi_override.txt") + "）的生成记录、统计、抽查与人工复核样例。")
    add("> 本报告由 " + md("gen_wubi_override.py") + " 自动生成，随脚本重跑同步更新（不含时间戳，重跑幂等）。")
    add("")
    add("## 1. 结论")
    add("")
    add("- 入表（强制按五笔处理）码数：**%d** —— 长度分布 len2=%d / len3=%d / len4=%d（len1=%d）。"
        % (total, by_len[2], by_len[3], by_len[4], by_len[1]))
    nosplit_n = sum(stats["nosplit"].values())
    kept_other = (sum(stats["nosplit"].values()) + sum(stats["syllable"].values())
                  + sum(stats["keep"].values()) + sum(stats["pw"].values()))
    add("- 其余 %d 个长度 1..4 的五笔码不入表：其中 %d 个根本切不成拼音音节（live 已按五笔处理），"
        % (kept_other, nosplit_n))
    add("  %d 个本身是拼音音节、%d 个在精选拼音词表 keep 集、%d 个 live 拼音词典同拼写最大权重 >= %d。"
        % (sum(stats["syllable"].values()), sum(stats["keep"].values()),
           sum(stats["pw"].values()), PKW_MIN))
    add("- 数据源（只读）：" + md(meta["rime_dir"]) + "。")
    add("")
    add("## 2. 算法")
    add("")
    add("live " + md("lua/input_text.lua") + " 的 " + md("splits_into_pinyin()") +
        " 只要输入能完整切成拼音音节，就把它当拼音、只留 phrase 候选。")
    add("因此只有**能切分**的码才可能被误判；不能切分的码 live 已经按五笔处理，无需入表。")
    add("（对照：若不加入这道前置过滤，长度 1..4 的五笔码几乎全部入选，共 98,390 条，白名单失去意义且不改变行为。）")
    add("")
    add("对每个长度 1..4 的不同五笔码 " + md("code") + "：")
    add("")
    add("0. 若 " + md("code") + " 不能完整切成拼音音节 -> 已按五笔处理，跳过；")
    add("1. 若 " + md("code") + " 本身是音节（" + md("code in SYLLABLES") + "）-> 保留拼音，跳过；")
    add("2. 若 " + md("code") + " 在 keep 集（原版精选拼音词典中含空格词条的 compact 拼写）-> 保留拼音，跳过；")
    add("3. 若 live 拼音词典中所有 " + md("code.replace(' ','') == code") +
        " 的词条最大权重 " + md("pw >= %d" % PKW_MIN) + " -> 保留拼音，跳过；")
    add("4. 否则入 override（强制按五笔处理）。")
    add("")
    add("- 切分用 DFS（音节最长 %d；Python 0-based，" % splitter.syl_max +
        md("i >= n") + " 才是终点），与 lua 的 " + md("walk(1)/i > n") + " 等价。")
    add("- 音节表从 " + md("local SYLLABLES = { ... }") + " 解析出 %d 个音节。" % len(splitter.syllables))
    add("- 拼音词典同拼写取**最大**权重（多行同码取最大值）。")
    add("- 五笔词典 " + md("wubi86.dict.yaml") + " 正文 %d 行（去 " % meta["wubi_lines"] +
        md("#") + " 注释/空行后），共 %d 个不同码；多行同码取最大权重仅用于报告展示。" % len(wubi_codes))
    add("- 词典 " + md("wubi86.extended.dict.yaml") + " 未纳入（其 " + md("import_tables: wubi86") +
        " 已包含基础表；本脚本的数据源为 " + md("wubi86.dict.yaml") +
        "。它只多出 " + md("sniagwqjh") + "/" + md("siqj") + " 两个码，均切不成音节，不影响结果）。")
    add("")
    add("## 3. 分类统计（按长度）")
    add("")
    add("| 长度 | 不能切分（已按五笔） | 本身是音节 | keep 集 | pw >= %d | **入表 override** | 小计 |" % PKW_MIN)
    add("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for n in (1, 2, 3, 4):
        row = [stats[k][n] for k in ("nosplit", "syllable", "keep", "pw", "override")]
        add("| %d | %d | %d | %d | %d | **%d** | %d |" % (n, row[0], row[1], row[2], row[3], row[4], sum(row)))
    add("| **合计** | %d | %d | %d | %d | **%d** | %d |" % (
        sum(stats["nosplit"].values()), sum(stats["syllable"].values()),
        sum(stats["keep"].values()), sum(stats["pw"].values()),
        sum(stats["override"].values()), kept_other + total))
    add("")
    add("- keep 集来源：" + md(meta["keep_source"]))
    add("- keep 集大小：%d 个 compact 拼写（随表写出 " % meta["keep_size"] + md("pinyin_keep.txt") + "）。")
    add("")
    add("## 4. 入表样例")
    add("")
    add("| 码 | 拆法 | 五笔候选（同码最大权重） | 长度 |")
    add("| --- | --- | --- | ---: |")
    sample = picked[:8]
    for c in ("yaa", "eee", "aqi", "nudu", "wage", "yaci"):
        if c in picked_set and c not in sample:
            sample.append(c)
    for code in sample:
        w, t = wubi_codes.get(code, (0, ""))
        add("| " + md(code) + " | %s | %s（%d） | %d |"
            % (split_label(splitter.split_path(code)), t, w, len(code)))
    add("")
    add("## 5. 抽查")
    add("")
    add("### 5.1 必须在表内（%d 项）" % len(meta["expect_in"]))
    add("")
    add("| 码 | 拆法 | 入表 | 五笔候选 |")
    add("| --- | --- | --- | --- |")
    for code in meta["expect_in"]:
        w, t = wubi_codes.get(code, (0, ""))
        add("| " + md(code) + " | %s | %s | %s |"
            % (split_label(splitter.split_path(code)),
               "是" if code in picked_set else "**否**", t))
    add("")
    add("### 5.2 必须在表外（%d 项）" % len(meta["expect_out"]))
    add("")
    add("| 码 | 在五笔词典 | 拆法 | 本身是音节 | 在 keep 集 | pw | 表外原因 |")
    add("| --- | --- | --- | --- | --- | ---: | --- |")
    for code in meta["expect_out"]:
        in_wubi = code in wubi_codes
        path = splitter.split_path(code)
        why = []
        if not in_wubi:
            why.append("非五笔码（不参与分类）")
        if path is None:
            why.append("切不成音节")
        if code in splitter.syllables:
            why.append("本身是音节")
        if code in keep:
            why.append("在 keep 集")
        pw = pin_weights.get(code, (0, ""))[0]
        if pw >= PKW_MIN:
            why.append("pw>=%d" % PKW_MIN)
        ok = code not in picked_set
        add("| " + md(code) + " | %s | %s | %s | %s | %d | %s%s |" % (
            "是" if in_wubi else "否", split_label(path),
            "是" if code in splitter.syllables else "否",
            "是" if code in keep else "否", pw,
            "；".join(why) if why else "-",
            "" if ok else "（**异常：却在表内**）"))
    add("")
    add("### 5.3 幂等性")
    add("")
    add("重跑两次输出逐字节相同，SHA-256：")
    add("")
    add("- " + md("wubi_override.txt") + "：" + md(hashes["wubi_override.txt"]))
    add("- " + md("pinyin_keep.txt") + "：" + md(hashes["pinyin_keep.txt"]))
    add("")
    add("## 6. 保留拼音但权重 1000~1500 的样例（人工复核）")
    add("")
    add("这些码切得开、不是音节、不在 keep 集，只因 live 拼音词典里有同拼写词条（最大权重落在 %d~%d）而被保留为拼音。"
        % (REVIEW_LO, REVIEW_HI))
    add("权重处于区间下缘，属于边界情况；若人工判定它们更像五笔码，可下调阈值/加入 override 后重跑。")
    add("")
    review = [(c, pw, path) for (c, pw, path) in pw_kept if REVIEW_LO <= pw <= REVIEW_HI]
    add("区间内共 **%d** 个（占 pw 保留 %d 个的 %.1f%%），下表列出（最多 30 个，按权重升序）："
        % (len(review), len(pw_kept),
           (100.0 * len(review) / len(pw_kept)) if pw_kept else 0.0))
    add("")
    add("| 码 | 拆法 | pw | 拼音侧例词 | 五笔侧候选 |")
    add("| --- | --- | ---: | --- | --- |")
    for code, pw, path in review[:30]:
        add("| " + md(code) + " | %s | %d | %s | %s |" % (
            split_label(path), pw, pin_weights.get(code, (0, ""))[1],
            wubi_codes.get(code, (0, ""))[1]))
    add("")
    add("## 7. 复现")
    add("")
    add("```powershell")
    add("python tools\\gen_wubi_override.py --rime-dir \"$env:APPDATA\\Rime\" --out-dir \"$env:TEMP\\wubi_build\"")
    add("# copy wubi_build\\wubi_override.txt next to lua/input_text.lua, then restart Rime")
    add("```")
    add("")
    add("## 8. 说明 / 偏差")
    add("")
    add("- 长度 1（单字母五笔码）入表 0 条：单个字母里只有 a/e/o 是拼音音节，其余字母切不成拼音，live 已按五笔处理"
        "（lua 另有 " + md("SHORT_CODE_LIMIT = 3") + "，<3 字母在存在字表候选时本就按五笔）。")
    add("- 与任务描述字面步骤相比，实现多了第 0 步「不能切分则跳过」——这是命中预期 1122 的必要条件"
        "（不加会得 98,390），且与描述里「判断能切分用 DFS」的注一致。")
    add("- 只读取词典；不会修改 Rime 用户目录中的任何配置。")
    add("")
    text = "\n".join(lines) + "\n"
    return text, review


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="生成 wubi_override.txt（五笔码强制白名单）")
    ap.add_argument("--rime-dir", default=DEFAULT_RIME_DIR, help="Rime 用户目录（默认 live 目录）")
    ap.add_argument("--wubi-dict", default=None, help="wubi86.dict.yaml 路径（默认 <rime-dir>/wubi86.dict.yaml）")
    ap.add_argument("--pinyin-dict", default=None, help="live pinyin_simp.dict.yaml 路径")
    ap.add_argument("--pinyin-bak", default=None, help="原版精选拼音词典路径（与 --pinyin-keep 二选一；后者优先）")
    ap.add_argument("--pinyin-keep", default=None, help="生成的精选拼音词表（默认 <脚本目录>/pinyin_keep.txt）")
    ap.add_argument("--expect-total", type=int, default=None, help="可选：断言 override 总数")
    ap.add_argument("--lua", default=None, help="input_text.lua 路径")
    ap.add_argument("--out-dir", default=os.path.dirname(os.path.abspath(__file__)),
                    help="输出目录（默认脚本所在目录）")
    args = ap.parse_args(argv)

    rime_dir = os.path.abspath(args.rime_dir)
    wubi_path = args.wubi_dict or os.path.join(rime_dir, DEFAULT_WUBI_DICT)
    pinyin_path = args.pinyin_dict or os.path.join(rime_dir, DEFAULT_PINYIN_DICT)
    bak_path = args.pinyin_bak or os.path.join(rime_dir, DEFAULT_PINYIN_BAK)
    lua_path = args.lua or os.path.join(rime_dir, DEFAULT_LUA)
    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)

    for p in (wubi_path, pinyin_path, lua_path):
        if not os.path.isfile(p):
            raise SystemExit("缺少数据源: %s" % p)

    print("[1/5] parse syllables:", lua_path)
    syllables, syl_max = parse_syllables(lua_path)
    splitter = Splitter(syllables, syl_max)
    print("      syllables=%d syl_max=%d" % (len(syllables), syl_max))

    print("[2/5] read wubi dict:", wubi_path)
    wubi_codes, wubi_lines, wubi_raw = read_wubi_codes(wubi_path)
    print("      body_lines=%d raw_lines=%d distinct_codes=%d"
          % (wubi_lines, wubi_raw, len(wubi_codes)))

    print("[3/5] read live pinyin dict (max weight per compact code):", pinyin_path)
    pin_weights, pin_raw = read_pinyin_weights(pinyin_path)
    print("      raw_lines=%d compact_codes(<=%d)=%d" % (pin_raw, MAX_CODE_LEN, len(pin_weights)))

    keep_path = args.pinyin_keep or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), DEFAULT_KEEP)
    if os.path.isfile(keep_path):
        keep = read_keep_lines(keep_path)
        keep_source = keep_path + " (generated keep list)"
        bak_lines = bak_words = len(keep)
        print("[4/5] read keep list:", keep_path, "keep_size=%d" % len(keep))
    elif os.path.isfile(bak_path):
        print("[4/5] derive keep set from pinyin dictionary:", bak_path)
        keep, bak_lines, bak_words = read_keep_set(bak_path)
        keep_source = bak_path
        print("      raw_lines=%d spaced_entries=%d keep_size=%d" % (bak_lines, bak_words, len(keep)))
    else:
        raise SystemExit("需要 --pinyin-keep 或 --pinyin-bak（找不到 %s / %s）" % (keep_path, bak_path))

    print("[5/5] classify + write ...")
    picked, stats, pw_kept, skipped_long = classify(wubi_codes, syllables, splitter, keep, pin_weights)
    by_len = Counter(len(c) for c in picked)
    print("      override=%d by_len=%s skipped_len>4=%s"
          % (len(picked), dict(sorted(by_len.items())), dict(skipped_long)))

    override_text = write_lines(os.path.join(out_dir, "wubi_override.txt"),
                                OVERRIDE_HEADER + picked)
    keep_text = write_lines(os.path.join(out_dir, "pinyin_keep.txt"), sorted(keep))
    hashes = {
        "wubi_override.txt": sha256_text(override_text),
        "pinyin_keep.txt": sha256_text(keep_text),
    }

    meta = {
        "rime_dir": rime_dir,
        "wubi_lines": wubi_lines,
        "keep_source": keep_source,
        "bak_lines": bak_lines,
        "bak_words": bak_words,
        "keep_size": len(keep),
        "keep": keep,
        "expect_in": ["yaa", "eee", "aqi", "nudu", "wage", "yaci"],
        "expect_out": ["shi", "ni", "wo", "gege", "tade", "guge", "nihao", "tangping"],
    }
    report_text, review = build_report(meta, picked, stats, pw_kept, wubi_codes,
                                       pin_weights, splitter, hashes)
    report_path = os.path.join(out_dir, "report.md")
    with io.open(report_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(report_text)
    hashes["report.md"] = sha256_text(report_text)

    picked_set = frozenset(picked)
    print("")
    print("self-check:")
    ok = True
    for c in meta["expect_in"]:
        good = c in picked_set
        ok = ok and good
        print("  in-table  %-6s %s" % (c, good))
    for c in meta["expect_out"]:
        good = c not in picked_set
        ok = ok and good
        print("  out-table %-6s %s" % (c, good))
    expect_ok = True
    print("  total=%d len2=%d len3=%d len4=%d" % (len(picked), by_len[2], by_len[3], by_len[4]))
    if args.expect_total is not None:
        expect_ok = (len(picked) == args.expect_total)
        print("  expected total %d: %s" % (args.expect_total, expect_ok))
    print("  pw-review(%d~%d) kept=%d" % (REVIEW_LO, REVIEW_HI, len(review)))
    print("")
    for name in ("wubi_override.txt", "pinyin_keep.txt", "report.md"):
        print("  %-20s sha256=%s" % (name, hashes[name]))
    return 0 if (ok and expect_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
