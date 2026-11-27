#!/usr/bin/env python3
"""The owner's tool for UrTV's remote games release (UrTV docs/GAMES-RELEASE.md): edits content/games-release.json, which content.yml checks and publishes as release/games.json.

  Games
    on ID [--a WHEN] [--b WHEN] [--native]   --native: a game of the app's own list (no definition); WHEN is now, a UTC time 2026-12-01T00:00:00Z, or off; a = everyone, b = group B; the game must have a definition (add GAME.json) or a sealed one
    off ID                           off for both groups
    add GAME.json                    puts the game's definition in the file for everyone («defs»), after the engine's rules (tools/engine_def.py) passed it
    seal ID GAME.json                puts it in the file for group B only («bdefs»), sealed with the group key (AES-256-GCM)
    remove ID                        takes a game out of the file altogether
    check [--at TIME]                what is on for each group at a time (now by default)
  The pass (group B)
    key                              makes the group key (32 random bytes) in the key file if there is none; never printed
    code [--add] [--ask] [--rounds N]   a pass code of exactly 6 signs (A to Z without I, L, O, and 2 to 9): made at random and shown ONCE (never stored), or with --ask one you type (hidden);
                                     prints the record for «codes» (--add pastes it); the record holds a check and the group key wrapped by the code, behind N rounds of PBKDF2
                                     (default 300000, 100000 to 1000000; a TV pays them once per record). 30 records at most. A 6-sign code is weak against guessing from the public file: the rounds are what slow it
    revoke HASH                      removes the record whose check hash starts with HASH (see «list»); to make a revoked TV's key useless for later files run «rekey»
    list                             the records, shortened, and what is in the file
    rekey --keep                     a NEW group key: asks (hidden) for the codes that stay, one at a time, writes their records again and seals every game again

The key file is outside the repository: --key-file, else $URTV_GAMES_KEY_FILE, else ~/.config/urtv-games/group.key (mode 600). It is the only secret and it is never printed or committed.
Nothing is pushed: commit content/games-release.json to main and content.yml checks and publishes it. Needs the «cryptography» package for seal, code and rekey."""
import argparse
import datetime as dt
import getpass
import hashlib
import json
import os
import re
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import engine_def  # noqa: E402

FILE = Path(os.environ.get("URTV_GAMES_RELEASE_FILE") or Path(__file__).resolve().parent.parent / "content" / "games-release.json")
WHEN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
ID = re.compile(r"[a-z0-9][a-z0-9-]{1,39}")
ROUNDS, ROUNDS_MIN, ROUNDS_MAX, SALT_BYTES, CODE_LEN, KEY_BYTES, IV_BYTES = 300_000, 100_000, 1_000_000, 16, 6, 32, 12
ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"   # A to Z without I, L and O, and the digits 2 to 9: 31 signs, nothing that can be read as another
CODES_MAX = 30
RECORD = re.compile(r"2:(\d{6,7}):([0-9a-f]{16,64}):([0-9a-f]{64}):([0-9a-f]{%d})" % ((IV_BYTES + KEY_BYTES + 16) * 2))
FILE_MAX = 60_000   # the app reads 64 KB at most


def hidden(prompt):
    """A code typed by a person is read hidden from the terminal (getpass). A code piped in (the tests, a script) is read from stdin, never echoed and never printed:
    getpass prefers /dev/tty whenever the process has one, so on a CI runner (Python 3.14) it read the terminal instead of the pipe, or could not turn echo off, and every
    code came back empty. The prompt goes to stderr; end of input gives an empty code, which ends a list as before."""
    if sys.stdin.isatty(): return getpass.getpass(prompt)
    sys.stderr.write(prompt); sys.stderr.flush()
    return sys.stdin.readline().rstrip("\r\n")


def normalize(code):
    """what the app does with a typed code: Arabic-Indic and Persian digits as Latin, upper case, letters and digits only"""
    out = []
    for c in code:
        if "٠" <= c <= "٩": c = chr(ord("0") + ord(c) - ord("٠"))
        elif "۰" <= c <= "۹": c = chr(ord("0") + ord(c) - ord("۰"))
        c = c.upper()
        if ("A" <= c <= "Z") or ("0" <= c <= "9"): out.append(c)
    return "".join(out)


def valid_code(n):
    """exactly CODE_LEN signs of the alphabet (the code is already normalised)"""
    return len(n) == CODE_LEN and all(c in ALPHABET for c in n)


def derive(code, salt, rounds, purpose):
    """the slow part once, PBKDF2-HMAC-SHA256 of the normalised code with the record's own random salt, then a name by HMAC («check» or «wrap»): UrTV's GameCrypt.derive"""
    import hmac
    master = hashlib.pbkdf2_hmac("sha256", normalize(code).encode("utf-8"), salt, rounds, KEY_BYTES)
    return hmac.new(master, purpose.encode(), hashlib.sha256).digest()


def aesgcm():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError:
        sys.exit("the «cryptography» package is needed for this (pip install cryptography)")
    return AESGCM


def seal(key, plain, iv=None):
    """iv + ciphertext + tag, hex: UrTV's GameCrypt.seal"""
    iv = iv or secrets.token_bytes(IV_BYTES)
    return (iv + aesgcm()(key).encrypt(iv, plain, None)).hex()


def open_sealed(key, sealed_hex):
    try:
        b = bytes.fromhex(sealed_hex)
        return aesgcm()(key).decrypt(b[:IV_BYTES], b[IV_BYTES:], None)
    except Exception:
        return None


def record(code, group_key, salt=None, rounds=ROUNDS, iv=None):
    salt = salt if salt is not None else secrets.token_bytes(SALT_BYTES)
    return f"2:{rounds}:{salt.hex()}:{derive(code, salt, rounds, 'check').hex()}:{seal(derive(code, salt, rounds, 'wrap'), group_key, iv)}"


def group_key_of(code, rec):
    """the group key a code opens in a record, or None: what the app does"""
    m = RECORD.fullmatch(rec)
    if not m or not valid_code(normalize(code)) or not ROUNDS_MIN <= int(m.group(1)) <= ROUNDS_MAX:
        return None
    salt = bytes.fromhex(m.group(2))
    if derive(code, salt, int(m.group(1)), "check").hex() != m.group(3):
        return None
    return open_sealed(derive(code, salt, int(m.group(1)), "wrap"), m.group(4))


def when(s):
    """a time as the file keeps it: «now», a UTC stamp, or False (off)"""
    if s in ("off", "false", "no"): return False
    if s == "now": return "now"
    if WHEN.fullmatch(s):
        try: dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError: sys.exit(f"{s}: not a real UTC time")
        return s
    sys.exit(f"{s!r}: use now, off, or a UTC time like 2026-12-01T00:00:00Z")


def load():
    if not FILE.is_file(): sys.exit(f"{FILE}: missing")
    d = json.loads(FILE.read_text(encoding="utf-8"))
    for k, v in (("v", 1), ("games", {}), ("defs", {}), ("bdefs", {}), ("codes", [])): d.setdefault(k, v)
    return d


def save(d):
    out = {"v": 1, "games": d["games"], "defs": d["defs"], "bdefs": d["bdefs"], "codes": d["codes"]}
    out = {k: v for k, v in out.items() if k in ("v", "games", "codes") or v}
    text = json.dumps(out, ensure_ascii=False, indent=1) + "\n"
    if len(text.encode("utf-8")) > FILE_MAX: sys.exit(f"the file would be {len(text.encode('utf-8'))} bytes: the app reads {FILE_MAX} at most (a bigger game is a pack)")
    FILE.write_text(text, encoding="utf-8")


def key_file(a):
    return Path(getattr(a, "key_file", None) or os.environ.get("URTV_GAMES_KEY_FILE") or Path.home() / ".config" / "urtv-games" / "group.key")


def read_key(a, make=False):
    f = key_file(a)
    if f.is_file(): return bytes.fromhex(f.read_text().strip())
    if not make: sys.exit(f"no group key at {f}: run «key» first")
    f.parent.mkdir(parents=True, exist_ok=True)
    k = secrets.token_bytes(KEY_BYTES)
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as h: h.write(k.hex() + "\n")
    return k


def game_json(path):
    try: g = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e: sys.exit(f"{path}: not read: {e}")
    why = engine_def.check_game(g)
    if why: sys.exit(f"{path}: not a game the engine can run: {why[0]}")
    return g


def cmd_key(a):
    f = key_file(a); had = f.is_file(); read_key(a, make=True)
    print(f"group key {'already there' if had else 'made'} at {f} (mode 600): keep it private, it is never printed or committed")


def cmd_code(a):
    d = load(); k = read_key(a)
    if not ROUNDS_MIN <= a.rounds <= ROUNDS_MAX: sys.exit(f"--rounds: {ROUNDS_MIN} to {ROUNDS_MAX}")
    if a.add and len(d["codes"]) >= CODES_MAX: sys.exit(f"{CODES_MAX} records at most (every TV that enters a code pays the slow part once for each record)")
    if a.ask:
        code = hidden(f"code (hidden, exactly {CODE_LEN} signs of {ALPHABET}): ")
        if hidden("again: ") != code: sys.exit("the two do not match; nothing done")
        if not valid_code(normalize(code)): sys.exit(f"a code is exactly {CODE_LEN} signs of {ALPHABET}")
        shown = None
    else:
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LEN)); shown = code
    rec = record(code, k, rounds=a.rounds)
    if a.add: d["codes"].append(rec); save(d); print("added to content/games-release.json (commit it to publish)")
    if shown: print(f"CODE (shown once, never stored):  {shown}")
    print("record:", rec)
    if not a.add: print('paste it into "codes" of content/games-release.json, or run again with --add')


def cmd_list(a):
    d = load()
    print(f"{len(d['codes'])} pass record(s):")
    for r in d["codes"]: print("  ", r.split(":")[3][:8], "rounds", r.split(":")[1])
    print("games:", ", ".join(f"{g} a={v.get('a')} b={v.get('b')}" for g, v in d["games"].items()) or "none")
    print("definitions: open", ", ".join(d["defs"]) or "none", "| sealed", ", ".join(d["bdefs"]) or "none")


def cmd_revoke(a):
    d = load(); hit = [r for r in d["codes"] if r.split(":")[3].startswith(a.hash.lower())]
    if len(hit) != 1: sys.exit(f"{len(hit)} records start with {a.hash!r}: nothing removed (see «list»)")
    d["codes"].remove(hit[0]); save(d); print("removed; the TVs that held it are group A at their next read (run «rekey --keep» so that what they already read is of no use for later files)")


def cmd_add(a):
    g = game_json(a.file); d = load(); d["defs"][g["id"]] = g; d["bdefs"].pop(g["id"], None); d["games"].setdefault(g["id"], {"a": False, "b": False}); save(d); print(g["id"], "added for everyone (off until «on»)")


def cmd_seal(a):
    g = game_json(a.file)
    if g["id"] != a.id: sys.exit(f"the file's id is {g['id']}, not {a.id}")
    d = load(); d["bdefs"][a.id] = seal(read_key(a), json.dumps(g, ensure_ascii=False, separators=(",", ":")).encode("utf-8")); d["defs"].pop(a.id, None); d["games"].setdefault(a.id, {"a": False, "b": False}); save(d); print(a.id, "sealed for group B (off until «on»)")


def cmd_remove(a):
    d = load()
    for k in ("games", "defs", "bdefs"): d[k].pop(a.id, None)
    save(d); print(a.id, "removed")


def cmd_on(a):
    if not ID.fullmatch(a.id): sys.exit("not an id")
    d = load()
    if a.native:
        if a.id not in engine_def.HELD: sys.exit(f"{a.id} is not a game the app holds back (tools/engine_def.py HELD)")
        if a.id in d["defs"] or a.id in d["bdefs"]: sys.exit(f"{a.id} has a definition: a native game has none (remove it first)")
    elif a.id in engine_def.HELD: sys.exit(f"{a.id} is a game of the app's own list: use --native")
    elif a.id not in d["defs"] and a.id not in d["bdefs"]: sys.exit(f"{a.id} has no definition: «add» or «seal» it first")
    if a.a is None and a.b is None: sys.exit("give --a and/or --b (a time, now or off)")
    g = d["games"].setdefault(a.id, {"a": False, "b": False})
    if a.native: g["native"] = True
    if a.a is not None: g["a"] = when(a.a)
    if a.b is not None: g["b"] = when(a.b)
    save(d); print(a.id, g)


def cmd_off(a):
    d = load()
    if a.id in d["games"]: d["games"][a.id] = {"a": False, "b": False, **({"native": True} if d["games"][a.id].get("native") else {})}
    save(d); print(a.id, "off for both")


def is_on(v, at):
    if v == "now": return True
    return isinstance(v, str) and bool(WHEN.fullmatch(v)) and dt.datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ") <= at


def cmd_check(a):
    d = load(); at = dt.datetime.strptime(a.at, "%Y-%m-%dT%H:%M:%SZ") if a.at else dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    print("at", at.strftime("%Y-%m-%dT%H:%M:%SZ"), "(group B also has a game from its a time)")
    for g, v in d["games"].items():
        ea, eb = is_on(v.get("a"), at), is_on(v.get("b"), at)
        has = g in d["defs"] or g in d["bdefs"] or v.get("native") is True
        print(f"  {g:24s} A {'on ' if ea and (g in d['defs'] or v.get('native') is True) else 'off'}  B {'on ' if (ea or eb) and has else 'off'}  {'' if has else '(no definition: not on)'}")


def cmd_rekey(a):
    d = load(); old = read_key(a)
    if not a.keep: sys.exit("«rekey --keep» asks for the codes that stay")
    codes = []
    print("the codes that stay, one at a time (hidden); an empty line ends:")
    while True:
        c = hidden("code: ")
        if not c: break
        if not valid_code(normalize(c)): print(f"not a code ({CODE_LEN} signs of the alphabet), skipped"); continue
        if not any(group_key_of(c, r) == old for r in d["codes"]): print("that code is not in the file: skipped"); continue
        codes.append(c)
    if not codes: sys.exit("no code to keep: nothing changed")
    new = secrets.token_bytes(KEY_BYTES)
    plain = {g: open_sealed(old, s) for g, s in d["bdefs"].items()}
    if any(p is None for p in plain.values()): sys.exit("a sealed game does not open with the current key: nothing changed")
    d["codes"] = [record(c, new, rounds=a.rounds) for c in codes]; d["bdefs"] = {g: seal(new, p) for g, p in plain.items()}
    f = key_file(a); tmp = f.with_suffix(".new")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as h: h.write(new.hex() + "\n")
    save(d); os.replace(tmp, f)
    print(f"a new group key (the old one is gone from the key file), {len(codes)} record(s) written again, {len(plain)} game(s) sealed again")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--key-file")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("key").set_defaults(f=cmd_key)
    c = sub.add_parser("code"); c.add_argument("--add", action="store_true"); c.add_argument("--ask", action="store_true"); c.add_argument("--rounds", type=int, default=ROUNDS); c.set_defaults(f=cmd_code)
    sub.add_parser("list").set_defaults(f=cmd_list)
    r = sub.add_parser("revoke"); r.add_argument("hash"); r.set_defaults(f=cmd_revoke)
    x = sub.add_parser("add"); x.add_argument("file"); x.set_defaults(f=cmd_add)
    s = sub.add_parser("seal"); s.add_argument("id"); s.add_argument("file"); s.set_defaults(f=cmd_seal)
    m = sub.add_parser("remove"); m.add_argument("id"); m.set_defaults(f=cmd_remove)
    o = sub.add_parser("on"); o.add_argument("id"); o.add_argument("--a"); o.add_argument("--b"); o.add_argument("--native", action="store_true"); o.set_defaults(f=cmd_on)
    f = sub.add_parser("off"); f.add_argument("id"); f.set_defaults(f=cmd_off)
    k = sub.add_parser("check"); k.add_argument("--at"); k.set_defaults(f=cmd_check)
    rk = sub.add_parser("rekey"); rk.add_argument("--keep", action="store_true"); rk.add_argument("--rounds", type=int, default=ROUNDS); rk.set_defaults(f=cmd_rekey)
    a = ap.parse_args(); a.f(a)


if __name__ == "__main__":
    main()
