--[[
rime-en-gloss -- show the English of every Chinese candidate in the comment slot

Result:

    1. 告诉     wjjg, to tell; to inform
    2. 东西     aiit, thing; stuff

The English goes into the candidate's *comment* slot (the grey text on the
right), which keeps selection behaviour untouched: pressing space still commits
the Chinese word, never the English.

Design rules that keep the host application responsive
------------------------------------------------------
The filter runs synchronously inside the input thread of whatever program you
are typing into (WeChat, Word, a browser...).  Anything slow here freezes that
program, so:

  * no C modules, no HTTP, no shelling out -- file reads only
  * the translation table is read incrementally, at most 40k lines per
    keystroke (~0.1 s measured), so the whole file becomes resident after a few
    keys while no single keystroke stalls
  * disk access happens only on a cache miss, at most once per second
  * only the first PROCESS_LIMIT candidates are inspected; the rest are streamed
    through untouched (a pinyin sentence can produce hundreds of candidates)
  * launching the optional helper service from here is deliberately NOT done:
    exec() inside the input thread is what made WeChat / Word freeze

Files (in the mailbox directory: %TEMP%\rime_argos on Windows,
$TMPDIR/rime_argos or /tmp/rime_argos elsewhere; override with the
RIME_EN_GLOSS_DIR environment variable):

    cache.txt         main table: "中文<TAB>English" per line (read-only for lua)
    fresh.txt         small rolling file with the newest translations
    request.txt       lua -> helper service: words to translate, one per line
    heartbeat.txt     helper service liveness (unix time); informational only
    filter_debug.log  written only when RIME_EN_GLOSS_DEBUG=1

Install: copy this file into <Rime user dir>\lua\ and add

    lua_filter@*input_text*filter

to the schema's engine/filters list, then redeploy Rime.
]]

-- Forward slashes work on Windows too and keep the path portable across
-- platforms; the temp directory name differs (%TEMP% on Windows, $TMPDIR or
-- /tmp elsewhere), so all of them are tried.
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

local MAX_LOOKUP = 6      -- translate at most this many candidates per page
local MAX_LEN = 12        -- skip long phrases (slow, and useless per keystroke)
local MIN_CODE_LEN = 1    -- also translate on a single keystroke (cache covers most)
local PROCESS_LIMIT = 30  -- inspect only the first N candidates; walking the
                          -- whole list froze the host application
local MAX_LINES_PER_CALL = 40000
local SERVICE_CHECK_INTERVAL = 300

local cache = {}
local cache_offset = 0      -- bytes of cache.txt already parsed
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

-- Incremental reader: parses only the bytes appended since last time, and at
-- most MAX_LINES_PER_CALL lines per call.
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
        cache = {}          -- the file was rewritten: start over
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
            break           -- half-written trailing line; pick it up next time
        end
    end
    cache_offset = offset
    f:close()
    return parsed > 0
end

-- The rolling "newest translations" file, so a word translated a moment ago
-- shows up on the very next keystroke instead of waiting for the incremental
-- reader to walk to the end of a multi-megabyte table.
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

-- Informational only: never start a process from here (see the header).
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

-- Rebuild a candidate with a comment, always "code, English".
-- Single characters carry no comment of their own, so fall back to the code the
-- user is currently typing and every row looks the same.
--
-- IMPORTANT: the candidate's input range (start/end) must survive untouched.
-- A multi-segment composition -- pinyin "lilinfei" (li|lin|fei) or a wubi
-- sentence -- produces candidates that each cover only PART of the input.
-- Recreating them with a hand-built range (Candidate("table", 0, #code, ...))
-- marks every candidate as covering the whole input, so selecting the first
-- character commits it alone and silently swallows the rest of the code
-- (typing a name like 李林菲 left only 李 on the screen). ShadowCandidate
-- wraps the original candidate, keeps its range and only replaces the comment.
-- If it is unavailable we keep the original candidate unmodified: a missing
-- English hint is far better than a broken composition.
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

-- Collect at most PROCESS_LIMIT candidates, then stream the remainder through.
function filter.func(input, env)
    local ctx = env.engine.context
    local code = ctx.input or ""
    local head = {}
    local flushed = false

    local function flush_head()
        if #code >= MIN_CODE_LEN then
            ensure_service()

            -- 1) memory-only lookup: the hot path never touches the disk
            local missing = {}
            local seen = {}
            local count = 0
            for _i, cand in ipairs(head) do
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

            -- 2) only a cache miss may read the file system
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

        for _i, cand in ipairs(head) do
            local en = lookup(cand["text"])
            if en and en ~= "" then
                yield(with_comment(cand, en, code))
            else
                yield(cand)
            end
        end
    end

    for cand in input:iter() do
        if #head < PROCESS_LIMIT then
            head[#head + 1] = cand
        else
            if not flushed then
                flush_head()
                flushed = true
            end
            yield(cand)
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
