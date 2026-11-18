#!/usr/bin/env python3
"""The rules of UrTV's games engine for a game definition (UrTV docs/GAME-ENGINE.md), in Python: the same limits, vocabulary and refusals as the app's GameDef.java, so a definition that
passes here is one the engine can run, and one that does not never gets published. A game that fails is not a game: the app keeps it hidden.

    python3 tools/engine_def.py GAME.json [...]      prints every problem (one line each) and exits 1 when there is one
Python standard library only. tests/engine_def_test.py holds the cases the app's own test (tests/GameEngineTest.java) holds."""
import json
import re
import sys

NAME_MAX, LINE_MAX, Q_MAX, OPT_MAX, ANS_MAX = 24, 70, 160, 40, 40
ITEMS_MAX, OPTS_MIN, OPTS_MAX, ANSWERS_MAX, PAIRS_MIN, PAIRS_MAX, ORDER_MIN = 200, 2, 6, 6, 3, 5, 3
ROUNDS = (3, 30); SECONDS = (5, 120); POINTS = (1, 10); PLAYERS_MAX = 10; TREE_MAX = 4000
BLOCKS = ["choose", "tf", "order", "word", "blank", "pairs", "odd", "closest", "draw", "buzz", "vote"]
SCORES = ["first", "all", "closest", "speed", "bank"]
ICONS = ["star", "heart", "circle", "square", "triangle", "diamond", "question", "check", "clock", "bulb", "flag", "drop"]
ACCENTS = ["saff", "ok", "pink", "deep", "ink"] + [f"side{i}" for i in range(10)]
ID = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
ARABIC = re.compile("[ء-يٱ]")
DIGIT = re.compile("[0-9٠-٩۰-۹]")
LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z ]*")


class Bad(Exception):
    pass


def clean(s, mx):
    """no control or direction-changing character, no «·» or «•», no link, not empty, not over mx characters, no space at an end"""
    if not isinstance(s, str) or not s or len(s) > mx or s != s.strip():
        return False
    for c in s:
        o = ord(c)
        if o < 0x20 or o == 0x7f or 0x200b <= o <= 0x200f or 0x202a <= o <= 0x202e or 0x2066 <= o <= 0x2069 or c == "﻿" or c in "·•":
            return False
    return "://" not in s and "www." not in s.lower()


def text(o, where, mx, digits_ok=False, required=True):
    if o is None:
        if required:
            raise Bad(f"{where}: missing")
        return None
    if isinstance(o, str):
        ar, en = o, ""
    elif isinstance(o, dict) and isinstance(o.get("ar"), str):
        ar, en = o["ar"], o.get("en", "")
        if o.get("en") is not None and not isinstance(en, str):
            raise Bad(f"{where}.en: a text")
        en = en or ""
    else:
        raise Bad(f"{where}: a text: a string or {{ar, en}}")
    if not clean(ar, mx):
        raise Bad(f"{where}.ar: empty, over {mx} characters, with a direction mark, a control character, a link, «·» or «•»")
    if not (ARABIC.search(ar) or (digits_ok and DIGIT.search(ar))):
        raise Bad(f"{where}.ar: no Arabic letters")
    if en and (not clean(en, mx) or ARABIC.search(en)):
        raise Bad(f"{where}.en: English only, within {mx} characters, no direction marks or links")
    return ar


def whole(o, where, lo, hi, default):
    if o is None:
        return default
    if isinstance(o, bool) or not isinstance(o, (int, float)) or o != int(o) or not lo <= o <= hi:
        raise Bad(f"{where}: a whole number {lo} to {hi}")
    return int(o)


def flag(o, where):
    if o is None:
        return False
    if not isinstance(o, bool):
        raise Bad(f"{where}: true or false")
    return o


def lst(o, where, lo, hi):
    if not isinstance(o, list) or not lo <= len(o) <= hi:
        raise Bad(f"{where}: a list of {lo} to {hi}")
    return o


def answers(o, where):
    for a in lst(o, where, 1, ANSWERS_MAX):
        if not (isinstance(a, str) and clean(a, ANS_MAX) and (ARABIC.search(a) or DIGIT.search(a) or LATIN_WORD.fullmatch(a))):
            raise Bad(f"{where}: answers: Arabic words, numbers or English words, within {ANS_MAX} characters")
    return o


def count(o, n):
    n[0] += 1
    if n[0] > TREE_MAX:
        raise Bad(f"file: too many values ({TREE_MAX} at most)")
    if isinstance(o, dict):
        for v in o.values():
            count(v, n)
    elif isinstance(o, list):
        for v in o:
            count(v, n)


def item(m, where):
    if not isinstance(m, dict):
        raise Bad(f"{where}: an object")
    t = m.get("t")
    if not (isinstance(t, str) and t in BLOCKS):
        raise Bad(f"{where}.t: not a block of the engine: {BLOCKS}")
    if m.get("h") is not None:
        text(m["h"], where + ".h", Q_MAX, False, False)
    if t in ("choose", "odd"):
        text(m.get("q"), where + ".q", Q_MAX)
        os_ = lst(m.get("o"), where + ".o", OPTS_MIN, OPTS_MAX)
        for i, o in enumerate(os_):
            text(o, f"{where}.o[{i}]", OPT_MAX, True)
        if whole(m.get("a"), where + ".a", 0, len(os_) - 1, -1) < 0:
            raise Bad(f"{where}.a: the number of the right option")
    elif t == "tf":
        text(m.get("q"), where + ".q", Q_MAX)
        if not isinstance(m.get("a"), bool):
            raise Bad(f"{where}.a: true or false")
    elif t == "order":
        text(m.get("q"), where + ".q", Q_MAX)
        for i, o in enumerate(lst(m.get("o"), where + ".o", ORDER_MIN, OPTS_MAX)):
            text(o, f"{where}.o[{i}]", OPT_MAX, True)
    elif t in ("word", "blank"):
        q = text(m.get("q"), where + ".q", Q_MAX)
        if t == "blank" and "___" not in q:
            raise Bad(f"{where}.q: a blank needs «___» in the Arabic")
        answers(m.get("a"), where + ".a")
    elif t == "pairs":
        text(m.get("q"), where + ".q", Q_MAX)
        for p in lst(m.get("p"), where + ".p", PAIRS_MIN, PAIRS_MAX):
            two = lst(p, where + ".p", 2, 2)
            text(two[0], where + ".p[0]", OPT_MAX, True)
            text(two[1], where + ".p[1]", OPT_MAX, True)
    elif t == "closest":
        text(m.get("q"), where + ".q", Q_MAX)
        a = m.get("a")
        if isinstance(a, bool) or not isinstance(a, (int, float)) or abs(a) > 1e12:
            raise Bad(f"{where}.a: a number (at most a trillion)")
        u = m.get("u")
        if u is not None and not (isinstance(u, str) and clean(u, 16) and ARABIC.search(u)):
            raise Bad(f"{where}.u: a unit in Arabic, 16 characters at most")
    elif t == "draw":
        text(m.get("w"), where + ".w", OPT_MAX)
    elif t == "buzz":
        text(m.get("q"), where + ".q", Q_MAX)
        if m.get("a") is not None:
            answers(m["a"], where + ".a")
    else:  # vote
        text(m.get("q"), where + ".q", Q_MAX)


def pack_items(tree):
    """the problems of a pack's file ({"v": 1, "items": [...]}); an empty list when it is good"""
    try:
        if not (isinstance(tree, dict) and tree.get("v") == 1 and not isinstance(tree.get("v"), bool)):
            raise Bad('pack: {"v": 1, "items": [...]}')
        count(tree, [0])
        for i, it in enumerate(lst(tree.get("items"), "pack.items", 1, ITEMS_MAX)):
            item(it, f"pack.items[{i}]")
        return []
    except Bad as e:
        return [str(e)]


def check_game(m):
    """the problems of a game definition; an empty list when the engine can run it"""
    try:
        if not isinstance(m, dict):
            raise Bad("game: an object")
        if m.get("v") != 1 or isinstance(m.get("v"), bool):
            raise Bad("game.v: 1")
        count(m, [0])
        if not (isinstance(m.get("id"), str) and ID.fullmatch(m["id"])):
            raise Bad("game.id: lower-case letters, digits and dashes, 2 to 40")
        text(m.get("name"), "game.name", NAME_MAX)
        text(m.get("line"), "game.line", LINE_MAX)
        if m.get("icon") is not None and m["icon"] not in ICONS:
            raise Bad(f"game.icon: one of {ICONS}")
        if m.get("look") is not None:
            if not isinstance(m["look"], dict):
                raise Bad("game.look: an object")
            if m["look"].get("accent") is not None and m["look"]["accent"] not in ACCENTS:
                raise Bad(f"game.look.accent: one of {ACCENTS}")
        flag(m.get("kids"), "game.kids"); flag(m.get("hints"), "game.hints")
        if m.get("players") is not None:
            p = m["players"]
            if not isinstance(p, dict):
                raise Bad("game.players: an object")
            lo = whole(p.get("min"), "game.players.min", 1, PLAYERS_MAX, 1); hi = whole(p.get("max"), "game.players.max", 1, PLAYERS_MAX, 8); flag(p.get("teams"), "game.players.teams")
            if lo > hi:
                raise Bad("game.players: min over max")
        whole(m.get("rounds"), "game.rounds", *ROUNDS, 8); whole(m.get("seconds"), "game.seconds", *SECONDS, 20); whole(m.get("points"), "game.points", *POINTS, 3)
        if m.get("score") is not None and m["score"] not in SCORES:
            raise Bad(f"game.score: one of {SCORES}")
        inline, packed = m.get("items") is not None, m.get("pack") is not None
        if inline == packed:
            raise Bad('game: either "items" or "pack", not both and not neither')
        if packed:
            if not (isinstance(m["pack"], str) and ID.fullmatch(m["pack"])):
                raise Bad("game.pack: a pack name: lower-case letters, digits and dashes")
        else:
            items = lst(m["items"], "game.items", 1, ITEMS_MAX)
            for i, it in enumerate(items):
                item(it, f"game.items[{i}]")
            if m.get("score") == "closest" and not any(it.get("t") == "closest" for it in items):
                raise Bad("game.score: «closest» scoring needs a «closest» block")
        return []
    except Bad as e:
        return [str(e)]


def main():
    bad = 0
    for f in sys.argv[1:]:
        try:
            d = json.load(open(f, encoding="utf-8"))
        except (OSError, ValueError) as e:
            print(f"FAIL {f}: not read: {e}"); bad += 1; continue
        for p in check_game(d):
            print(f"FAIL {f}: {p}"); bad += 1
    print(f"{bad} problems" if bad else "games: all good")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
