#!/usr/bin/env python3
"""tools/games_release.py and the release file's check: it makes a group key outside the repository, pass records that UrTV's GameCrypt opens, seals games for group B, switches games on and
off for the two groups, revokes and rekeys, and leaves a file that tools/check_content.py passes. Made-up games only; the codes are made for the test and thrown away."""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import games_release as gr  # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        fails.append(name)


with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    f = t / "games-release.json"; kf = t / "keys" / "group.key"
    shutil.copy(ROOT / "content/games-release.json", f)
    env = {**os.environ, "URTV_GAMES_RELEASE_FILE": str(f)}

    def tool(*a, inp=None):
        return subprocess.run([sys.executable, str(ROOT / "tools/games_release.py"), "--key-file", str(kf), *a], capture_output=True, text=True, input=inp, env=env)

    def data():
        d = json.loads(f.read_text(encoding="utf-8"))
        for k, v in (("games", {}), ("defs", {}), ("bdefs", {}), ("codes", [])): d.setdefault(k, v)
        return d
    def valid():
        d = t / "content"; d.mkdir(exist_ok=True)
        for src in (ROOT / "content").glob("*.json"): shutil.copy(src, d / src.name)
        shutil.copy(f, d / "games-release.json")
        r = subprocess.run([sys.executable, str(ROOT / "tools/check_content.py"), str(d)], capture_output=True, text=True)
        return r.returncode == 0, r.stdout

    check("the file as committed is empty (no game, no definition, no code) and passes the check", json.loads(f.read_text()) == {"v": 1, "games": {}, "codes": []} and valid()[0])
    check("«code» before «key» refuses (no group key): nothing is written", tool("code", "--add").returncode != 0 and data()["codes"] == [])
    r = tool("key")
    check("«key» makes the group key in the key file (mode 600), prints no key, and a second run keeps it", r.returncode == 0 and kf.is_file() and oct(kf.stat().st_mode & 0o777) == "0o600" and len(bytes.fromhex(kf.read_text().strip())) == 32 and kf.read_text().strip() not in r.stdout and "already" in tool("key").stdout)
    key = bytes.fromhex(kf.read_text().strip())
    r = tool("code")
    m = re.search(r"CODE \(shown once, never stored\):\s+([A-HJ-KM-NP-Z2-9]{6})\b", r.stdout); rec = re.search(r"record: (\S+)", r.stdout)
    check("«code» makes a random 6-sign code (A to Z without I, L, O, and 2 to 9), prints it once with its record, writes nothing", r.returncode == 0 and m and rec and data()["codes"] == [] and gr.RECORD.fullmatch(rec.group(1)), r.stdout + r.stderr)
    code = m.group(1)
    check("the record opens with its code (in any spelling) to the group key, and not with another code", gr.group_key_of(code, rec.group(1)) == key and gr.group_key_of(code.lower(), rec.group(1)) == key and gr.group_key_of(code[:3] + " " + code[3:], rec.group(1)) == key and gr.group_key_of(code[:-1] + ("A" if code[-1] != "A" else "B"), rec.group(1)) is None and gr.group_key_of("SHORT", rec.group(1)) is None)
    r2 = tool("code", "--add"); c2 = re.search(r"CODE \(shown once, never stored\):\s+(\S+)", r2.stdout).group(1)
    check("--add puts only the record in the file: neither code is anywhere in it, the group key is not either; the file passes the check", len(data()["codes"]) == 1 and c2 not in f.read_text() and key.hex() not in f.read_text() and valid()[0])
    check("«on --native» for a game of the app's own list needs no definition and writes {native: true, a, b}; «check» says it is on; «off» turns it off and keeps native",
          tool("on", "maths", "--native", "--b", "now").returncode == 0 and data()["games"]["maths"] == {"a": False, "b": "now", "native": True}
          and "maths" in tool("check").stdout and tool("off", "maths").returncode == 0 and data()["games"]["maths"] == {"a": False, "b": False, "native": True})
    check("«on» for such a game without --native, and --native for another id, are refused", tool("on", "maths", "--b", "now").returncode != 0 and tool("on", "test-1", "--native", "--a", "now").returncode != 0)
    tool("remove", "maths")
    check("«on» for a game with no definition is refused", tool("on", "test-1", "--a", "now").returncode != 0 and data()["games"] == {})
    ex = ROOT / "tests/engine-examples/test-1.json"; ex2 = ROOT / "tests/engine-examples/test-2.json"
    bad = t / "bad.json"; bad.write_text(json.dumps({"v": 1, "id": "test-9", "name": "اختبار", "line": "خطأ", "items": [{"t": "spin"}]}, ensure_ascii=False))
    check("«add» takes a game only after the engine's rules pass it; a game with an unknown block is refused and changes nothing", tool("add", str(bad)).returncode != 0 and data()["defs"] == {} and tool("add", str(ex)).returncode == 0 and "test-1" in data()["defs"] and data()["games"]["test-1"] == {"a": False, "b": False} and valid()[0])
    check("«seal» seals a game for group B: the file holds hex, not the game; it opens with the group key; the id must match; the file passes the check",
          tool("seal", "test-2", str(ex)).returncode != 0 and tool("seal", "test-2", str(ex2)).returncode == 0 and re.fullmatch(r"[0-9a-f]+", data()["bdefs"]["test-2"]) and "اختبار" not in json.dumps(data()["bdefs"], ensure_ascii=False)
          and json.loads(gr.open_sealed(key, data()["bdefs"]["test-2"]))["id"] == "test-2" and gr.open_sealed(b"\x01" * 32, data()["bdefs"]["test-2"]) is None and valid()[0])
    check("«on» sets the two times: test-1 for everyone now, test-2 for group B from a date; a bad time is refused", tool("on", "test-1", "--a", "now").returncode == 0 and tool("on", "test-2", "--b", "2026-12-01T00:00:00Z").returncode == 0 and tool("on", "test-2", "--b", "tomorrow").returncode != 0
          and data()["games"]["test-1"] == {"a": "now", "b": False} and data()["games"]["test-2"] == {"a": False, "b": "2026-12-01T00:00:00Z"} and valid()[0])
    c = tool("check", "--at", "2026-11-25T00:00:00Z").stdout
    check("«check» tells what each group has: test-1 for both, test-2 for nobody before its date, for group B after it", re.search(r"test-1\s+A on\s+B on", c) and re.search(r"test-2\s+A off\s+B off", c) and re.search(r"test-2\s+A off\s+B on", tool("check", "--at", "2026-12-02T00:00:00Z").stdout), c)
    d = data(); d["games"]["test-2"]["a"] = "now"; f.write_text(json.dumps(d, ensure_ascii=False))
    ok, out = valid()
    check("the check refuses a game on for everyone whose definition is sealed for group B only", not ok and "sealed for group B only" in out, out)
    d = data(); d["games"]["test-2"]["a"] = False; d["games"]["ghost"] = {"a": "now"}; f.write_text(json.dumps(d, ensure_ascii=False)); ok, out = valid()
    check("…and a game on with no definition", not ok and "no definition" in out, out)
    check("«off» and «remove» turn a game off and take it out", tool("off", "test-1").returncode == 0 and data()["games"]["test-1"] == {"a": False, "b": False} and tool("remove", "ghost").returncode == 0 and "ghost" not in data()["games"] and valid()[0])
    base = data()
    def broken(mut, want):
        d = copy.deepcopy(base); mut(d); f.write_text(json.dumps(d, ensure_ascii=False)); ok, out = valid(); f.write_text(json.dumps(base, ensure_ascii=False)); return (not ok) and want in out
    check("check: a definition with no source", broken(lambda d: d["defs"]["test-1"].pop("source"), "source"))
    check("check: a definition whose id is not its key", broken(lambda d: d["defs"].__setitem__("test-3", dict(d["defs"]["test-1"])) or d["games"].__setitem__("test-3", {"a": False, "b": False}), "id is not its key"))
    check("check: a definition the engine cannot run", broken(lambda d: d["defs"]["test-1"]["items"].append({"t": "spin"}), "not a game the engine can run"))
    check("check: a game both open and sealed", broken(lambda d: d["bdefs"].__setitem__("test-1", d["bdefs"]["test-2"]), "both open and sealed"))
    check("check: a bad record, a record twice, a number as a record", broken(lambda d: d["codes"].append("1:2000:zz:bad:x"), "codes[") and broken(lambda d: d["codes"].append(d["codes"][0]), "a record twice") and broken(lambda d: d["codes"].append(42), "codes["))
    check("check: a sealed value that is not hex, a sealed game the file does not list, a time that is not a UTC stamp, a game named with capitals", broken(lambda d: d["bdefs"].__setitem__("test-2", "not hex"), "sealed value") and broken(lambda d: d["bdefs"].__setitem__("zzz-9", d["bdefs"]["test-2"]), "does not list") and broken(lambda d: d["games"]["test-1"].__setitem__("a", "2026-12-01"), "UTC time") and broken(lambda d: d["games"].__setitem__("Bad Id", {"a": False}), "an id"))
    check("a code is exactly 6 signs of the alphabet: 5 or 7 signs, an I, an L, an O, a 0 or a 1 never open a record (even one made for them), and the record's rounds are 100000 to 1000000",
          gr.group_key_of(code[:5], rec.group(1)) is None and gr.group_key_of(code + "A", rec.group(1)) is None and all(gr.group_key_of(code[:5] + c, rec.group(1)) is None for c in "ILO01") and not gr.valid_code("ABCDE0") and not gr.valid_code("ABCDEI") and gr.valid_code("ABCD23")
          and tool("code", "--rounds", "99999").returncode != 0 and tool("code", "--rounds", "1000001").returncode != 0 and re.fullmatch(r"2:300000:.*", rec.group(1)) is not None)
    ra = tool("code", "--rounds", "100000"); recb = re.search(r"record: (\S+)", ra.stdout).group(1)
    check("--rounds sets the cost (100000 here, 300000 by default); a record is 2:rounds:salt:check:wrapped with a salt of its own each time", recb.startswith("2:100000:") and gr.group_key_of(re.search(r"CODE \(shown once, never stored\):\s+(\S+)", ra.stdout).group(1), recb) == key and recb.split(":")[2] != rec.group(1).split(":")[2])
    ask = tool("code", "--ask", inp="XYZ234\nXYZ234\n"); rk_ask = re.search(r"record: (\S+)", ask.stdout)
    check("«code --ask» takes a typed code (hidden) twice, prints only the record, never the code; a code of the wrong length, with an O, or typed twice differently is refused",
          ask.returncode == 0 and rk_ask and "XYZ234" not in ask.stdout and gr.group_key_of("xyz-234", rk_ask.group(1)) == key and tool("code", "--ask", inp="XYZ23\nXYZ23\n").returncode != 0 and tool("code", "--ask", inp="XYZ23O\nXYZ23O\n").returncode != 0 and tool("code", "--ask", inp="XYZ234\nXYZ235\n").returncode != 0)
    # revoke and rekey
    first = data()["codes"][0].split(":")[3][:8]
    check("«list» shows shortened hashes only, never a record or a code", first in tool("list").stdout and data()["codes"][0] not in tool("list").stdout and code not in tool("list").stdout and key.hex() not in tool("list").stdout)
    check("«revoke» removes exactly the record whose check hash starts with the given characters; none or several removes nothing", tool("revoke", "zzzz").returncode != 0 and len(data()["codes"]) == 1 and tool("revoke", first).returncode == 0 and data()["codes"] == [])
    tool("code", "--add"); keep = tool("code", "--add"); ckeep = re.search(r"CODE \(shown once, never stored\):\s+(\S+)", keep.stdout).group(1)
    old_sealed = data()["bdefs"]["test-2"]; before = len(data()["codes"])
    r = tool("rekey", "--keep", inp=ckeep + "\nNOTACODE12345\n\n")
    newkey = bytes.fromhex(kf.read_text().strip())
    check("«rekey --keep» makes a new group key and writes again only the codes that were given (and in the file): the others no longer open anything, every sealed game is sealed again under the new key",
          r.returncode == 0 and before == 2 and len(data()["codes"]) == 1 and newkey != key and gr.group_key_of(ckeep, data()["codes"][0]) == newkey and gr.group_key_of(code, data()["codes"][0]) is None and data()["bdefs"]["test-2"] != old_sealed
          and gr.open_sealed(key, data()["bdefs"]["test-2"]) is None and json.loads(gr.open_sealed(newkey, data()["bdefs"]["test-2"]))["id"] == "test-2" and valid()[0], r.stdout + r.stderr)
    check("«rekey» with no valid code to keep changes nothing", tool("rekey", "--keep", inp="WRONGCODE12345\n\n").returncode != 0 and bytes.fromhex(kf.read_text().strip()) == newkey and len(data()["codes"]) == 1)
    big = t / "big.json"; g = json.load(open(ex, encoding="utf-8")); g["id"] = "test-5"; g["items"] = [{"t": "choose", "q": "ما أكبر كوكب في المجموعة الشمسية كلها؟", "o": [{"ar": "الأرض", "en": "Earth"}, {"ar": "المشتري", "en": "Jupiter"}, {"ar": "المريخ", "en": "Mars"}, {"ar": "زحل", "en": "Saturn"}], "a": 1}] * 90
    big.write_text(json.dumps(g, ensure_ascii=False))
    for i in range(3):
        g2 = dict(g, id=f"test-{i + 6}"); big.write_text(json.dumps(g2, ensure_ascii=False)); r = tool("add", str(big))
    check("a file over 60000 bytes is refused by the tool before it is written (the app reads 64 KB at most)", r.returncode != 0 and "60000" in (r.stdout + r.stderr) and len(f.read_bytes()) <= 60000, r.stdout + r.stderr)
    d = data(); keepcodes = list(d["codes"]); d["codes"] = [f"2:100000:{i:032x}:{'ab' * 32}:{'cd' * 60}" for i in range(30)]
    f.write_text(json.dumps(d, ensure_ascii=False))
    check("30 records at most: «code --add» refuses the 31st (every TV pays the slow part once per record), and the check refuses a file with 31", tool("code", "--add").returncode != 0 and len(data()["codes"]) == 30 and valid()[0])
    d["codes"].append(f"2:100000:{31:032x}:{'ab' * 32}:{'cd' * 60}"); f.write_text(json.dumps(d, ensure_ascii=False)); ok31, out31 = valid()
    check("…and a file with 31 records fails the check", not ok31 and "30 records" in out31, out31)
    d["codes"] = keepcodes; f.write_text(json.dumps(d, ensure_ascii=False))
    check("nothing the tool wrote holds a code, the group key or a key file path", set(data()) <= {"v", "games", "defs", "bdefs", "codes"} and newkey.hex() not in f.read_text() and key.hex() not in f.read_text() and ckeep not in f.read_text())

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
