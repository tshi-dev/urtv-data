#!/usr/bin/env python3
"""tools/check_content.py: the files of content/ pass; each kind of mistake is caught."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
fails = []


def check(name, ok, detail=""):
    print(("PASS " if ok else "FAIL ") + name + ("" if ok else f"  [{detail}]"))
    if not ok:
        fails.append(name)


def run(files):
    with tempfile.TemporaryDirectory() as t:
        for k, v in files.items():
            (Path(t) / k).write_text(json.dumps(v, ensure_ascii=False), encoding="utf-8")
        return subprocess.run([sys.executable, str(ROOT / "tools/check_content.py"), t], capture_output=True, text=True)


r = subprocess.run([sys.executable, str(ROOT / "tools/check_content.py"), str(ROOT / "content")], capture_output=True, text=True)
check("content/ as it is passes", r.returncode == 0, r.stdout)
good = {
    "games-release.json": {"v": 1, "games": {"test-1": {"a": False, "b": False}}, "codes": []},
    "announcements.json": {"v": 1, "notices": [{"id": "eid-2027", "text": {"ar": "عيدكم مبارك", "en": "Eid Mubarak"}, "from": "2027-03-09", "to": "2027-03-12",
                                                "min_app": "4.3.3", "dismissible": True}]},
    "devices.json": {"v": 1, "devices": [{"id": "tcl-g07", "match": {"brand": "TCL", "device": "G07"}, "defaults": {"lite": True}, "why": "weak"}]},
    "seasonal.json": {"v": 1, "packs": [{"id": "ramadan", "name": {"ar": "رمضان", "en": "Ramadan"}, "from": "2027-02-08", "to": "2027-03-09",
                                          "url": "https://github.com/tshi-dev/UrTV/releases/download/photos-ramadan/ramadan.zip", "sha256": "a" * 64,
                                          "source": {"ar": "أنسبلاش", "en": "Unsplash"}, "count": 30, "bytes": 9000000,
                                          "license": {"name": "Unsplash License"}}]},
    "prayer-adjustments.json": {"v": 1, "adjustments": [{"id": "sa-isha-ramadan", "where": {"country": "SA"}, "from": "2027-02-08", "to": "2027-03-09",
                                                          "minutes": {"isha": 5}, "source": "Umm al-Qura calendar"}]},
    "sa-school.json": {"v": 1, "source": "https://ajel.sa/guide/school-calendar",
                       "breaks": [{"name": "إجازة الخريف", "from": "2026-11-20", "to": "2026-11-28"},
                                  {"name": "إجازة منتصف العام الدراسي", "from": "2027-01-08", "to": "2027-01-16"}]},
}
check("a full example passes", run(good).returncode == 0, run(good).stdout)
for what, change, want in [
    ("school: a break that ends first", lambda d: d["sa-school.json"]["breaks"][0].update({"to": "2026-11-01"}), "ends before it starts"),
    ("school: breaks out of order", lambda d: d["sa-school.json"]["breaks"].reverse(), "date order"),
    ("school: no Arabic name", lambda d: d["sa-school.json"]["breaks"][0].update({"name": "Autumn"}), "Arabic name"),
    ("school: no source link", lambda d: d["sa-school.json"].update({"source": "ajel"}), "https link"),
]:
    d = copy.deepcopy(good)
    change(d)
    r = run(d)
    check("caught: " + what, r.returncode == 1 and want in r.stdout, r.stdout)


def broken(name, path, value, want):
    d = copy.deepcopy(good)
    o = d[name]
    for k in path[:-1]:
        o = o[k]
    o[path[-1]] = value
    r = run(d)
    check(f"caught: {want}", r.returncode == 1 and want in r.stdout, r.stdout)


broken("announcements.json", ["notices", 0, "text", "ar"], "Eid", "text.ar")
broken("announcements.json", ["notices", 0, "text", "en"], "see https://x.example", "no links")
broken("announcements.json", ["notices", 0, "to"], "2027-03-01", "ends before it starts")
broken("announcements.json", ["notices", 0, "min_app"], "new", "min_app")
broken("devices.json", ["devices", 0, "match"], {"sdk_min": 30}, "never every TV")
broken("seasonal.json", ["packs", 0, "license"], {"name": "found on Google"}, "license.name")
broken("seasonal.json", ["packs", 0, "license"], {"name": "CC-BY-4.0"}, "license.credit")
broken("seasonal.json", ["packs", 0, "url"], "https://example.com/x.zip", "url")
broken("prayer-adjustments.json", ["adjustments", 0, "minutes"], {"isha": 30}, "minutes")
broken("prayer-adjustments.json", ["adjustments", 0, "minutes"], {"sunrise": 2}, "minutes")
broken("seasonal.json", ["packs", 0, "url"], "https://github.com/tshi-dev/UrTV/releases/download/photos-x/x.zip", "url")
broken("seasonal.json", ["packs", 0, "count"], 0, "count")
broken("prayer-adjustments.json", ["adjustments", 0, "where"], {"country": "Saudi"}, "where.country")
broken("prayer-adjustments.json", ["v"], 2, '"v": 1')
broken("games-release.json", ["games", "test-1", "a"], "2026-12-01", "UTC time")
broken("games-release.json", ["games", "test-1", "a"], True, "now, false")
broken("games-release.json", ["games", "test-1"], {"c": "now"}, "a and/or b only")
broken("games-release.json", ["games", "Bad Id"], {"a": False}, "an id")
broken("games-release.json", ["codes"], ["K7QF-2M9X"], "a record")
broken("games-release.json", ["games"], [], "object of game ids")
broken("games-release.json", ["v"], 2, '"v": 1')
broken("games-release.json", ["games", "test-1"], {"a": "now", "b": "now"}, "no definition")
# a game of the app's own list: on with no definition is fine, and a definition under its id is not
d = copy.deepcopy(good); d["games-release.json"]["games"]["maths"] = {"a": False, "b": "now"}
check("a held game of the app's own list can be switched on with no definition", run(d).returncode == 0, run(d).stdout)
d = copy.deepcopy(good); d["games-release.json"]["games"]["maths"] = {"a": "now"}; d["games-release.json"]["defs"] = {"maths": {}}
r = run(d); check("caught: a definition under the id of a game of the app's own list", r.returncode == 1 and "the app already has it" in r.stdout, r.stdout)
d = copy.deepcopy(good)
d["devices.json"]["devices"].append(copy.deepcopy(d["devices.json"]["devices"][0]))
check("caught: an id twice", "id twice" in run(d).stdout)

print(f"\n{len(fails)} failed" if fails else "\nall passed")
sys.exit(1 if fails else 0)
