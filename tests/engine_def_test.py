#!/usr/bin/env python3
"""tools/engine_def.py: the engine's rules for a game definition, the same cases UrTV's tests/GameEngineTest.java holds (made-up games only). A game that fails is not a game."""
import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import engine_def as E  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        fails.append(name)


CHOOSE = {"t": "choose", "q": "ما أكبر كوكب؟", "o": ["الأرض", "المشتري", "المريخ"], "a": 1}


def game(extra=None, items=None):
    g = {"v": 1, "id": "test-1", "name": {"ar": "اختبار ١", "en": "Test 1"}, "line": "لعبة تجريبية صغيرة", "rounds": 3, "items": items if items is not None else [copy.deepcopy(CHOOSE)]}
    g.update(extra or {})
    return g


def ok(g): return E.check_game(g) == []
def refused(g, want=None):
    r = E.check_game(g)
    return bool(r) and (want is None or want in r[0])


for f in sorted((ROOT / "tests/engine-examples").glob("*.json")):
    check(f"example {f.name} is a game the engine can run", ok(json.load(open(f, encoding="utf-8"))), E.check_game(json.load(open(f, encoding="utf-8"))))
every = [CHOOSE, {"t": "tf", "q": "الشمس نجم؟", "a": True}, {"t": "odd", "q": "من الغريب؟", "o": ["قطة", "كلب", "طاولة"], "a": 2}, {"t": "order", "q": "رتب", "o": ["أولا", "ثانيا", "ثالثا"]},
         {"t": "word", "q": "عاصمة مصر؟", "a": ["القاهرة", "Cairo"]}, {"t": "blank", "q": "الشمس ___ في الشرق", "a": ["تشرق"]}, {"t": "pairs", "q": "طابق", "p": [["قطة", "مواء"], ["كلب", "نباح"], ["بقرة", "خوار"]]},
         {"t": "closest", "q": "كم يوما في السنة؟", "a": 365, "u": "يوم"}, {"t": "draw", "w": {"ar": "شجرة", "en": "tree"}}, {"t": "buzz", "q": "من أسرع؟"}, {"t": "vote", "q": "من الأكثر ضحكا؟"}]
check("every one of the 11 blocks passes", ok(game(items=every)) and len(E.BLOCKS) == 11)
check("the vocabulary is the app's: 11 blocks, 5 scores, 12 icons, 15 accents", (len(E.BLOCKS), len(E.SCORES), len(E.ICONS), len(E.ACCENTS)) == (11, 5, 12, 15))
check("unknown block = not a game; the reason says where", refused(game(items=[{"t": "spin", "q": "س"}]), "game.items[0].t") and refused(game(items=[{"q": "س"}])) and refused(game(items=[{"t": 5}])) and refused(game(items=[CHOOSE, {"t": "native-code"}])))
check("version and id", refused(game({"v": 2})) and refused(game({"id": "Test 1"})) and refused(game({"id": "x"})) and refused(game({"id": "a" * 41})) and ok(game({"id": "a" * 40})))
check("Arabic is required (an option may be a number); the English is English only", refused(game({"name": {"ar": "Test"}})) and refused(game({"line": "a small game"})) and refused(game(items=[{"t": "tf", "q": "Is the sun a star?", "a": True}]))
      and ok(game(items=[{"t": "choose", "q": "كم؟", "o": ["١٢٠", "150"], "a": 0}])) and refused(game(items=[{"t": "choose", "q": "كم؟", "o": ["abc", "x"], "a": 0}])) and refused(game({"name": {"ar": "اختبار", "en": "اختبار"}})) and refused(game({"name": {"ar": "اختبار", "en": "see http://x.y"}})))
bad = lambda q: refused(game(items=[{"t": "choose", "q": q, "o": ["ا", "ب"], "a": 0}]))
check("unsafe text: a direction mark, a control character, zero-width, «·», «•», a link, a space at an end, empty", bad("‫ما أكبر") and bad("‏ما أكبر") and bad("ما\u0007 أكبر") and bad("ما · أكبر") and bad("ما • أكبر") and bad("ما أكبر www.x.com") and bad(" ما أكبر") and bad(""))
check("size limits: a question 160, an option 40, a name 24, a line 70", ok(game(items=[dict(CHOOSE, q="ب" * 160)])) and refused(game(items=[dict(CHOOSE, q="ب" * 161)])) and refused(game(items=[dict(CHOOSE, o=["ب" * 41, "ا"])])) and refused(game({"name": "ب" * 25})) and refused(game({"line": "ب" * 71})) and ok(game({"line": "ب" * 70})))
check("200 items are fine, 201 are not; a file over 4000 values is refused", ok(game(items=[{"t": "tf", "q": "سؤال", "a": True}] * 200)) and refused(game(items=[{"t": "tf", "q": "سؤال", "a": True}] * 201))
      and refused(game(items=[{"t": "choose", "q": {"ar": "سؤال", "en": "q"}, "o": [{"ar": "جواب", "en": "a"}] * 6, "a": 0}] * 200), "too many values"))
check("options 2 to 6 and the right number in range", ok(game(items=[dict(CHOOSE, o=["ا", "ب"])])) and refused(game(items=[dict(CHOOSE, o=["ا"])])) and refused(game(items=[dict(CHOOSE, o=["ا"] * 7)])) and refused(game(items=[dict(CHOOSE, a=3)])) and refused(game(items=[{k: v for k, v in CHOOSE.items() if k != "a"}])) and refused(game(items=[dict(CHOOSE, a=1.5)])))
check("a blank needs ___; order 3 to 6; pairs 3 to 5 of two; closest a number; a word needs answers",
      refused(game(items=[{"t": "blank", "q": "بلا فراغ", "a": ["س"]}])) and refused(game(items=[{"t": "order", "q": "رتب", "o": ["ا", "ب"]}])) and refused(game(items=[{"t": "pairs", "q": "طابق", "p": [["ا", "ب"], ["ت", "ث"]]}]))
      and refused(game(items=[{"t": "pairs", "q": "طابق", "p": [["ا", "ب", "ج"], ["ت", "ث"], ["ح", "خ"]]}])) and refused(game(items=[{"t": "closest", "q": "كم", "a": "365"}])) and refused(game(items=[{"t": "word", "q": "س", "a": []}])))
check("numbers: rounds 3 to 30, seconds 5 to 120, points 1 to 10, players 1 to 10 min not over max; score, icon, accent from the lists; flags are booleans",
      refused(game({"rounds": 2})) and refused(game({"rounds": 31})) and refused(game({"seconds": 4})) and refused(game({"seconds": 121})) and refused(game({"points": 11})) and refused(game({"points": 0})) and refused(game({"players": {"min": 4, "max": 2}})) and refused(game({"players": {"max": 11}}))
      and refused(game({"icon": "skull"})) and ok(game({"icon": "heart", "look": {"accent": "side7"}})) and refused(game({"look": {"accent": "#ff0000"}})) and refused(game({"score": "closest"})) and refused(game({"score": "magic"})) and refused(game({"kids": 1})) and refused(game({"players": {"teams": 2}})))
check("a game has items or a pack, never both and never neither; a pack's own items are checked as strictly",
      ok({"v": 1, "id": "test-2", "name": "اختبار ٢", "line": "من حزمة", "pack": "test-pack"}) and refused(game({"pack": "x-pack"})) and refused({"v": 1, "id": "test-2", "name": "اختبار ٢", "line": "من حزمة"})
      and E.pack_items({"v": 1, "items": [CHOOSE]}) == [] and E.pack_items({"v": 1, "items": [{"t": "nope"}]}) != [] and E.pack_items({"v": 2, "items": []}) != [])
check("a text may be {ar, en} or a plain string; an {en} alone is refused; a hint is a text", ok(game(items=[dict(CHOOSE, q={"ar": "ما أكبر كوكب؟", "en": "Which planet is biggest?"})])) and refused(game(items=[dict(CHOOSE, q={"en": "x"})])) and ok(game(items=[dict(CHOOSE, h="تلميح صغير")])))
check("a game's JSON that is not an object, or has a bool where a number is wanted, is refused", refused([1]) and refused(game({"rounds": True}), "game.rounds") and refused(game(items=[dict(CHOOSE, a=True)])))

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
