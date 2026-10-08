# -*- coding: utf-8 -*-
"""
Optional local translation helper for rime-en-gloss.

This program is NOT required.  The lua filter shows English for everything in
cache.txt, which build_cache.py generates from CC-CEDICT offline.  Run this only
if you want English for long-tail words (>= 3 characters) that the dictionary
does not contain: it translates them with a local neural model and appends the
results to the same table.

Nothing leaves the machine and no API key is involved.

Two channels:
  1. File mailbox (primary) -- zero latency for lua, no subprocess, no console flash
         lua  writes  <mailbox>/request.txt   (one Chinese word per line)
         svc  appends translations to
         svc  writes  <mailbox>/cache.txt     ("中文<TAB>English" per line)
  2. HTTP API (optional) -- DeepLX compatible, handy for manual testing
         POST http://127.0.0.1:1188/translate

Requirements: pip install ctranslate2 sentencepiece flask
Model: run fetch_mt_model.py first.

    python optional_mt_server.py --no-http        # mailbox only (recommended)
"""
import argparse
import json
import logging
import os
import re
import threading
import time

from flask import Flask, jsonify, request

import ctranslate2
import sentencepiece as spm

HERE = os.path.dirname(os.path.abspath(__file__))

#: Model folder and CC-CEDICT can be overridden with the environment variables.
DEFAULT_MODEL_ROOT = os.environ.get("RIME_EN_GLOSS_MODEL") or os.path.join(HERE, "models", "zh_en")


def _find_cedict():
    candidates = [
        os.environ.get("RIME_EN_GLOSS_CEDICT"),
        os.path.join(HERE, os.pardir, "data", "cedict.json"),
        os.path.join(HERE, "data", "cedict.json"),
        os.path.join(HERE, "models", "cedict.json"),
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return candidates[1]


CEDICT_FILE = _find_cedict()

#: The lua side uses the same directory (RIME_EN_GLOSS_DIR on the lua side).
MAILBOX = os.environ.get("RIME_EN_GLOSS_DIR") or os.path.join(os.environ.get("TEMP", "."), "rime_argos")
REQ_FILE = os.path.join(MAILBOX, "request.txt")
CACHE_FILE = os.path.join(MAILBOX, "cache.txt")
EXTRA_FILE = os.path.join(MAILBOX, "cache_extra.txt")
FRESH_FILE = os.path.join(MAILBOX, "fresh.txt")
HEARTBEAT_FILE = os.path.join(MAILBOX, "heartbeat.txt")
LOG_FILE = os.path.join(MAILBOX, "service.log")
POLL_INTERVAL = 0.05
MAX_CACHE_LINES = 200000
BATCH_PER_TICK = 8
FRESH_MAX = 600          # rolling window of recently translated words

app = Flask(__name__)
logging.getLogger("werkzeug").setLevel(logging.ERROR)

_state = {"translator": None, "sp": None, "ready": False, "error": None}
_cedict = {}
_lock = threading.Lock()
_cache = {}
_fresh = []


def log(msg):
    """Append a line to the service log (pythonw has no console)."""
    try:
        os.makedirs(MAILBOX, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write("%s %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass
    try:
        print(msg, flush=True)
    except Exception:
        pass


# ---------------------------------------------------------------- model + dict

def find_paths(root):
    ct2_dir, spm_path = None, None
    for dirpath, _dirnames, filenames in os.walk(root):
        if ct2_dir is None and "model.bin" in filenames:
            ct2_dir = dirpath
        for name in filenames:
            if spm_path is None and name.lower().endswith(".model"):
                spm_path = os.path.join(dirpath, name)
    return ct2_dir, spm_path


def load_model(root):
    ct2_dir, spm_path = find_paths(root)
    if not ct2_dir or not spm_path:
        raise RuntimeError("model files not found under %s" % root)
    translator = ctranslate2.Translator(ct2_dir, device="cpu", compute_type="int8",
                                        inter_threads=1, intra_threads=2)
    sp = spm.SentencePieceProcessor(model_file=spm_path)
    return translator, sp


def load_cedict():
    global _cedict
    if not os.path.exists(CEDICT_FILE):
        log("cedict not found: %s" % CEDICT_FILE)
        return
    with open(CEDICT_FILE, "r", encoding="utf-8") as fh:
        _cedict = json.load(fh)
    log("cedict loaded: %d entries" % len(_cedict))


NOISE_PREFIXES = (
    "cl:", "see ", "variant of", "old variant", "abbr. for", "used in",
    "also written", "erhua variant", "surname ", "prefix used", "taiwan pr.",
    "classifier for", "(bound form)", "dialectal", "archaic", "literary",
    "for 屏", "for 於", "for 惡", "for 勝",
)


def dict_lookup(word):
    """Best clean English gloss, or None.

    Delegates to :mod:`glossary`, which resolves "variant of" chains, scores
    every candidate sense against a common-English word list (so 告诉 picks
    "to tell" instead of "to press charges") and applies the hand-checked
    override tables for everything people actually type.
    """
    try:
        import glossary
    except Exception:                                 # pragma: no cover
        return None
    raw = glossary.best_gloss(word, _cedict)
    if len(word) == 1:
        return glossary.refine_char(word, raw)
    return glossary.refine_word(word, raw)


#: Sentences the neural model produces for dictionary-less fragments
#: ("人不 -> No, no, no", "一大 -> A big one").  Those are worse than showing
#: nothing, so they are rejected.
MODEL_NOISE_RE = re.compile(
    r"(^[A-Z])|(^|\s)(i|i'm|i'd|i'll|you|you're|we|we're|they're|he's|she's|it's|"
    r"don't|can't|didn't|wouldn't|no,|yeah|okay|here you go|nothing|somebody|"
    r"someone|anybody|everybody|gonna|wanna)(\s|$|')", re.I)


def model_ok(text, gloss):
    """Reject machine output that is really a sentence, not a translation."""
    if not gloss:
        return False
    if len(gloss) > 60 or len(gloss.split()) > 8:
        return False
    if gloss[-1:] in "!?." or ".." in gloss or "," in gloss:
        return False
    if MODEL_NOISE_RE.search(gloss):
        return False
    if gloss != gloss.lower():
        return False
    return True


def translate_word(text):
    """Dictionary first, model as a last resort.

    The model is only consulted for words of three characters or more: for
    single characters and two-character words the dictionary plus the
    hand-checked tables are reliable, and the model produced visible nonsense
    there (化 -> "Zoom", 就能 -> "Yeah").
    """
    gloss = dict_lookup(text)
    if gloss:
        return gloss
    if len(text) < 3:
        return None
    candidate = model_translate(text)
    return candidate if model_ok(text, candidate) else None


def model_translate(text):
    tokens = _state["sp"].encode(text, out_type=str)
    results = _state["translator"].translate_batch([tokens], beam_size=1)
    if not results or not results[0].hypotheses:
        return None
    out = _state["sp"].decode(results[0].hypotheses[0])
    out = out.replace("\u2581", " ").strip()
    # a short gloss should not come back with a trailing full stop
    if len(text) <= 8 and len(out) <= 32 and out.endswith((".", "\u3002", "!")):
        out = out[:-1].strip()
    return out or None


# ---------------------------------------------------------------- cache file

def load_cache_file():
    """Load the loaded-by-lua cache plus the overflow file (long tail)."""
    for path in (CACHE_FILE, EXTRA_FILE):
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.rstrip("\n")
                    if "\t" not in line:
                        continue
                    zh, en = line.split("\t", 1)
                    if zh:
                        _cache[zh] = en
        except Exception as exc:
            log("cache load failed (%s): %s" % (os.path.basename(path), exc))


def append_cache_line(zh, en):
    """Append to the long-term cache and refresh the small 'fresh' file.

    The fresh file matters: the lua side reads the big cache incrementally from
    the start, so a word appended at the end would not be visible for a long
    time. fresh.txt is small and re-read whole, making new translations
    available on the very next keystroke.
    """
    os.makedirs(MAILBOX, exist_ok=True)
    row = (zh.replace("\t", " ").replace("\n", " "),
           en.replace("\t", " ").replace("\n", " "))
    with open(CACHE_FILE, "a", encoding="utf-8") as fh:
        fh.write("%s\t%s\n" % row)
    _fresh.append(row)
    if len(_fresh) > FRESH_MAX:
        _fresh[:] = _fresh[-FRESH_MAX:]
    try:
        with open(FRESH_FILE, "w", encoding="utf-8") as fh:
            for z, e in _fresh[-200:]:
                fh.write("%s\t%s\n" % (z, e))
    except Exception as exc:
        log("fresh write failed: %s" % exc)


def trim_cache():
    if len(_cache) <= MAX_CACHE_LINES:
        return
    try:
        items = list(_cache.items())[-MAX_CACHE_LINES:]
        with open(CACHE_FILE, "w", encoding="utf-8") as fh:
            for zh, en in items:
                fh.write("%s\t%s\n" % (zh, en))
    except Exception as exc:
        log("cache trim failed: %s" % exc)


# ---------------------------------------------------------------- loops

def heartbeat_loop():
    while True:
        try:
            with open(HEARTBEAT_FILE, "w", encoding="utf-8") as fh:
                fh.write(str(int(time.time())))
        except Exception:
            pass
        time.sleep(30)


def read_request_lines():
    try:
        with open(REQ_FILE, "r", encoding="utf-8") as fh:
            raw = fh.read()
    except Exception:
        return []
    return [w.strip() for w in raw.split("\n") if w.strip()]


def mailbox_loop():
    os.makedirs(MAILBOX, exist_ok=True)
    if not os.path.exists(CACHE_FILE):
        open(CACHE_FILE, "a", encoding="utf-8").close()
    load_cache_file()
    log("mailbox ready: %s | cached: %d" % (MAILBOX, len(_cache)))
    while True:
        time.sleep(POLL_INTERVAL)
        if not _state["ready"]:
            continue
        words = read_request_lines()
        if not words:
            continue
        todo = [w for w in words if w not in _cache][:BATCH_PER_TICK]
        for word in todo:
            try:
                with _lock:
                    out = translate_word(word)
                if out:
                    _cache[word] = out
                    append_cache_line(word, out)
                    log("translated %s -> %s" % (word, out))
            except Exception as exc:
                log("translate failed for %r: %s" % (word, exc))
        if len(_cache) > MAX_CACHE_LINES:
            trim_cache()


# ---------------------------------------------------------------- http api

@app.route("/translate", methods=["POST"])
def translate_http():
    try:
        if not _state["ready"]:
            return jsonify({"code": 503, "message": _state["error"] or "model loading"})
        data = request.get_json(force=True, silent=True) or {}
        text = (data.get("text") or "").strip()
        if not text:
            return jsonify({"code": 400, "message": "empty text"})
        if text in _cache:
            out = _cache[text]
        else:
            with _lock:
                out = translate_word(text)
            if out:
                _cache[text] = out
                append_cache_line(text, out)
        return jsonify({"code": 200, "id": 0, "data": out, "alternatives": [out]})
    except Exception as exc:
        return jsonify({"code": 500, "message": str(exc)})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"ok": True, "ready": _state["ready"], "error": _state["error"],
                    "cached": len(_cache), "dict": len(_cedict)})


def background_load(root):
    try:
        load_cedict()
        translator, sp = load_model(root)
        _state.update({"translator": translator, "sp": sp, "ready": True, "error": None})
        log("model loaded OK")
    except Exception as exc:
        _state["error"] = str(exc)
        log("model load FAILED: %s" % exc)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=1188)
    parser.add_argument("--model", default=DEFAULT_MODEL_ROOT)
    parser.add_argument("--no-http", action="store_true")
    args = parser.parse_args()

    threading.Thread(target=background_load, args=(args.model,), daemon=True).start()
    threading.Thread(target=mailbox_loop, daemon=True).start()
    threading.Thread(target=heartbeat_loop, daemon=True).start()

    if args.no_http:
        while True:
            time.sleep(3600)
    else:
        try:
            app.run(host="127.0.0.1", port=args.port, threaded=True)
        except Exception as exc:
            # e.g. port already taken by another instance -- keep serving the
            # mailbox instead of dying (lua only uses the file channel)
            log("http server unavailable (%s); running mailbox-only" % exc)
            while True:
                time.sleep(3600)
