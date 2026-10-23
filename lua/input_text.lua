--[[
input_text.lua -- English glosses in the candidate comment slot.

Also keeps wubi and pinyin candidates separate: a wubi code shows only wubi
candidates, a pinyin spelling shows only pinyin candidates.

How the split works
-------------------
librime tags every candidate with a *type* that reveals which translator
produced it:

    table       -- a wubi character/word from the table dictionary
    completion  -- a wubi prefix completion
    phrase      -- a pinyin word (script_translator)
    sentence    -- a whole sentence glued together from several segments
    reverse_lookup / others -- reverse-lookup noise

The input string decides the mode. A wubi code is 1-4 letters drawn from the
wubi alphabet and is *not* a sequence of legal pinyin syllables; a pinyin
spelling is always splittable into syllables from the dictionary.

Wubi override list
------------------
Some *legal* wubi codes are also legal pinyin spellings, so the split above
sends them to the pinyin side and the wubi result disappears:

    yaa  -- wubi 试, but splits as ya + a   -> 鸭啊 on the pinyin side
    eee  -- wubi 月, but splits as e + e + e -> 饿饿饿

wubi_override.txt lists the codes that must stay wubi, one code per line;
blank lines and lines starting with '#' are ignored.  An input found in the
list is forced to wubi mode before the pinyin split is attempted, so the wubi
candidates are kept and the pinyin ones dropped.

The list is generated offline by tools/gen_wubi_override.py.  A code is added
only when (a) it splits into pinyin syllables, (b) it is not itself a pinyin
syllable, (c) it is not a word in the curated pinyin dictionary, and (d) the
live pinyin dictionary has no entry of the same spelling with weight >= 1000.
Genuine pinyin spellings therefore stay pinyin; regenerate the list after
replacing the wubi or pinyin dictionary.  Nothing writes it at runtime.

Lookup order -- the first file that exists wins, and it is read exactly once:
    1. the directory this lua file lives in (debug.getinfo, source "@<path>")
    2. $RIME_EN_GLOSS_DIR, the helper mailbox, when set
    3. $TEMP/rime_argos/
A missing or unreadable file is not an error: the filter then behaves exactly
as it did before, and the failed lookup is never retried per keystroke.

Design rules that keep the host application responsive
-----------------------------------------------------
The filter runs synchronously inside the input thread of whatever program you
are typing into. Anything slow here freezes that program, so:
  * no C modules, no HTTP, no shelling out -- file reads only
  * the translation table is read incrementally, at most 40k lines per keystroke
  * disk access happens only on a cache miss, at most once per second
  * only the first PROCESS_LIMIT candidates are inspected
]]

local MAILBOX = os.getenv("RIME_EN_GLOSS_DIR")
if not MAILBOX or MAILBOX == "" then
    local base = os.getenv("TEMP") or os.getenv("TMPDIR") or os.getenv("TMP") or "/tmp"
    MAILBOX = base .. "/rime_argos"
end
local CACHE_FILE = MAILBOX .. "/cache.txt"
local FRESH_FILE = MAILBOX .. "/fresh.txt"
local REQ_FILE = MAILBOX .. "/request.txt"
local HEARTBEAT_FILE = MAILBOX .. "/heartbeat.txt"

local DEBUG = (os.getenv("RIME_EN_GLOSS_DEBUG") == "1")

-- ---------------------------------------------------------------------------
-- wubi override list
-- ---------------------------------------------------------------------------
-- Some legal wubi codes also split into legal pinyin syllables ("yaa" = 试,
-- "eee" = 月), so looks_like_wubi() below would send them to the pinyin side
-- and the wubi candidates would vanish.  wubi_override.txt lists those codes,
-- one per line, and any input found there is forced to wubi mode.
--
-- The filter runs in the input thread of the host application, so the list is
-- read lazily, exactly once, and every failure is swallowed: a missing or
-- broken file simply leaves the override table empty and the filter behaves
-- as it did before.  See the header comment for the search order.
local OVERRIDE = nil                  -- nil = not read yet; table = read once
local OVERRIDE_FILE = "wubi_override.txt"
local MAX_OVERRIDE_LINES = 4096       -- keeps a runaway file from stalling
local MAX_OVERRIDE_CODE = 24          -- no real input is longer than this

-- Diagnostics only; must never break typing.
local function override_trace(msg)
    if not DEBUG then
        return
    end
    pcall(function()
        local f = io.open(MAILBOX .. "/filter_debug.log", "a")
        if f then
            f:write(os.date("%Y-%m-%d %H:%M:%S ") .. msg .. "\n")
            f:close()
        end
    end)
end

-- Directory of this lua file.  debug.getinfo(1, "S").source is "@<path>" for
-- a chunk loaded from a file; a chunk loaded from a string has no "@" and
-- there is no directory to search.
local function script_directory()
    -- debug.getinfo must be called from a Lua frame: passing it straight to
    -- pcall(debug.getinfo, 1, "S") makes level 1 the C frame of pcall itself,
    -- whose source is "=[C]" and has no directory at all.  Calling it inside
    -- this closure keeps level 1 on this chunk.
    local ok, source = pcall(function()
        return debug.getinfo(1, "S").source
    end)
    if not ok or type(source) ~= "string" then
        return nil
    end
    local dir = source:match("^@(.*)[/\\][^/\\]*$")
    if dir and dir ~= "" then
        return dir
    end
    return nil
end

-- Candidate locations in priority order: next to this lua file, the mailbox
-- ($RIME_EN_GLOSS_DIR), then %TEMP%/rime_argos.
local function override_paths()
    local paths = {}
    local dir = script_directory()
    if dir then
        paths[#paths + 1] = dir .. "/" .. OVERRIDE_FILE
    end
    local mailbox = os.getenv("RIME_EN_GLOSS_DIR")
    if mailbox and mailbox ~= "" then
        paths[#paths + 1] = mailbox .. "/" .. OVERRIDE_FILE
    end
    local base = os.getenv("TEMP") or os.getenv("TMPDIR") or os.getenv("TMP") or "/tmp"
    paths[#paths + 1] = base .. "/rime_argos/" .. OVERRIDE_FILE
    return paths
end

-- Parse one file into a set of codes.  Returns nil when the file cannot be
-- opened, otherwise the set (which may be empty).  A read error keeps the
-- codes parsed so far instead of raising.
local function read_override(path)
    local f = io.open(path, "r")
    if not f then
        return nil
    end
    local set = {}
    local lines = 0
    pcall(function()
        for raw in f:lines() do
            lines = lines + 1
            if lines > MAX_OVERRIDE_LINES then
                break
            end
            local line = raw:gsub("\r$", "")
            line = line:match("^%s*(.-)%s*$") or ""
            if line ~= "" and line:sub(1, 1) ~= "#" and #line <= MAX_OVERRIDE_CODE then
                set[line] = true
            end
        end
    end)
    pcall(function()
        f:close()
    end)
    return set
end

local function load_override()
    -- Mark as loaded before touching the disk: nothing here may run twice or
    -- turn into per-keystroke IO, not even after a failure.
    OVERRIDE = {}
    local ok, err = pcall(function()
        local paths = override_paths()
        override_trace("wubi override: searching " .. table.concat(paths, " ; "))
        for i = 1, #paths do
            local set = read_override(paths[i])
            if set then
                local count = 0
                for _ in pairs(set) do
                    count = count + 1
                end
                OVERRIDE = set
                override_trace("wubi override: " .. count .. " code(s) from " .. paths[i])
                return
            end
        end
        override_trace("wubi override: no " .. OVERRIDE_FILE .. " found")
    end)
    if not ok then
        OVERRIDE = {}
        override_trace("wubi override: load failed: " .. tostring(err))
    end
    return OVERRIDE
end

local function override_codes()
    if OVERRIDE == nil then
        return load_override()
    end
    return OVERRIDE
end

local MAX_LOOKUP = 6
local MAX_LEN = 12
local MIN_CODE_LEN = 1
local PROCESS_LIMIT = 30
local MAX_LINES_PER_CALL = 40000
local SERVICE_CHECK_INTERVAL = 300

-- ---------------------------------------------------------------------------
-- pinyin syllable table
-- ---------------------------------------------------------------------------
-- Built from the dictionary the pinyin translator uses, so it always matches
-- the syllables librime itself accepts.  A spelling that splits completely
-- into these syllables is treated as pinyin; anything else is a wubi code.
local SYLLABLES = {
    a = true, ai = true, an = true, ang = true, ao = true,
    ba = true, bai = true, ban = true, bang = true, bao = true, bei = true,
    ben = true, beng = true, bi = true, bian = true, biao = true, bie = true,
    bin = true, bing = true, bo = true, bu = true,
    ca = true, cai = true, can = true, cang = true, cao = true, ce = true,
    cen = true, ceng = true, cha = true, chai = true, chan = true, chang = true,
    chao = true, che = true, chen = true, cheng = true, chi = true, chong = true,
    chou = true, chu = true, chua = true, chuai = true, chuan = true,
    chuang = true, chui = true, chun = true, chuo = true, ci = true,
    cong = true, cou = true, cu = true, cuan = true, cui = true, cun = true,
    cuo = true,
    da = true, dai = true, dan = true, dang = true, dao = true, de = true,
    dei = true, deng = true, di = true, dian = true, diao = true, die = true,
    ding = true, diu = true, dong = true, dou = true, du = true, duan = true,
    dui = true, dun = true, duo = true,
    e = true, ei = true, en = true, eng = true, er = true,
    fa = true, fan = true, fang = true, fei = true, fen = true, feng = true,
    fo = true, fou = true, fu = true,
    ga = true, gai = true, gan = true, gang = true, gao = true, ge = true,
    gei = true, gen = true, geng = true, gong = true, gou = true, gu = true,
    gua = true, guai = true, guan = true, guang = true, gui = true, gun = true,
    guo = true,
    ha = true, hai = true, han = true, hang = true, hao = true, he = true,
    hei = true, hen = true, heng = true, hong = true, hou = true, hu = true,
    hua = true, huai = true, huan = true, huang = true, hui = true, hun = true,
    huo = true,
    ji = true, jia = true, jian = true, jiang = true, jiao = true, jie = true,
    jin = true, jing = true, jiong = true, jiu = true, ju = true, juan = true,
    jue = true, jun = true,
    ka = true, kai = true, kan = true, kang = true, kao = true, ke = true,
    ken = true, keng = true, kong = true, kou = true, ku = true, kua = true,
    kuai = true, kuan = true, kuang = true, kui = true, kun = true, kuo = true,
    la = true, lai = true, lan = true, lang = true, lao = true, le = true,
    lei = true, leng = true, li = true, lia = true, lian = true, liang = true,
    liao = true, lie = true, lin = true, ling = true, liu = true, long = true,
    lou = true, lu = true, luan = true, lun = true, luo = true, lve = true,
    ma = true, mai = true, man = true, mang = true, mao = true, me = true,
    mei = true, men = true, meng = true, mi = true, mian = true, miao = true,
    mie = true, min = true, ming = true, miu = true, mo = true, mou = true,
    mu = true,
    na = true, nai = true, nan = true, nang = true, nao = true, ne = true,
    nei = true, nen = true, neng = true, ni = true, nian = true, niang = true,
    niao = true, nie = true, nin = true, ning = true, niu = true, nong = true,
    nou = true, nu = true, nuan = true, nuo = true, nve = true,
    o = true, ou = true,
    pa = true, pai = true, pan = true, pang = true, pao = true, pei = true,
    pen = true, peng = true, pi = true, pian = true, piao = true, pie = true,
    pin = true, ping = true, po = true, pou = true, pu = true,
    qi = true, qia = true, qian = true, qiang = true, qiao = true, qie = true,
    qin = true, qing = true, qiong = true, qiu = true, qu = true, quan = true,
    que = true, qun = true,
    ran = true, rang = true, rao = true, re = true, ren = true, reng = true,
    ri = true, rong = true, rou = true, ru = true, rua = true, ruan = true,
    rui = true, run = true, ruo = true,
    sa = true, sai = true, san = true, sang = true, sao = true, se = true,
    sen = true, seng = true, sha = true, shai = true, shan = true, shang = true,
    shao = true, she = true, shen = true, sheng = true, shi = true,
    shou = true, shu = true, shua = true, shuai = true, shuan = true,
    shuang = true, shui = true, shun = true, shuo = true, si = true,
    song = true, sou = true, su = true, suan = true, sui = true, sun = true,
    suo = true,
    ta = true, tai = true, tan = true, tang = true, tao = true, te = true,
    teng = true, ti = true, tian = true, tiao = true, tie = true, ting = true,
    tong = true, tou = true, tu = true, tuan = true, tui = true, tun = true,
    tuo = true,
    wa = true, wai = true, wan = true, wang = true, wei = true, wen = true,
    weng = true, wo = true, wu = true,
    xi = true, xia = true, xian = true, xiang = true, xiao = true, xie = true,
    xin = true, xing = true, xiong = true, xiu = true, xu = true, xuan = true,
    xue = true, xun = true,
    ya = true, yan = true, yang = true, yao = true, ye = true, yi = true,
    yin = true, ying = true, yo = true, yong = true, you = true, yu = true,
    yuan = true, yue = true, yun = true,
    za = true, zai = true, zan = true, zang = true, zao = true, ze = true,
    zei = true, zen = true, zeng = true, zha = true, zhai = true, zhan = true,
    zhang = true, zhao = true, zhe = true, zhen = true, zheng = true, zhi = true,
    zhong = true, zhou = true, zhu = true, zhua = true, zhuai = true,
    zhuan = true, zhuang = true, zhui = true, zhun = true, zhuo = true, zi = true,
    zong = true, zou = true, zu = true, zuan = true, zui = true, zun = true,
    zuo = true,
}

-- Maximum syllable length (chuang / shuang / zhuang are 6).
local SYLLABLE_MAX = 6

-- Split *input* completely into syllables?  Memoised depth-first search: the
-- input is at most a dozen letters, so this stays far below a millisecond.
local function splits_into_pinyin(input)
    local n = #input
    if n == 0 then
        return false
    end
    local memo = {}
    local function walk(i)
        if i > n then
            return true
        end
        if memo[i] ~= nil then
            return memo[i]
        end
        local longest = math.min(SYLLABLE_MAX, n - i + 1)
        for len = longest, 1, -1 do
            if SYLLABLES[input:sub(i, i + len - 1)] and walk(i + len) then
                memo[i] = true
                return true
            end
        end
        memo[i] = false
        return false
    end
    return walk(1)
end

-- Short wubi codes (1-2 letters) collide with pinyin: "a" is a syllable and
-- "aa"/"an"/"ai" split cleanly, yet they are ordinary wubi level-1 and level-2
-- short codes.  Treat fewer than three letters as wubi whenever the candidate
-- set contains table candidates, which is what the table translator produces.
local SHORT_CODE_LIMIT = 3

-- Decide the input mode.
--
--   * an input listed in wubi_override.txt is always a wubi code
--   * a spelling that splits into legal pinyin syllables is pinyin
--   * a spelling that does not, but produced table candidates, is a wubi code
--   * anything else (no table candidates and not splittable, e.g. "abc") is
--     left as pinyin so the pinyin words still show up -- a wubi-only user
--     typing such a string has no table match anyway
local function looks_like_wubi(input, has_table_cand, has_phrase_cand)
    if input == "" then
        return false
    end
    -- A code the user listed in wubi_override.txt is wubi by definition.  This
    -- check has to come before the pinyin split: "yaa" (试) and "eee" (月) are
    -- legal wubi codes *and* legal pinyin spellings, and the split would send
    -- them to the pinyin side.
    if override_codes()[input] then
        return true
    end
    -- The single most reliable signal: a spelling splittable into legal pinyin
    -- syllables is pinyin.  This is checked first because a wubi code such as
    -- "wqiy" also happens to produce a few phrase candidates (乌齐雅); those
    -- must not flip the mode to pinyin and hide the real wubi result 你.
    if splits_into_pinyin(input) then
        return false
    end
    -- 1-2 letters that do not split cleanly: wubi level-1/level-2 short codes.
    if #input < SHORT_CODE_LIMIT then
        return has_table_cand
    end
    -- Not a pinyin spelling.  If the table translator matched, this is wubi.
    if has_table_cand then
        return true
    end
    -- Neither splittable nor a table hit (e.g. "abc"): show pinyin words if
    -- there are any, otherwise fall back to whatever is there.
    return not has_phrase_cand
end

-- ---------------------------------------------------------------------------
-- English gloss table
-- ---------------------------------------------------------------------------

local cache = {}
local cache_offset = 0
local fresh_size = -1
local last_request = nil
local last_service_check = 0
local last_cache_read = 0

local function log_debug(msg)
    if not DEBUG then
        return
    end
    local f = io.open(MAILBOX .. "/filter_debug.log", "a")
    if f then
        f:write(os.date("%Y-%m-%d %H:%M:%S ") .. msg .. "\n")
        f:close()
    end
end

local function lookup(text)
    return cache[text]
end

local function is_chinese(text)
    if not text or text == "" then
        return false
    end
    local ok, code = pcall(utf8.codepoint, text, 1, 1)
    if not ok or not code then
        return false
    end
    return code >= 0x4E00 and code <= 0x9FFF
end

local function load_cache()
    local now = os.time()
    if now == last_cache_read then
        return false
    end
    last_cache_read = now

    local f = io.open(CACHE_FILE, "rb")
    if not f then
        return false
    end
    local sz = f:seek("end")
    if sz < cache_offset then
        cache = {}
        cache_offset = 0
    end
    if sz == cache_offset then
        f:close()
        return false
    end
    f:seek("set", cache_offset)
    local offset = cache_offset
    local parsed = 0
    while parsed < MAX_LINES_PER_CALL do
        local line = f:read("*l")
        if not line then
            break
        end
        local next_offset = f:seek()
        line = line:gsub("\r$", "")
        local zh, en = line:match("^([^\t]+)\t(.+)$")
        if zh and en then
            cache[zh] = en
            offset = next_offset
            parsed = parsed + 1
        else
            break
        end
    end
    cache_offset = offset
    f:close()
    return parsed > 0
end

local function load_fresh()
    local f = io.open(FRESH_FILE, "rb")
    if not f then
        return
    end
    local sz = f:seek("end")
    if sz == fresh_size then
        f:close()
        return
    end
    fresh_size = sz
    f:seek("set", 0)
    for raw_line in f:lines() do
        local line = raw_line:gsub("\r$", "")
        local zh, en = line:match("^([^\t]+)\t(.+)$")
        if zh and en then
            cache[zh] = en
        end
    end
    f:close()
end

local function service_alive()
    local f = io.open(HEARTBEAT_FILE, "r")
    if not f then
        return false
    end
    local raw = f:read("*a")
    f:close()
    local ts = tonumber(raw)
    if not ts then
        return false
    end
    return (os.time() - ts) < 120
end

local function ensure_service()
    local now = os.time()
    if now - last_service_check < SERVICE_CHECK_INTERVAL then
        return
    end
    last_service_check = now
    if not service_alive() then
        log_debug("helper service heartbeat is stale (not launched from the IME thread)")
    end
end

local function request_translation(texts)
    local body = table.concat(texts, "\n")
    if body == "" or body == last_request then
        return
    end
    last_request = body
    local f = io.open(REQ_FILE, "w")
    if not f then
        return
    end
    f:write(body)
    f:close()
end

-- Rebuild a candidate with a comment, always "code, English".  The candidate's
-- input range must survive untouched (see the ShadowCandidate note in the
-- project docs): a hand-built range would break multi-segment compositions.
local function with_comment(cand, extra, code)
    local orig = cand["comment"] or ""
    if orig == "" then
        orig = code or ""
    end
    local merged
    if orig ~= "" then
        merged = orig .. ", " .. extra
    else
        merged = extra
    end
    local ok, new_cand = pcall(function()
        return ShadowCandidate(cand, cand["type"] or "table", cand["text"], merged)
    end)
    if ok and new_cand then
        return new_cand
    end
    log_debug("shadow_candidate unavailable, keep original: " .. tostring(cand["text"]))
    return cand
end

local filter = {}

-- Candidate types that carry no useful result for either mode.
local DROP_TYPES = { sentence = true, reverse_lookup = true }

-- Candidate types per mode.
--
-- librime distinguishes "from the dictionary" from "learned into the user's own
-- dictionary", and the learned entries have their own types:
--
--   table / completion       -- wubi dictionary
--   user_table               -- wubi entry learned from what the user typed
--   phrase                   -- pinyin dictionary
--   user_phrase              -- pinyin entry learned from what the user typed
--
-- Missing user_table here was a real bug: once the user had typed 一 by its
-- short code "g", 一 moved into the user dictionary and became a user_table
-- candidate, which this filter dropped -- so "g" started showing 开 (a mere
-- completion) instead of 一.
local function is_wubi_type(t)
    return t == "table" or t == "completion" or t == "user_table"
end

local function is_pinyin_type(t)
    return t == "phrase" or t == "user_phrase"
end

function filter.func(input, env)
    local ctx = env.engine.context
    local code = ctx.input or ""
    local head = {}
    local flushed = false
    local wubi_mode = nil
    -- When the chosen mode has no candidate at all (e.g. a schema without a
    -- pinyin translator, or a rare wubi char hidden by the charset filter),
    -- the menu falls back to *all* buffered candidates.  Tail filtering must
    -- be switched off too: otherwise the fallback shows the first page and
    -- silently drops every later wubi candidate (a pure wubi86 schema would
    -- lose everything after candidate 30).
    local mode_filtering = true

    local function flush_head()
        -- 1) decide the input mode from the candidate types we collected
        local has_table, has_phrase = false, false
        for _i, cand in ipairs(head) do
            local t = cand["type"] or ""
            if is_wubi_type(t) then
                has_table = true
            elseif is_pinyin_type(t) then
                has_phrase = true
            end
        end
        local mode = looks_like_wubi(code, has_table, has_phrase)
        wubi_mode = mode

        -- 2) keep only candidates that belong to this input mode
        local kept = {}
        for _i, cand in ipairs(head) do
            local t = cand["type"] or ""
            if not DROP_TYPES[t] then
                if mode then
                    if is_wubi_type(t) then
                        kept[#kept + 1] = cand
                    end
                else
                    if is_pinyin_type(t) then
                        kept[#kept + 1] = cand
                    end
                end
            end
        end
        if #kept == 0 then
            kept = head        -- never leave the menu empty
            mode_filtering = false
        end

        -- 3) English glosses for the candidates we keep
        if #code >= MIN_CODE_LEN then
            ensure_service()
            local missing = {}
            local seen = {}
            local count = 0
            for _i, cand in ipairs(kept) do
                local text = cand["text"]
                if count >= MAX_LOOKUP then
                    break
                end
                if text and #text >= 1 and #text <= MAX_LEN and is_chinese(text)
                    and not seen[text] then
                    seen[text] = true
                    count = count + 1
                    if not lookup(text) then
                        missing[#missing + 1] = text
                    end
                end
            end
            if #missing > 0 then
                load_fresh()
                local still = {}
                for _i, text in ipairs(missing) do
                    if not lookup(text) then
                        still[#still + 1] = text
                    end
                end
                if #still > 0 and load_cache() then
                    local still2 = {}
                    for _i, text in ipairs(still) do
                        if not lookup(text) then
                            still2[#still2 + 1] = text
                        end
                    end
                    still = still2
                end
                if #still > 0 then
                    request_translation(still)
                end
            end
        end

        for _i, cand in ipairs(kept) do
            local en = lookup(cand["text"])
            if en and en ~= "" then
                yield(with_comment(cand, en, code))
            else
                yield(cand)
            end
        end
    end

    -- Keep the wubi/pinyin split for the *whole* menu, not just the first
    -- PROCESS_LIMIT candidates: a wubi code such as \"trnt\" produces only two
    -- table candidates but dozens of pinyin phrases, and the phrases used to
    -- leak through the tail unfiltered.  Filtering here stays allocation-free
    -- per candidate, so the input thread never blocks.
    local function keep_in_mode(cand)
        if not mode_filtering then
            return true   -- no mode candidate survived; pass the rest through
        end
        local t = cand["type"] or ""
        if DROP_TYPES[t] then
            return false
        end
        if wubi_mode then
            return is_wubi_type(t)
        end
        return is_pinyin_type(t)
    end

    for cand in input:iter() do
        if #head < PROCESS_LIMIT then
            head[#head + 1] = cand
        else
            if not flushed then
                flush_head()
                flushed = true
            end
            if wubi_mode == nil or keep_in_mode(cand) then
                yield(cand)
            end
        end
    end
    if not flushed then
        flush_head()
    end
end

function filter.fini(_env)
    -- nothing to clean up
end

return { filter = filter }
