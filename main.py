#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XORE FF BOT — v5.1 (FULL SINGLE FILE)
======================================
Public  : Ghost 4HB (Speed 6x)
Admin   : Ghost + Blitz + Spam + Watch + Accounts CRUD (AJAX) + Logs + Stats

v5.1 FIXES (Welcome Message Delivery):
  [BUG 1] watch_worker deadline كان +60s فقط — الآن +WATCH_KEEPALIVE+30
  [BUG 2] _extract_member_uids قوي: يتعامل مع int / str / bytes / nested
  [BUG 3] welcome channel fallback: يجرب [1, 6, 8] تلقائياً
  [BUG 4] logging تفصيلي داخل watch loop (pkts / uid_hits / welcomes)
  [NEW]   /watch-debug — ring buffer لآخر 100 packet مستلمة
  [NEW]   /watch-test-welcome — اختبار 4 قنوات على uid معين
  [NEW]   _dump_packet() داخلي لكل packet مستلم

v5.0 (base):
  - Account Manager AJAX (no page reload)
  - Batch select + bulk enable/disable/delete/test
  - Sort + pagination + live search + filters
  - Alias + Note per account
  - Password reveal toggle
  - Export TXT / CSV / JSON
  - Live stats polling + running modules indicator
  - Session history (last 50)
  - Toast notifications + optional sound
  - Dark / Light theme toggle
  - Draft autosave (localStorage)
"""
import csv
import io
import json
import os
import random
import socket
import struct
import threading
import time
import urllib3
from datetime import datetime

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import (HTMLResponse, JSONResponse,
                                PlainTextResponse, Response)
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import blackboxprotobuf
    HAS_BLACKBOX = True
except ImportError:
    HAS_BLACKBOX = False

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ═══════════════════════════════════════════════════════════
#  ⚙️  CONFIG
# ═══════════════════════════════════════════════════════════

xK = b"Yg&tc%DEuh6%Zc^8"
xV = b"6oyZDr22E3ychjM%"

MAX_SESSION_SECONDS = int(os.environ.get("MAX_SESSION_SECONDS", "22"))
HB_PER_ACCOUNT      = int(os.environ.get("HB_PER_ACCOUNT", "4"))
MAX_ACCOUNTS        = int(os.environ.get("MAX_ACCOUNTS", "500"))
ADMIN_KEY           = os.environ.get("ADMIN_KEY", "mahdixorepy12340")
LOGIN_TIMEOUT       = int(os.environ.get("LOGIN_TIMEOUT", "6"))
TCP_CONNECT_TIMEOUT = int(os.environ.get("TCP_CONNECT_TIMEOUT", "4"))
POST_LOGIN_WAIT     = float(os.environ.get("POST_LOGIN_WAIT", "0.08"))
LOGIN_POOL          = int(os.environ.get("LOGIN_POOL", "128"))
SEND_RETRIES        = int(os.environ.get("SEND_RETRIES", "5"))

WELCOME_MSG          = os.environ.get("WELCOME_MSG", "اهلا من مهدي")
WELCOME_ENABLED      = os.environ.get("WELCOME_ENABLED", "1") == "1"
WELCOME_CHANNEL      = int(os.environ.get("WELCOME_CHANNEL", "1"))
WELCOME_CHANNELS_TRY = [WELCOME_CHANNEL, 6, 8, 1]  # fallback order
WATCH_KEEPALIVE      = int(os.environ.get("WATCH_KEEPALIVE", "600"))
WATCH_KEEPALIVE_PING = int(os.environ.get("WATCH_KEEPALIVE_PING", "18"))
WATCH_BASELINE_WAIT  = float(os.environ.get("WATCH_BASELINE_WAIT", "3.0"))

SPAM_RATE            = float(os.environ.get("SPAM_RATE", "0.15"))
SPAM_DURATION        = int(os.environ.get("SPAM_DURATION", "120"))
SPAM_ACCOUNTS_MAX    = int(os.environ.get("SPAM_ACCOUNTS_MAX", "100"))

BLITZ_ACCOUNTS_MAX   = int(os.environ.get("BLITZ_ACCOUNTS_MAX", "100"))
BLITZ_LINGER_S       = float(os.environ.get("BLITZ_LINGER_S", "3.0"))
BLITZ_CHANNEL        = int(os.environ.get("BLITZ_CHANNEL", "2"))

WEBHOOK_URL          = os.environ.get("WEBHOOK_URL", "")
XORE_DEBUG           = os.environ.get("XORE_DEBUG", "0") == "1"


def _log(*a):
    if XORE_DEBUG:
        print("[XORE]", *a, flush=True)


# ═══════════════════════════════════════════════════════════
#  👥  ACCOUNT STORE
# ═══════════════════════════════════════════════════════════

_DEFAULT_ACCOUNTS_RAW = os.environ.get("FF_ACCOUNTS_RAW", "") or ""


def _parse_accounts(raw):
    if not raw or not raw.strip():
        return []
    out = []
    seen = set()
    for chunk in raw.replace(";", "\n").replace(",", "\n").splitlines():
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#") or ":" not in chunk:
            continue
        pw, uid = chunk.split(":", 1)
        pw, uid = pw.strip(), uid.strip()
        if pw and uid and uid not in seen:
            seen.add(uid)
            out.append((uid, pw))
    return out[:MAX_ACCOUNTS]


_ACCOUNTS = _parse_accounts(_DEFAULT_ACCOUNTS_RAW)
_DISABLED_UIDS = set()
_ACCOUNTS_LOCK = threading.Lock()

_ACCOUNT_META = {}
_META_LOCK = threading.Lock()


def _meta_get(uid):
    with _META_LOCK:
        m = _ACCOUNT_META.get(uid)
        if m is None:
            m = {"alias": "", "note": "", "added_at": time.time(),
                 "last_status": None, "last_check": 0}
            _ACCOUNT_META[uid] = m
        return dict(m)


def _meta_update(uid, **kw):
    with _META_LOCK:
        m = _ACCOUNT_META.setdefault(uid, {
            "alias": "", "note": "", "added_at": time.time(),
            "last_status": None, "last_check": 0,
        })
        m.update(kw)


def _meta_set_status(uid, status):
    with _META_LOCK:
        m = _ACCOUNT_META.setdefault(uid, {
            "alias": "", "note": "", "added_at": time.time(),
            "last_status": None, "last_check": 0,
        })
        m["last_status"] = status
        m["last_check"] = time.time()


def _meta_drop(uid):
    with _META_LOCK:
        _ACCOUNT_META.pop(uid, None)


def get_accounts():
    with _ACCOUNTS_LOCK:
        return [(u, p) for (u, p) in _ACCOUNTS if u not in _DISABLED_UIDS]


def get_all_accounts_raw():
    with _ACCOUNTS_LOCK:
        return [(u, p, u not in _DISABLED_UIDS) for (u, p) in _ACCOUNTS]


def count_accounts():
    with _ACCOUNTS_LOCK:
        return len(_ACCOUNTS)


def add_accounts(raw):
    with _ACCOUNTS_LOCK:
        existing = {u for (u, p) in _ACCOUNTS}
        added, skipped_dup = 0, 0
        for u, p in _parse_accounts(raw):
            if u in existing:
                skipped_dup += 1
                continue
            if len(_ACCOUNTS) >= MAX_ACCOUNTS:
                break
            _ACCOUNTS.append((u, p))
            existing.add(u)
            added += 1
            _meta_update(u, added_at=time.time())
    return {"added": added, "skipped_dup": skipped_dup,
            "total": count_accounts()}


def replace_accounts(raw):
    global _ACCOUNTS, _DISABLED_UIDS
    new_list = _parse_accounts(raw)
    with _ACCOUNTS_LOCK:
        _ACCOUNTS = new_list[:MAX_ACCOUNTS]
        _DISABLED_UIDS = set()
    return len(_ACCOUNTS)


def delete_account(uid):
    global _ACCOUNTS, _DISABLED_UIDS
    with _ACCOUNTS_LOCK:
        before = len(_ACCOUNTS)
        _ACCOUNTS = [(u, p) for (u, p) in _ACCOUNTS if u != uid]
        _DISABLED_UIDS.discard(uid)
        removed = before - len(_ACCOUNTS)
    if removed:
        _meta_drop(uid)
    return removed


def bulk_delete(uids):
    if not uids:
        return 0
    s = set(uids)
    global _ACCOUNTS, _DISABLED_UIDS
    with _ACCOUNTS_LOCK:
        before = len(_ACCOUNTS)
        _ACCOUNTS = [(u, p) for (u, p) in _ACCOUNTS if u not in s]
        _DISABLED_UIDS -= s
        removed = before - len(_ACCOUNTS)
    for u in s:
        _meta_drop(u)
    return removed


def clear_accounts():
    global _ACCOUNTS, _DISABLED_UIDS
    with _ACCOUNTS_LOCK:
        n = len(_ACCOUNTS)
        _ACCOUNTS = []
        _DISABLED_UIDS = set()
    with _META_LOCK:
        _ACCOUNT_META.clear()
    return n


def toggle_account(uid):
    with _ACCOUNTS_LOCK:
        if not any(u == uid for (u, p) in _ACCOUNTS):
            return None
        if uid in _DISABLED_UIDS:
            _DISABLED_UIDS.discard(uid)
            return True
        _DISABLED_UIDS.add(uid)
        return False


def set_enabled_many(uids, enabled):
    n = 0
    with _ACCOUNTS_LOCK:
        present = {u for (u, p) in _ACCOUNTS}
        for u in uids:
            if u not in present:
                continue
            if enabled:
                if u in _DISABLED_UIDS:
                    _DISABLED_UIDS.discard(u)
                    n += 1
            else:
                if u not in _DISABLED_UIDS:
                    _DISABLED_UIDS.add(u)
                    n += 1
    return n


def export_accounts_text():
    with _ACCOUNTS_LOCK:
        return "\n".join(f"{p}:{u}" for (u, p) in _ACCOUNTS)


def export_accounts_csv():
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["uid", "password", "alias", "enabled", "last_status",
                "last_check", "added_at"])
    with _ACCOUNTS_LOCK:
        rows = list(_ACCOUNTS)
    for u, p in rows:
        m = _meta_get(u)
        w.writerow([u, p, m.get("alias", ""),
                    "1" if u not in _DISABLED_UIDS else "0",
                    m.get("last_status") or "",
                    datetime.fromtimestamp(m.get("last_check") or 0)
                        .strftime("%Y-%m-%d %H:%M:%S")
                        if m.get("last_check") else "",
                    datetime.fromtimestamp(m.get("added_at") or 0)
                        .strftime("%Y-%m-%d %H:%M:%S")])
    return buf.getvalue()


def export_accounts_json():
    with _ACCOUNTS_LOCK:
        rows = list(_ACCOUNTS)
    out = []
    for u, p in rows:
        m = _meta_get(u)
        out.append({
            "uid": u, "password": p,
            "alias": m.get("alias", ""), "note": m.get("note", ""),
            "enabled": u not in _DISABLED_UIDS,
            "last_status": m.get("last_status"),
            "last_check": m.get("last_check", 0),
            "added_at": m.get("added_at", 0),
        })
    return out


# ═══════════════════════════════════════════════════════════
#  📊  STATE
# ═══════════════════════════════════════════════════════════

_LIVE_STATUS = {
    "checked": False, "total": 0, "alive": 0, "dead": 0,
    "checking": False, "results": [],
    "started_at": 0, "finished_at": 0,
}
_LIVE_LOCK = threading.Lock()

_WATCH_STATE = {
    "active": False, "team": None, "started_at": 0,
    "sessions": 0, "welcomed": 0, "events": [],
    "pkts_total": 0, "uid_hits_total": 0,
}
_WATCH_LOCK = threading.Lock()
_WATCH_STOP_EVENTS = []

_SPAM_STATE = {
    "active": False, "team": None, "started_at": 0,
    "accounts": 0, "cycles": 0, "joins": 0, "exits": 0, "errors": 0,
    "events": [],
}
_SPAM_LOCK = threading.Lock()
_SPAM_STOP_EVENTS = []

_BLITZ_STATE = {
    "active": False, "team": None, "started_at": 0,
    "accounts": 0, "joined": 0, "welcomed": 0, "exited": 0, "errors": 0,
    "events": [], "total": 0,
}
_BLITZ_LOCK = threading.Lock()
_BLITZ_STOP_EVENTS = []

_GHOST_STATE = {
    "active": False, "team": None, "started_at": 0,
    "accounts": 0, "finished_at": 0, "last_result": None,
}
_GHOST_LOCK = threading.Lock()

_STATS = {
    "ghost_runs": 0, "blitz_runs": 0, "spam_runs": 0, "watch_runs": 0,
    "checks": 0, "logins_ok": 0, "logins_fail": 0,
    "started_at": time.time(),
}
_STATS_LOCK = threading.Lock()

_ACTIVITY_LOG = []
_ACTIVITY_LOCK = threading.Lock()

_HISTORY = []
_HISTORY_LOCK = threading.Lock()

# Packet ring buffer for /watch-debug
_PACKET_DUMP = []
_PACKET_DUMP_LOCK = threading.Lock()


def _dump_packet(uid, tag, hx, decoded=None):
    with _PACKET_DUMP_LOCK:
        _PACKET_DUMP.insert(0, {
            "t": time.strftime("%H:%M:%S"),
            "uid": uid, "tag": tag,
            "len": len(hx) // 2,
            "opcode": hx[:4] if len(hx) >= 4 else "",
            "decoded": (decoded[:500] if isinstance(decoded, str)
                        else str(decoded)[:500] if decoded else None),
            "hex_head": hx[:240],
        })
        del _PACKET_DUMP[200:]


def _stats_inc(key, n=1):
    with _STATS_LOCK:
        _STATS[key] = _STATS.get(key, 0) + n


def _stats_snapshot():
    with _STATS_LOCK:
        s = dict(_STATS)
        s["uptime"] = int(time.time() - s.get("started_at", time.time()))
        return s


def _activity(kind, msg="", uid=None):
    with _ACTIVITY_LOCK:
        _ACTIVITY_LOG.insert(0, {
            "t": time.strftime("%H:%M:%S"),
            "ts": time.time(), "kind": kind, "msg": msg, "uid": uid,
        })
        del _ACTIVITY_LOG[300:]


def _activity_snapshot(limit=80):
    with _ACTIVITY_LOCK:
        return list(_ACTIVITY_LOG[:limit])


def _history_push(kind, team, accounts, extra=None):
    with _HISTORY_LOCK:
        _HISTORY.insert(0, {
            "t": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ts": time.time(),
            "kind": kind, "team": team, "accounts": accounts,
            "extra": extra or {},
        })
        del _HISTORY[100:]


def _history_snapshot(limit=50):
    with _HISTORY_LOCK:
        return list(_HISTORY[:limit])


def _watch_snapshot():
    with _WATCH_LOCK:
        return dict(_WATCH_STATE)


def _watch_push_event(kind, uid=None):
    with _WATCH_LOCK:
        _WATCH_STATE["events"].insert(0, {
            "t": time.strftime("%H:%M:%S"), "kind": kind, "uid": uid,
        })
        del _WATCH_STATE["events"][50:]
        if kind == "welcome":
            _WATCH_STATE["welcomed"] += 1
    _activity(f"watch:{kind}", uid=uid)


def _watch_stats_inc(pkts=0, uid_hits=0):
    with _WATCH_LOCK:
        _WATCH_STATE["pkts_total"] = _WATCH_STATE.get("pkts_total", 0) + pkts
        _WATCH_STATE["uid_hits_total"] = \
            _WATCH_STATE.get("uid_hits_total", 0) + uid_hits


def _spam_snapshot():
    with _SPAM_LOCK:
        return dict(_SPAM_STATE)


def _spam_push(kind, uid=None):
    with _SPAM_LOCK:
        if   kind == "join":  _SPAM_STATE["joins"] += 1
        elif kind == "exit":  _SPAM_STATE["exits"] += 1
        elif kind == "cycle": _SPAM_STATE["cycles"] += 1
        elif kind == "error": _SPAM_STATE["errors"] += 1
        _SPAM_STATE["events"].insert(0, {
            "t": time.strftime("%H:%M:%S"), "kind": kind, "uid": uid,
        })
        del _SPAM_STATE["events"][50:]
    if kind in ("cycle", "error"):
        _activity(f"spam:{kind}", uid=uid)


def _blitz_snapshot():
    with _BLITZ_LOCK:
        return dict(_BLITZ_STATE)


def _blitz_push(kind, uid=None):
    with _BLITZ_LOCK:
        if   kind == "joined":   _BLITZ_STATE["joined"] += 1
        elif kind == "welcome":  _BLITZ_STATE["welcomed"] += 1
        elif kind == "exit":     _BLITZ_STATE["exited"] += 1
        elif kind == "error":    _BLITZ_STATE["errors"] += 1
        _BLITZ_STATE["events"].insert(0, {
            "t": time.strftime("%H:%M:%S"), "kind": kind, "uid": uid,
        })
        del _BLITZ_STATE["events"][80:]
    if kind in ("joined", "welcome", "exit", "error"):
        _activity(f"blitz:{kind}", uid=uid)


def _ghost_snapshot():
    with _GHOST_LOCK:
        return dict(_GHOST_STATE)


def get_live_status():
    with _LIVE_LOCK:
        return dict(_LIVE_STATUS)


def _set_live_status(**kwargs):
    with _LIVE_LOCK:
        _LIVE_STATUS.update(kwargs)


def is_admin(key):
    return key == ADMIN_KEY


# ═══════════════════════════════════════════════════════════
#  🔐  CRYPTO / PROTOBUF
# ═══════════════════════════════════════════════════════════

def EnV_VaRiAnT(n):
    out = []
    while True:
        b = n & 0x7F; n >>= 7
        if n: b |= 0x80
        out.append(b)
        if not n: break
    return bytes(out)


def ProToBuF(fields):
    p = bytearray()
    for f, v in fields.items():
        if isinstance(v, bool):
            p.extend(EnV_VaRiAnT((f << 3) | 0)); p.extend(EnV_VaRiAnT(1 if v else 0))
        elif isinstance(v, int):
            p.extend(EnV_VaRiAnT((f << 3) | 0)); p.extend(EnV_VaRiAnT(v))
        elif isinstance(v, str):
            d = v.encode()
            p.extend(EnV_VaRiAnT((f << 3) | 2)); p.extend(EnV_VaRiAnT(len(d))); p.extend(d)
        elif isinstance(v, (bytes, bytearray)):
            d = bytes(v)
            p.extend(EnV_VaRiAnT((f << 3) | 2)); p.extend(EnV_VaRiAnT(len(d))); p.extend(d)
    return bytes(p)


def Read_VaRiAnT(data, pos):
    result = 0; shift = 0
    while pos < len(data):
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80): break
        shift += 7
    return result, pos


def Parse_ProToBuF(data):
    fields = {}; pos = 0; n = len(data)
    while pos < n:
        try:
            key, pos = Read_VaRiAnT(data, pos)
        except Exception:
            break
        fn = key >> 3; wt = key & 0x07
        try:
            if wt == 0:
                val, pos = Read_VaRiAnT(data, pos)
            elif wt == 2:
                ln, pos = Read_VaRiAnT(data, pos)
                val = data[pos:pos + ln]; pos += ln
            elif wt == 5:
                val = data[pos:pos + 4]; pos += 4
            elif wt == 1:
                val = data[pos:pos + 8]; pos += 8
            else:
                break
        except Exception:
            break
        fields.setdefault(fn, []).append(val)
    return fields


# ═══════════════════════════════════════════════════════════
#  🎯  MEMBER UID EXTRACTOR — v5.1 STRONG
# ═══════════════════════════════════════════════════════════

def _extract_member_uids(packet):
    """Extract candidate player UIDs from decoded blackboxprotobuf JSON.
    Handles: int, str-of-digits, bytes (4/8 byte BE, or ASCII digits),
    nested lists/dicts, depth up to 12."""
    uids = set()
    if not isinstance(packet, dict):
        return uids

    def _coerce_int(d):
        if isinstance(d, bool):
            return None
        if isinstance(d, int):
            return d
        if isinstance(d, str) and d.isdigit():
            try:
                return int(d)
            except Exception:
                return None
        if isinstance(d, (bytes, bytearray)):
            try:
                if len(d) in (4, 8):
                    return int.from_bytes(d, "big")
                s = d.decode("ascii", errors="ignore")
                if s.isdigit():
                    return int(s)
            except Exception:
                return None
        return None

    def walk(node, depth=0):
        if depth > 12:
            return
        if isinstance(node, list):
            for item in node:
                walk(item, depth + 1)
            return
        if not isinstance(node, dict):
            return
        if "data" in node:
            v = _coerce_int(node["data"])
            if v is not None and 100_000 < v < 99_999_999_999:
                uids.add(v)
        for v in node.values():
            walk(v, depth + 1)

    walk(packet)
    return uids


def Ua():
    return random.choice([
        "4.0.18P6", "4.0.19P7", "4.0.20P1", "4.1.0P3", "4.1.5P2",
        "4.2.1P8", "4.2.3P1", "5.0.1B2", "5.0.2P4", "5.1.0P1",
        "5.2.0B1", "5.2.5P3", "5.3.0B1", "5.3.2P2", "5.4.0P1",
        "5.4.3B2", "5.5.0P1", "5.5.2P3",
    ])


def EnC_PacKeT(HeX, K, V):
    return AES.new(K, AES.MODE_CBC, V).encrypt(
        pad(bytes.fromhex(HeX), 16)).hex()


def EnC_Vr(N):
    H = []
    while True:
        b = N & 0x7F; N >>= 7
        if N: b |= 0x80
        H.append(b)
        if not N: break
    return bytes(H)


def CrEaTe_VarianT(field_number, value):
    return EnC_Vr((field_number << 3) | 0) + EnC_Vr(value)


def CrEaTe_LenGTh(field_number, value):
    encoded = value.encode() if isinstance(value, str) else value
    return EnC_Vr((field_number << 3) | 2) + EnC_Vr(len(encoded)) + encoded


def CrEaTe_ProTo(fields):
    packet = bytearray()
    for field, value in fields.items():
        if isinstance(value, dict):
            packet.extend(CrEaTe_LenGTh(field, CrEaTe_ProTo(value)))
        elif isinstance(value, int):
            packet.extend(CrEaTe_VarianT(field, value))
        elif isinstance(value, (str, bytes)):
            packet.extend(CrEaTe_LenGTh(field, value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    packet.extend(CrEaTe_LenGTh(field, CrEaTe_ProTo(item)))
    return bytes(packet)


def DecodE_HeX(H):
    F = hex(H)[2:]
    return "0" + F if len(F) == 1 else F


def GeneRaTePk(Pk, N, K, V):
    PkEnc = EnC_PacKeT(Pk, K, V)
    length_hex = DecodE_HeX(len(PkEnc) // 2)
    padding = {2: "000000", 3: "00000", 4: "0000", 5: "000"}.get(
        len(length_hex), "00000")
    return bytes.fromhex(N + padding + length_hex + PkEnc)


def DeCode_PackEt(input_text):
    if not HAS_BLACKBOX:
        return None
    try:
        data = bytes.fromhex(input_text) if isinstance(input_text, str) else input_text
        message, _ = blackboxprotobuf.protobuf_to_json(data)
        return message
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
#  📦  PACKETS
# ═══════════════════════════════════════════════════════════

def Join_Team(team_code, key, iv):
    sub = {
        1: bytes.fromhex("01090a0b121619201d2729"), 2: 40,
        3: bytes.fromhex("01090a0b121619201d2729"), 4: "w\\Z]", 6: 12,
        7: bytes.fromhex("01090a0b121619201d2729"),
        8: "1.132.9", 9: 6, 10: 2,
        11: bytes.fromhex("01090a0b121619201d2729"),
    }
    main = {
        1: 4, 2: {
            4: bytes.fromhex("01090a0b121619201d2729"),
            5: str(team_code), 6: 6, 8: 1, 9: sub,
            11: {1: "IDC1", 2: 99, 3: "ME"}, 13: "ar",
            16: bytes.fromhex("374f521955"),
            20: [
                {1: 3, 2: 360}, {1: 4, 2: 391}, {1: 5, 2: 156},
                {1: 29, 2: 204}, {1: 22, 2: 118}, {1: 14, 2: 139}, {1: 21},
            ],
            27: {1: 2, 2: 4},
        },
    }
    return GeneRaTePk(CrEaTe_ProTo(main).hex(), "0519", key, iv)


def SendInv(bot_uid, uid, K, V):
    fields = {
        1: 33, 2: {
            1: int(uid), 2: "ME", 3: 1, 4: 1, 6: "yyt", 7: 330,
            8: 1000, 9: 100, 10: "DZ", 12: 1, 13: int(uid), 16: 1,
            17: {2: 159, 4: "y[WW", 6: 11, 8: "1.118.1", 9: 3, 10: 1},
            18: 306, 19: 18, 24: 902000306, 26: {},
            27: {1: 11, 2: int(bot_uid), 3: 999}, 28: {},
            31: {1: 1, 2: 32768}, 32: 32768,
            34: {
                1: int(bot_uid), 2: 8,
                3: "\u0010\u0015\b\n\u000b\u0013\f\u000f\u0011\u0004"
                   "\u0007\u0002\u0003\r\u000e\u0012\u0001\u0005\u0006",
            },
        },
    }
    return GeneRaTePk(str(CrEaTe_ProTo(fields).hex()), "0519", K, V)


def Send_GhosTs(uid, name, sq, key, iv, lang="en"):
    fields = {
        1: 61, 2: {
            1: int(uid),
            2: {1: int(uid), 2: 1159, 3: name, 5: 12, 6: 9999,
                7: 1, 8: {2: 1, 3: 1}, 9: 3, 10: lang},
            3: sq,
        },
    }
    return GeneRaTePk(str(CrEaTe_ProTo(fields).hex()), "0519", key, iv)


def Send_TeamChat(bot_uid, msg, squad_code, key, iv, channel=1):
    text = str(msg)[:120]
    fields = {
        1: 100, 2: {1: int(bot_uid), 2: text, 3: int(channel)},
    }
    return GeneRaTePk(str(CrEaTe_ProTo(fields).hex()), "0519", key, iv)


def Send_GlobalChat(bot_uid, msg, squad_code, key, iv):
    return Send_TeamChat(bot_uid, msg, squad_code, key, iv, channel=BLITZ_CHANNEL)


def ExiT(key, iv):
    fields = {1: 7, 2: {1: 0}}
    return GeneRaTePk(str(CrEaTe_ProTo(fields).hex()), "0519", key, iv)


# ═══════════════════════════════════════════════════════════
#  🔑  LOGIN
# ═══════════════════════════════════════════════════════════

def PyL(access_token, open_id):
    P = {
        3: time.strftime("%Y-%m-%d %H:%M:%S"),
        4: "free fire", 5: 1, 7: "1.132.9",
        8: "Android OS 14 / API-34 (UP1A.231005.007/V816.0.15.0.UNQMIXM)",
        9: "Handheld", 10: "Grameenphone", 11: "CarrierDataNetwork",
        12: 1666, 13: 750, 14: "352",
        15: "ARM64 FP ASIMD AES | 2400 | 8",
        16: 5563, 17: "Mali-G57 MC2",
        18: "OpenGL ES 3.2 v1.r32p1-01eac0.0a0b917d9265b4c01be9925306306139",
        19: "Google|9cc73f7a-91f6-40f6-87ec-5b67e597eb8c",
        20: "59.152.5.188", 21: "en", 22: open_id, 23: "8", 24: "Handheld",
        25: "Xiaomi 2312DRAABI", 26: "BD", 29: access_token, 30: 1,
        41: "Grameenphone", 42: "Cellular",
        57: "7428b253defc164018c604a1ebbfebdf",
        60: 109685, 61: 58294, 62: 797, 63: 18000,
        64: 58818, 65: 109685, 66: 58818, 67: 109685, 73: 2,
        74: "/data/app/~~cqQgpdMykLQEM3odipXatw==/com.dts.freefireth-"
            "G6e5yOt1dtuXG5Ambhj18g==/lib/arm64",
        76: 1,
        77: "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/"
            "~~cqQgpdMykLQEM3odipXatw==/com.dts.freefireth-"
            "G6e5yOt1dtuXG5Ambhj18g==/base.apk",
        78: 3, 79: 2, 81: "64", 83: "2019121229",
        85: 3, 86: "OpenGLES2", 87: 4095, 88: 8,
        89: b"FwQVTgUPX1UaUllDDwcWCRBpWAUOUgsvA1snWlBaO1kFYg==",
        90: "Dhaka", 91: "C", 92: 8043, 93: "android",
        94: "KqsHT4XbSZhqerDNUhjbS3DxG/4+I62zQU2tZFJN91kBUICAlZ5yujsh"
            "LKvjlk/KiShfKfis8EeB1PMhFHIodWPncZC4fCHYF3TcTwNj95aWY/S3",
        95: 111207,
        96: '{"cur_rate":[60,90,120],"support_etc2":false}',
        97: 1, 98: 1, 99: "4", 100: "4", 102: "GQ]        e",
        103: 1, 104: 45174, 105: 1,
        106: "https://dl-bs.ggpolarbear.com/live/ABHotUpdates/|"
             "https://core-bs.ggpolarbear.com/live/ABHotUpdates/|"
             "a4332cb1c1a84e51dd77441e4856ed5a",
        107: "1.9393e7b8e53e8aeb",
    }
    return AES.new(xK, AES.MODE_CBC, xV).encrypt(pad(ProToBuF(P), 16))


def Strip_MajorLogin_Prefix(body):
    if len(body) <= 64:
        return body
    try:
        if 8 in Parse_ProToBuF(body):
            return body
    except Exception:
        pass
    try:
        if 8 in Parse_ProToBuF(body[64:]):
            return body[64:]
    except Exception:
        pass
    return body[64:]


def GeT_AccEss(uid, password):
    url = "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant"
    headers = {"User-Agent": Ua(),
               "Content-Type": "application/json; charset=utf-8"}
    payload = {
        "client_id": 100067,
        "client_secret": "2ee44819e9b4598845141067b281621874"
                         "d0d5d7af9d8f7e00c1e54715b7d1e3",
        "client_type": 2, "device_id": "",
        "password": password, "response_type": "token",
        "uid": int(uid),
    }
    try:
        R = requests.post(url, headers=headers, json=payload,
                          verify=False, timeout=LOGIN_TIMEOUT)
    except Exception:
        return None
    if R.status_code not in (200, 201):
        return None
    try:
        J = R.json()
    except Exception:
        return None
    if J.get("code") != 0:
        return None
    d = J.get("data", {})
    return {"access_token": d.get("access_token"),
            "open_id": d.get("open_id")}


def MajorLogin(Payload):
    url = "https://loginbp.ppmainecoonghj.com/MajorLogin"
    headers = {
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*", "Accept-Encoding": "deflate, gzip",
        "X-GA-SV": str(int(time.time())), "Authorization": "Bearer ",
        "X-GA": "v1 1", "ReleaseVersion": "OB55",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        R = requests.post(url, headers=headers, data=Payload,
                          verify=False, timeout=LOGIN_TIMEOUT)
    except Exception:
        return None
    return R.content if R.status_code in (200, 201) and R.content else None


def GeTLoginDaTa(client_url, payload, jwt):
    url = f"{client_url}/GetLoginData"
    headers = {
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*", "Accept-Encoding": "deflate, gzip",
        "X-GA-SV": str(int(time.time())),
        "Authorization": f"Bearer {jwt}",
        "X-GA": "v1 1", "ReleaseVersion": "OB55",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    try:
        R = requests.post(url, headers=headers, data=payload,
                          verify=False, timeout=LOGIN_TIMEOUT)
    except Exception:
        return None
    return R.content if R.status_code == 200 and R.content else None


def _gv(fields, n):
    v = fields.get(n)
    if v is None:
        return None
    return v[0] if isinstance(v, list) else v


def ExtractMajorLogin(ml_resp):
    body = Strip_MajorLogin_Prefix(ml_resp)
    f = Parse_ProToBuF(body)
    jwt_b = _gv(f, 8); url_b = _gv(f, 10); ts_v = _gv(f, 21)
    key_b = _gv(f, 22); iv_b = _gv(f, 23); acct_v = _gv(f, 1)

    jwt = (jwt_b.decode("utf-8", errors="ignore")
           if isinstance(jwt_b, (bytes, bytearray))
           else (jwt_b if isinstance(jwt_b, str) else None))
    url = (url_b.decode("utf-8", errors="ignore")
           if isinstance(url_b, (bytes, bytearray))
           else (url_b if isinstance(url_b, str) else None))
    ts = ts_v if isinstance(ts_v, int) else None
    acct = acct_v if isinstance(acct_v, int) else None

    if not jwt or not isinstance(key_b, (bytes, bytearray)) or \
       not isinstance(iv_b, (bytes, bytearray)):
        return None
    return {"jwt": jwt, "url": url, "ts": ts,
            "key": bytes(key_b), "iv": bytes(iv_b), "account_id": acct}


def login_account(acc_uid, acc_pass):
    td = GeT_AccEss(acc_uid, acc_pass)
    if not td:
        _stats_inc("logins_fail")
        _meta_set_status(acc_uid, "dead")
        return None
    access_token = td["access_token"]; open_id = td["open_id"]
    if not access_token or not open_id:
        _stats_inc("logins_fail")
        _meta_set_status(acc_uid, "dead")
        return None
    login_payload = PyL(access_token, open_id)
    ml = MajorLogin(login_payload)
    if not ml:
        _stats_inc("logins_fail")
        _meta_set_status(acc_uid, "dead")
        return None
    ad = ExtractMajorLogin(ml)
    if not ad:
        _stats_inc("logins_fail")
        _meta_set_status(acc_uid, "dead")
        return None

    jwt = ad["jwt"]; ts = ad["ts"]; key = ad["key"]; iv = ad["iv"]
    url = ad["url"] or "https://clientbp.ppmainecoonghj.com"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    account_id = ad["account_id"]

    ld = GeTLoginDaTa(url, login_payload, jwt)
    if not ld:
        _stats_inc("logins_fail")
        _meta_set_status(acc_uid, "dead")
        return None
    gl = Parse_ProToBuF(ld)

    def gv(n):
        v = gl.get(n); return v[0] if isinstance(v, list) else v
    def gs(n):
        v = gv(n); return v.decode() if isinstance(v, (bytes, bytearray)) else v
    def gi(n):
        v = gv(n); return int(v) if isinstance(v, int) else None

    player_name = gs(4) or ""
    func_addr = gs(14); info_addr = gs(32)
    if not func_addr or not info_addr:
        _stats_inc("logins_fail")
        _meta_set_status(acc_uid, "dead")
        return None
    ip, port = func_addr.split(":")
    ip2, port2 = info_addr.split(":")
    if not account_id:
        account_id = gi(1) or gi(5) or 0
    _stats_inc("logins_ok")
    _meta_set_status(acc_uid, "alive")
    return {
        "uid": account_id, "jwt": jwt, "ts": ts, "key": key, "iv": iv,
        "ip": ip, "port": port, "ip2": ip2, "port2": port2,
        "name": player_name, "token": access_token,
    }


# ═══════════════════════════════════════════════════════════
#  🌐  TCP SESSION
# ═══════════════════════════════════════════════════════════

def BuildAuthToken(uid, jwt_str, ts, key, iv, mode="online"):
    ah = f"{int(uid):x}".zfill(16)
    if len(ah) > 16:
        raise ValueError("uid hex too long")
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(
        pad(jwt_str.encode(), 16)).hex()
    th = f"{int(ts):x}"
    if len(th) % 2:
        th = "0" + th
    tsz = f"{len(enc) // 2:02x}"
    pad_ = "00000" if mode == "chat" else "0000000000000"
    return f"9015{ah}{th}{pad_}{tsz}{enc}"


def _TuneSock(s):
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 524288)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 524288)
    except Exception:
        pass
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 15)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 2)
    except Exception:
        pass
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                     struct.pack("ii", 1, 0))
    except Exception:
        pass


def _fast_send(sock, pkt, retries=SEND_RETRIES):
    for i in range(retries):
        try:
            sock.sendall(pkt)
            return True
        except Exception:
            time.sleep(0.005 * (i + 1))
    return False


def _Session(host, port, uid, jwt, ts, key, iv, mode, tag,
             team_code, barrier, deadline, watch_state=None):
    s = None
    result = {"tag": tag, "uid": uid, "status": "started",
              "sent": 0, "error": None, "welcomed": 0}
    try:
        s = socket.create_connection((host, int(port)),
                                     timeout=TCP_CONNECT_TIMEOUT)
        s.settimeout(4)
        _TuneSock(s)
        s.sendall(bytes.fromhex(
            BuildAuthToken(uid, jwt, ts, key, iv, mode=mode)))

        try:
            barrier.wait(timeout=max(0.5, deadline - time.time()))
        except Exception:
            pass
        if time.time() > deadline:
            result["status"] = "timeout_before_join"
            return result

        join_pkt = Join_Team(team_code, key, iv)
        for _ in range(4):
            if _fast_send(s, join_pkt):
                result["sent"] += 1

        s.settimeout(0.5)
        target_uid = None; squad_code = None
        t0 = time.time()
        while time.time() - t0 < 4 and time.time() < deadline:
            try:
                data = s.recv(65536)
                if not data:
                    break
                hx = data.hex()
                _dump_packet(uid, "join-rx", hx)
                if hx.startswith("0500") and 100 < len(hx) < 5000:
                    try:
                        js = DeCode_PackEt(hx[10:])
                        if js:
                            packet = json.loads(js)
                            t_uid = (packet.get("5", {}).get("data", {})
                                            .get("1", {}).get("data"))
                            sq = (packet.get("5", {}).get("data", {})
                                        .get("5", {}).get("data", {})
                                        .get("31", {}).get("data"))
                            if not sq:
                                sq = (packet.get("5", {}).get("data", {})
                                            .get("31", {}).get("data"))
                            if t_uid and sq:
                                target_uid = t_uid; squad_code = sq
                                break
                    except Exception:
                        pass
            except socket.timeout:
                continue
            except Exception:
                break

        if not target_uid or not squad_code:
            result["status"] = "no_team_data"
            return result

        try: s.close()
        except Exception: pass
        if time.time() > deadline:
            result["status"] = "timeout_before_reconnect"
            return result

        s = socket.create_connection((host, int(port)),
                                     timeout=TCP_CONNECT_TIMEOUT)
        s.settimeout(4)
        _TuneSock(s)
        s.sendall(bytes.fromhex(
            BuildAuthToken(uid, jwt, ts, key, iv, mode=mode)))
        time.sleep(POST_LOGIN_WAIT)

        if _fast_send(s, SendInv(uid, target_uid, key, iv)):
            result["sent"] += 1
        for _ in range(4):
            if _fast_send(s, join_pkt):
                result["sent"] += 1

        try:
            barrier.wait(timeout=max(0.5, deadline - time.time()))
        except Exception:
            pass
        if time.time() > deadline:
            result["status"] = "timeout_before_ghost"
            return result

        ghost = Send_GhosTs(int(target_uid), "[C][B][FF00FF]XORE",
                            squad_code, key, iv)
        for _ in range(4):
            if _fast_send(s, ghost):
                result["sent"] += 1

        # ═══════════════════════════════════════════════════
        #  WATCH MODE — v5.1 FIXED
        # ═══════════════════════════════════════════════════
        if watch_state is not None and WELCOME_ENABLED:
            result["status"] = "watching"
            watch_deadline = time.time() + WATCH_KEEPALIVE
            last_ping = time.time()
            s.settimeout(0.8)
            packet_count = 0
            uid_hits = 0
            welcomes_sent = 0

            while (time.time() < watch_deadline
                   and not watch_state["stop"].is_set()):
                try:
                    data = s.recv(65536)
                    if not data:
                        break
                    packet_count += 1
                    hx = data.hex()
                    _dump_packet(uid, "watch-rx", hx)

                    if not hx.startswith("0500"):
                        continue
                    payload = hx[10:] if len(hx) > 10 else ""
                    if not payload:
                        continue
                    try:
                        js = DeCode_PackEt(payload)
                        if not js:
                            continue
                        packet = json.loads(js) if isinstance(js, str) else js
                    except Exception:
                        continue

                    members = _extract_member_uids(packet)
                    uid_hits += len(members)
                    if not members:
                        continue

                    # baseline window — collect silently
                    if (not watch_state["baseline_done"]
                            and time.time() - watch_state["started"]
                                < WATCH_BASELINE_WAIT):
                        with watch_state["lock"]:
                            watch_state["known"].update(members)
                        continue

                    if not watch_state["baseline_done"]:
                        with watch_state["lock"]:
                            watch_state["baseline_done"] = True
                            watch_state["known"].update(members)

                    for nu in members:
                        if nu == int(uid):
                            continue
                        is_new = False
                        with watch_state["lock"]:
                            if nu not in watch_state["known"]:
                                watch_state["known"].add(nu)
                                is_new = True
                        if not is_new:
                            continue

                        # try multiple channels
                        sent_ok = False
                        for ch in WELCOME_CHANNELS_TRY:
                            try:
                                pkt = Send_TeamChat(
                                    uid, WELCOME_MSG,
                                    squad_code or "0",
                                    key, iv, channel=ch)
                                s.sendall(pkt)
                                sent_ok = True
                                break
                            except Exception:
                                continue
                        if sent_ok:
                            welcomes_sent += 1
                            result["welcomed"] += 1
                            _watch_push_event("welcome", uid=nu)
                        else:
                            _watch_push_event("welcome_fail", uid=nu)

                except socket.timeout:
                    if time.time() - last_ping > WATCH_KEEPALIVE_PING:
                        try:
                            s.sendall(join_pkt)
                            last_ping = time.time()
                        except Exception:
                            break
                    continue
                except Exception:
                    break

            _watch_stats_inc(pkts=packet_count, uid_hits=uid_hits)
            _log(f"watch uid={uid} pkts={packet_count} "
                 f"uid_hits={uid_hits} welcomes={welcomes_sent}")

            try:
                s.sendall(ExiT(key, iv)); result["sent"] += 1
            except Exception:
                pass
            return result

        try:
            barrier.wait(timeout=max(0.5, deadline - time.time()))
        except Exception:
            pass
        if time.time() < deadline:
            try:
                s.sendall(ExiT(key, iv)); result["sent"] += 1
            except Exception:
                pass

        result["status"] = "success"
        return result
    except Exception as e:
        result["status"] = "error"; result["error"] = str(e)
        return result
    finally:
        try:
            if s: s.close()
        except Exception:
            pass


def run_one_account(session_data, team_code, barrier, deadline,
                    watch_state=None):
    uid = session_data["uid"]
    jwt = session_data["jwt"]; ts = session_data["ts"]
    key = session_data["key"]; iv = session_data["iv"]

    plans = [
        (session_data["ip"],  session_data["port"],  "online", "ChaT"),
        (session_data["ip2"], session_data["port2"], "chat",   "OnLinE"),
        (session_data["ip"],  session_data["port"],  "online", "ChaT2"),
        (session_data["ip2"], session_data["port2"], "chat",   "OnLinE2"),
    ]

    results = []; threads = []
    for host, port, mode, tag in plans:
        if watch_state is not None and tag != "ChaT":
            continue

        if watch_state is not None:
            t = threading.Thread(
                target=lambda h=host, p=port, m=mode, tg=tag: results.append(
                    _Session(h, p, uid, jwt, ts, key, iv, m, tg,
                             team_code, barrier, deadline, watch_state)),
                daemon=True)
        else:
            t = threading.Thread(
                target=lambda h=host, p=port, m=mode, tg=tag: results.append(
                    _Session(h, p, uid, jwt, ts, key, iv, m, tg,
                             team_code, barrier, deadline)),
                daemon=True)
        threads.append(t); t.start()

    if watch_state is not None:
        for t in threads:
            t.join()
    else:
        remaining = max(0.5, deadline - time.time())
        for t in threads:
            t.join(timeout=remaining)
    return results


# ═══════════════════════════════════════════════════════════
#  💥  SPAM  /  🌍  BLITZ
# ═══════════════════════════════════════════════════════════

def _SpamCycle(session_data, team_code, stop_event, rate, duration):
    uid = session_data["uid"]
    jwt = session_data["jwt"]; ts = session_data["ts"]
    key = session_data["key"]; iv = session_data["iv"]
    host = session_data["ip"]; port = session_data["port"]

    s = None
    joins = 0; exits = 0; cycles = 0
    try:
        s = socket.create_connection((host, int(port)),
                                     timeout=TCP_CONNECT_TIMEOUT)
        s.settimeout(3)
        _TuneSock(s)
        s.sendall(bytes.fromhex(
            BuildAuthToken(uid, jwt, ts, key, iv, mode="online")))

        join_pkt = Join_Team(team_code, key, iv)
        exit_pkt = ExiT(key, iv)

        s.sendall(join_pkt); joins += 1
        _spam_push("join", uid)

        end_at = time.time() + duration
        while time.time() < end_at and not stop_event.is_set():
            for _ in range(4):
                if stop_event.is_set(): break
                try:
                    s.sendall(join_pkt); joins += 1
                except Exception:
                    _spam_push("error", uid); break

            time.sleep(rate)

            for _ in range(3):
                if stop_event.is_set(): break
                try:
                    s.sendall(exit_pkt); exits += 1
                except Exception:
                    _spam_push("error", uid); break

            time.sleep(rate)
            cycles += 1
            _spam_push("cycle", uid)

        try: s.sendall(exit_pkt)
        except Exception: pass
    except Exception:
        _spam_push("error", uid)
    finally:
        try:
            if s: s.close()
        except Exception:
            pass
    return {"uid": uid, "joins": joins, "exits": exits, "cycles": cycles}


def _BlitzWorker(session_data, team_code, stop_event, linger_s, chat_msg):
    uid = session_data["uid"]
    jwt = session_data["jwt"]; ts = session_data["ts"]
    key = session_data["key"]; iv = session_data["iv"]
    host = session_data["ip"]; port = session_data["port"]

    s = None
    try:
        s = socket.create_connection((host, int(port)),
                                     timeout=TCP_CONNECT_TIMEOUT)
        s.settimeout(3)
        _TuneSock(s)
        s.sendall(bytes.fromhex(
            BuildAuthToken(uid, jwt, ts, key, iv, mode="online")))

        join_pkt = Join_Team(team_code, key, iv)
        for _ in range(3):
            if _fast_send(s, join_pkt):
                break

        s.settimeout(0.4)
        squad_code = None
        t0 = time.time()
        while time.time() - t0 < 2.5 and not stop_event.is_set():
            try:
                data = s.recv(65536)
                if not data: break
                hx = data.hex()
                _dump_packet(uid, "blitz-rx", hx)
                if hx.startswith("0500") and 100 < len(hx) < 5000:
                    try:
                        js = DeCode_PackEt(hx[10:])
                        if js:
                            packet = json.loads(js)
                            sq = (packet.get("5", {}).get("data", {})
                                        .get("5", {}).get("data", {})
                                        .get("31", {}).get("data"))
                            if not sq:
                                sq = (packet.get("5", {}).get("data", {})
                                            .get("31", {}).get("data"))
                            if sq:
                                squad_code = sq; break
                    except Exception:
                        pass
            except socket.timeout:
                continue
            except Exception:
                break

        _blitz_push("joined", uid)

        try:
            gc = Send_GlobalChat(uid, chat_msg, squad_code or "0", key, iv)
            if _fast_send(s, gc):
                _blitz_push("welcome", uid)
        except Exception:
            pass

        end_at = time.time() + max(0.5, linger_s)
        s.settimeout(0.4)
        while time.time() < end_at and not stop_event.is_set():
            try:
                s.recv(65536)
            except socket.timeout:
                continue
            except Exception:
                break

        try:
            if _fast_send(s, ExiT(key, iv)):
                _blitz_push("exit", uid)
        except Exception:
            pass
    except Exception:
        _blitz_push("error", uid)
    finally:
        try:
            if s: s.close()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
#  🎨  CSS — v5.1
# ═══════════════════════════════════════════════════════════

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#06060a;--bg-2:#0d0d14;--card:#12121b;--card-2:#1a1a26;
 --border:#25253a;--text:#eaeaf2;--muted:#6f6f88;
 --xore-1:#8b5cf6;--xore-2:#06b6d4;--xore-3:#ec4899;
 --success:#10f098;--warn:#f5b800;--error:#f43f5e}
body.light{--bg:#f5f5fa;--bg-2:#ffffff;--card:#ffffff;--card-2:#f0f0f5;
 --border:#dcdce8;--text:#101018;--muted:#6b6b80}
html,body{background:var(--bg);color:var(--text);
 font-family:'Cairo','JetBrains Mono',system-ui,sans-serif;
 min-height:100vh;line-height:1.65;transition:background .3s,color .3s}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:-1;
 background:radial-gradient(circle at 15% 5%,rgba(139,92,246,.14),transparent 45%),
 radial-gradient(circle at 85% 95%,rgba(6,182,212,.14),transparent 45%)}
body.light::before{display:none}
a{color:var(--xore-2);text-decoration:none}
a:hover{color:var(--xore-3)}
.container{max-width:1280px;margin:0 auto;padding:32px 20px 80px}
.header{text-align:center;margin-bottom:36px;padding:36px 20px;position:relative}
.header::after{content:'';position:absolute;bottom:0;left:50%;transform:translateX(-50%);
 width:80px;height:2px;background:linear-gradient(90deg,transparent,var(--xore-1),var(--xore-2),transparent)}
.logo{font-size:56px;font-weight:900;letter-spacing:14px;margin-bottom:6px;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3),var(--xore-2));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent;
 filter:drop-shadow(0 0 40px rgba(139,92,246,.45))}
.tagline{color:var(--muted);font-size:12px;letter-spacing:6px;text-transform:uppercase;font-weight:700}
.status-bar{display:flex;align-items:center;justify-content:center;gap:10px;margin-top:20px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;
 border-radius:999px;background:var(--card);border:1px solid var(--border);
 font-size:11.5px;font-weight:700;color:var(--muted)}
.pill.live{color:var(--success);border-color:rgba(16,240,152,.3)}
.pill.live .dot{background:var(--success);box-shadow:0 0 12px var(--success);animation:pulse 2s infinite}
.pill.busy{color:var(--warn);border-color:rgba(245,184,0,.3)}
.pill.busy .dot{background:var(--warn);box-shadow:0 0 12px var(--warn);animation:pulse 1s infinite}
.dot{width:8px;height:8px;border-radius:50%}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.hero{display:flex;justify-content:center;margin:36px 0}
.hero-stat{background:var(--card);border:1px solid var(--border);border-radius:24px;
 padding:36px 56px;text-align:center;position:relative;overflow:hidden;min-width:280px}
.hero-stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
 background:linear-gradient(90deg,var(--xore-1),var(--xore-3),var(--xore-2))}
.hero-stat .lbl{font-size:12px;color:var(--muted);text-transform:uppercase;
 letter-spacing:2px;font-weight:800;margin-bottom:12px}
.hero-stat .val{font-size:68px;font-weight:900;line-height:1;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:16px;margin-bottom:28px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:18px;
 padding:20px;position:relative;overflow:hidden;transition:transform .15s}
.stat:hover{transform:translateY(-3px)}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
 background:linear-gradient(90deg,var(--xore-1),var(--xore-3),var(--xore-2))}
.stat .label{font-size:11px;color:var(--muted);text-transform:uppercase;
 letter-spacing:1.5px;margin-bottom:10px;font-weight:800}
.stat .value{font-size:30px;font-weight:900;line-height:1}
.stat .value.purple{background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat .value.cyan{background:linear-gradient(135deg,var(--xore-2),var(--xore-1));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat .value.green{color:var(--success)}
.stat .value.red{color:var(--error)}
.stat .value.gold{background:linear-gradient(135deg,#f5b800,#d97706);
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.card{background:var(--card);border:1px solid var(--border);border-radius:20px;
 padding:24px;margin-bottom:20px;transition:background .3s,border-color .3s}
.card h2{font-size:16.5px;font-weight:800;margin-bottom:18px;
 display:flex;align-items:center;gap:12px;flex-wrap:wrap}
.card h2::before{content:'';width:5px;height:22px;border-radius:3px;
 background:linear-gradient(180deg,var(--xore-1),var(--xore-2))}
.input-row{display:flex;gap:10px;flex-wrap:wrap}
input[type=text],input[type=search],input[type=password],textarea,select{
 flex:1;background:var(--bg-2);border:1.5px solid var(--border);border-radius:12px;
 padding:14px 16px;color:var(--text);font-family:inherit;font-size:14px;outline:none;
 transition:border-color .15s,box-shadow .15s;min-width:180px}
select{cursor:pointer}
input[type=text]:focus,input[type=search]:focus,input[type=password]:focus,
textarea:focus,select:focus{border-color:var(--xore-1);
 box-shadow:0 0 0 4px rgba(139,92,246,.12)}
textarea{resize:vertical;min-height:200px;font-family:'JetBrains Mono',monospace;
 font-size:12.5px;line-height:1.7}
button,.btn{display:inline-block;padding:14px 26px;border-radius:12px;
 font-weight:800;font-family:inherit;font-size:13.5px;letter-spacing:.6px;
 border:none;cursor:pointer;transition:all .18s;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 color:#fff;box-shadow:0 8px 24px -8px rgba(139,92,246,.7);text-align:center}
button:hover,.btn:hover{transform:translateY(-2px)}
button:disabled{opacity:.5;cursor:not-allowed;transform:none}
button.sm{padding:8px 14px;font-size:12px;border-radius:8px}
button.xs{padding:5px 9px;font-size:11px;border-radius:6px}
button.ghost,.btn.ghost{background:transparent;color:var(--xore-2);
 border:1.5px solid var(--xore-2);box-shadow:none}
button.danger{background:linear-gradient(135deg,var(--error),#b91c1c)}
button.green{background:linear-gradient(135deg,var(--success),#059669);color:#04140c}
button.warn{background:linear-gradient(135deg,var(--warn),#c2410c);color:#1a1000}
button.gold{background:linear-gradient(135deg,#f5b800,#d97706);color:#1a1000}
button.gray{background:linear-gradient(135deg,#6f6f88,#3f3f55)}
button.cyan{background:linear-gradient(135deg,#06b6d4,#0891b2)}
.btn-full{width:100%;padding:18px;font-size:16px;letter-spacing:2px}
.badge{display:inline-block;padding:4px 11px;border-radius:7px;font-size:10.5px;
 font-weight:800;letter-spacing:.5px;text-transform:uppercase}
.badge.success{background:rgba(16,240,152,.14);color:var(--success);
 border:1px solid rgba(16,240,152,.35)}
.badge.error{background:rgba(244,63,94,.14);color:var(--error);
 border:1px solid rgba(244,63,94,.35)}
.badge.warn{background:rgba(245,184,0,.14);color:var(--warn);
 border:1px solid rgba(245,184,0,.35)}
.badge.info{background:rgba(6,182,212,.14);color:var(--xore-2);
 border:1px solid rgba(6,182,212,.35)}
.badge.purple{background:rgba(139,92,246,.14);color:var(--xore-1);
 border:1px solid rgba(139,92,246,.35)}
.badge.off{background:rgba(111,111,136,.14);color:var(--muted);
 border:1px solid rgba(111,111,136,.35)}
.table{width:100%;border-collapse:collapse;font-size:12.5px}
.table th,.table td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--border)}
.table th{color:var(--muted);font-weight:800;text-transform:uppercase;
 font-size:10.5px;letter-spacing:1.1px;background:var(--bg-2);position:sticky;top:0;z-index:2}
.table tr:hover td{background:var(--card-2)}
.table tr.disabled td{opacity:.45}
.table tr.selected td{background:rgba(139,92,246,.08)}
.mono{font-family:'JetBrains Mono',monospace;font-size:12px}
.scroll-y{max-height:420px;overflow-y:auto;border:1px solid var(--border);border-radius:12px}
.scroll-y.tall{max-height:620px}
.hint{color:var(--muted);font-size:12.5px;margin-top:14px;padding:14px 18px;
 background:var(--bg-2);border-left:3px solid var(--xore-1);border-radius:8px;line-height:1.7}
.hint code{background:#000;padding:2px 8px;border-radius:5px;color:var(--xore-2);font-size:12px}
body.light .hint code{background:#e8e8f0;color:var(--xore-1)}
.result-box{display:flex;align-items:center;gap:20px;flex-wrap:wrap;
 padding:20px;background:var(--bg-2);border-radius:16px;margin-top:14px;
 border:1px solid var(--border)}
.result-box .big{font-size:36px;font-weight:900;line-height:1}
.result-box .big.green{color:var(--success)}
.result-box .big.red{color:var(--error)}
.result-box .big.purple{background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.result-box .big.cyan{background:linear-gradient(135deg,var(--xore-2),var(--xore-1));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.result-box .big.gold{background:linear-gradient(135deg,#f5b800,#d97706);
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.result-box .label{font-size:11px;color:var(--muted);
 text-transform:uppercase;letter-spacing:1.3px;font-weight:800;margin-bottom:6px}
.progress-outer{height:10px;background:var(--bg-2);border-radius:99px;overflow:hidden;
 border:1px solid var(--border);margin-top:12px}
.progress-inner{height:100%;width:0%;
 background:linear-gradient(90deg,#f5b800,#ec4899,#8b5cf6);
 transition:width .3s;border-radius:99px}
footer{margin-top:60px;padding-top:26px;border-top:1px solid var(--border);
 text-align:center;color:var(--muted);font-size:12.5px}
footer .xore{font-size:16px;font-weight:900;letter-spacing:8px;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3),var(--xore-2));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent;display:inline-block;margin-bottom:8px}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);
 border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite;
 vertical-align:middle;margin-left:8px}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.animate-in{animation:fadeIn .35s ease-out}
.blitz{border-color:rgba(245,184,0,.5);
 background:linear-gradient(180deg,rgba(245,184,0,.06),transparent)}
.admin-tag{display:inline-block;padding:3px 10px;background:linear-gradient(135deg,#8b5cf6,#ec4899);
 color:#fff;border-radius:6px;font-size:10px;font-weight:900;letter-spacing:1px;margin-left:8px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.toolbar input[type=search]{flex:1;min-width:220px;padding:10px 14px}
.preset-chip{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;
 background:var(--bg-2);border:1px solid var(--border);border-radius:99px;
 font-size:12px;font-weight:700;cursor:pointer;color:var(--muted);transition:all .15s}
.preset-chip:hover{border-color:var(--xore-2);color:var(--xore-2)}
.preset-chip button{background:transparent;padding:0;color:var(--error);
 font-size:14px;line-height:1;box-shadow:none;margin:0;min-width:0}
.log-line{padding:6px 10px;border-bottom:1px solid var(--border);
 font-family:'JetBrains Mono',monospace;font-size:11.5px;display:flex;gap:10px;align-items:center}
.log-line:last-child{border-bottom:none}
.log-line .time{color:var(--muted);flex-shrink:0}
.log-line .k{font-weight:800;flex-shrink:0}
.log-line .k.ghost{color:var(--xore-1)}
.log-line .k.blitz{color:var(--warn)}
.log-line .k.spam{color:var(--error)}
.log-line .k.watch{color:var(--success)}
.log-line .k.acct{color:var(--xore-2)}
.log-line .k.check{color:var(--xore-3)}
.log-line .msg{color:var(--text);opacity:.85;flex:1;overflow:hidden;
 text-overflow:ellipsis;white-space:nowrap}
.toast-wrap{position:fixed;bottom:30px;left:50%;transform:translateX(-50%);
 display:flex;flex-direction:column;gap:10px;z-index:99999;pointer-events:none;
 max-width:92vw}
.toast{pointer-events:auto;background:var(--card);border:1px solid var(--border);
 border-radius:12px;padding:12px 20px;font-weight:800;color:var(--text);
 box-shadow:0 10px 40px rgba(0,0,0,.35);display:flex;align-items:center;gap:10px;
 animation:fadeIn .25s ease-out;min-width:240px;max-width:600px}
.toast.success{border-color:rgba(16,240,152,.5);color:var(--success)}
.toast.error{border-color:rgba(244,63,94,.5);color:var(--error)}
.toast.warn{border-color:rgba(245,184,0,.5);color:var(--warn)}
.toast.info{border-color:rgba(6,182,212,.5);color:var(--xore-2)}
.mods{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0 20px}
.mod{display:inline-flex;align-items:center;gap:6px;padding:6px 12px;
 border-radius:99px;font-size:11px;font-weight:800;letter-spacing:.5px;
 text-transform:uppercase;background:var(--bg-2);border:1px solid var(--border);
 color:var(--muted);transition:all .2s}
.mod.on{color:var(--success);border-color:rgba(16,240,152,.6);
 box-shadow:0 0 16px rgba(16,240,152,.2)}
.mod.on .dot{background:var(--success);box-shadow:0 0 10px var(--success);
 animation:pulse 1.5s infinite}
.chk{width:18px;height:18px;accent-color:var(--xore-1);cursor:pointer}
.filters{display:flex;gap:6px;flex-wrap:wrap;margin:8px 0}
.fchip{padding:5px 12px;border-radius:99px;background:var(--bg-2);
 border:1px solid var(--border);font-size:11.5px;font-weight:700;
 cursor:pointer;color:var(--muted);transition:all .15s}
.fchip:hover{border-color:var(--xore-2);color:var(--xore-2)}
.fchip.active{background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 color:#fff;border-color:transparent}
.pager{display:flex;gap:6px;align-items:center;justify-content:center;
 margin-top:12px;flex-wrap:wrap;font-size:12px;color:var(--muted);font-weight:700}
.pager button{padding:6px 12px;font-size:12px;border-radius:8px}
.pw-cell{letter-spacing:1px;user-select:all}
.pw-hidden{filter:blur(4px);user-select:none}
.batch-bar{display:none;align-items:center;gap:10px;padding:12px 16px;
 background:linear-gradient(135deg,rgba(139,92,246,.12),rgba(236,72,153,.12));
 border:1px solid rgba(139,92,246,.4);border-radius:12px;margin-bottom:12px;
 flex-wrap:wrap}
.batch-bar.on{display:flex}
.batch-bar .count{font-weight:900;color:var(--xore-1)}
.inline-result{margin-top:14px;padding:0;border-radius:12px;overflow:hidden;
 max-height:0;transition:max-height .3s ease-out}
.inline-result.on{max-height:400px}
.dbg-line{padding:8px 10px;border-bottom:1px solid var(--border);
 font-family:'JetBrains Mono',monospace;font-size:11px;display:flex;
 gap:10px;align-items:center;flex-wrap:wrap}
.dbg-line .op{color:var(--xore-2);font-weight:800}
.dbg-line .len{color:var(--muted)}
.dbg-line .hh{color:var(--text);opacity:.6;font-size:10.5px;word-break:break-all;
 max-width:100%;overflow:hidden}
@media (max-width:640px){
 .container{padding:18px 12px 50px}
 .logo{font-size:38px;letter-spacing:8px}
 .hero-stat{padding:28px 36px}
 .hero-stat .val{font-size:52px}
 .stat .value{font-size:24px}
 .card{padding:16px}
 button,.btn{padding:12px 20px;font-size:13px}
 .table th,.table td{padding:8px 8px;font-size:11.5px}
 .toast{min-width:auto;font-size:12.5px;padding:10px 14px}
}
"""


def _wrap(title, body):
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — XORE</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Cairo:wght@400;600;800;900&family=JetBrains+Mono:wght@400;600;800&display=swap" rel="stylesheet">
<style>{BASE_CSS}</style>
</head>
<body>
<div class="container">
{body}
<footer>
  <div class="xore">XORE</div>
  <div>Powered by XORE · Free Fire OB55 · ME · v5.1 · DEV EDITION</div>
</footer>
</div>
<div class="toast-wrap" id="toastWrap"></div>
<script>
window.XORE_TOAST = function(msg, kind) {{
  kind = kind || 'info';
  const wrap = document.getElementById('toastWrap');
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  const icons = {{success:'✅',error:'❌',warn:'⚠️',info:'ℹ️'}};
  el.innerHTML = '<span>' + (icons[kind]||'') + '</span><span>' + msg + '</span>';
  wrap.appendChild(el);
  if (window.XORE_SOUND && window.XORE_SOUNDON) {{
    try {{
      const ctx = window.XORE_SOUND;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.frequency.value = kind === 'error' ? 220 : (kind === 'success' ? 880 : 550);
      osc.type = 'sine';
      gain.gain.value = 0.05;
      osc.connect(gain); gain.connect(ctx.destination);
      osc.start();
      osc.stop(ctx.currentTime + 0.1);
    }} catch(e) {{}}
  }}
  setTimeout(() => {{
    el.style.transition = 'opacity .3s, transform .3s';
    el.style.opacity = '0';
    el.style.transform = 'translateY(10px)';
    setTimeout(() => el.remove(), 320);
  }}, 3200);
}};
document.addEventListener('click', () => {{
  if (!window.XORE_SOUND && window.AudioContext) {{
    try {{ window.XORE_SOUND = new AudioContext(); }} catch(e) {{}}
  }}
}}, {{ once: true }});
</script>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
#  📄  PUBLIC PAGE
# ═══════════════════════════════════════════════════════════

def render_public():
    count = count_accounts()
    body = f"""
<div class="header">
  <div class="logo">XORE</div>
  <div class="tagline">FF BOT · OB55 · ME · GHOST</div>
  <div class="status-bar">
    <div class="pill live"><span class="dot"></span> ONLINE</div>
    <div class="pill">Speed 6x</div>
    <div class="pill">{HB_PER_ACCOUNT} اتصالات/حساب</div>
  </div>
</div>

<div class="hero">
  <div class="hero-stat">
    <div class="lbl">الحسابات المحمّلة</div>
    <div class="val">{count}</div>
  </div>
</div>

<div class="card">
  <h2>👻 تشغيل Ghost (4HB · Speed 6x)</h2>
  <form id="startForm" onsubmit="startBot(event)">
    <div class="input-row" style="flex-direction:column;gap:14px">
      <input type="text" name="team" id="teamInput"
             placeholder="أدخل كود الفريق (Team Code) هنا..."
             required minlength="1" maxlength="20" autocomplete="off"
             style="text-align:center;font-size:18px;padding:20px;
                    letter-spacing:3px;font-weight:800">
      <button type="submit" id="startBtn" class="btn btn-full">👻 بدء Ghost</button>
    </div>
  </form>

  <div id="progressWrap" style="display:none;margin-top:20px">
    <div style="display:flex;justify-content:space-between;margin-bottom:8px;
                font-size:12px;color:var(--muted);font-weight:700;letter-spacing:1px">
      <span>⏳ يشتغل البوت...</span>
      <span id="progressTime">0s</span>
    </div>
    <div class="progress-outer"><div id="progressBar" class="progress-inner"></div></div>
    <div id="progressStage" style="text-align:center;margin-top:12px;font-size:13px;
         color:var(--xore-2);font-weight:700;letter-spacing:1px">
      🔑 تسجيل الدخول للحسابات...
    </div>
  </div>

  <div id="resultWrap"></div>

  <div class="hint" style="text-align:center">
    اكتب كود الفريق، اضغط <strong>بدء Ghost</strong>.<br>
    كل حساب يفتح <strong>{HB_PER_ACCOUNT} اتصالات متوازية</strong> ويرسل JOIN + GHOST burst.
  </div>
</div>

<script>
const MAX_SESSION = {MAX_SESSION_SECONDS};
let timerInterval = null;
let startTime = 0;

function updateProgress() {{
  const elapsed = Math.floor((Date.now() - startTime) / 1000);
  document.getElementById('progressTime').textContent = elapsed + 's';
  const pct = Math.min(95, (elapsed / MAX_SESSION) * 100);
  document.getElementById('progressBar').style.width = pct + '%';
  const stageEl = document.getElementById('progressStage');
  if (elapsed < 3)       stageEl.textContent = '🔑 تسجيل دخول متوازي...';
  else if (elapsed < 6)  stageEl.textContent = '🌐 فتح {HB_PER_ACCOUNT} اتصالات/حساب...';
  else if (elapsed < 10) stageEl.textContent = '🎯 JOIN burst × 4...';
  else if (elapsed < 15) stageEl.textContent = '👻 GHOST burst × 4...';
  else                   stageEl.textContent = '🚪 EXIT وتنظيف...';
}}

async function startBot(e) {{
  e.preventDefault();
  const team = document.getElementById('teamInput').value.trim();
  if (!team) return;
  const btn = document.getElementById('startBtn');
  const progressWrap = document.getElementById('progressWrap');
  const resultWrap = document.getElementById('resultWrap');
  btn.disabled = true;
  btn.innerHTML = 'يشتغل...<span class="spinner"></span>';
  resultWrap.innerHTML = '';
  progressWrap.style.display = 'block';
  document.getElementById('progressBar').style.width = '0%';
  document.getElementById('progressTime').textContent = '0s';
  startTime = Date.now();
  timerInterval = setInterval(updateProgress, 200);
  try {{
    const r = await fetch('/start?team=' + encodeURIComponent(team) + '&format=json');
    const data = await r.json();
    clearInterval(timerInterval);
    document.getElementById('progressBar').style.width = '100%';
    document.getElementById('progressStage').textContent = '✅ اكتمل';
    setTimeout(() => {{ progressWrap.style.display = 'none'; }}, 800);
    renderResult(data);
    if (window.XORE_TOAST) {{
      const ok = (data.accounts_logged || 0) > 0;
      XORE_TOAST(ok ? ('نجح — ' + data.accounts_logged + ' حساب') : 'فشل التشغيل', ok ? 'success' : 'error');
    }}
  }} catch (err) {{
    clearInterval(timerInterval);
    progressWrap.style.display = 'none';
    resultWrap.innerHTML = `
      <div class="result-box animate-in" style="border-color:var(--error)">
        <div class="label" style="color:var(--error)">خطأ: ${{err.message}}</div>
      </div>`;
    if (window.XORE_TOAST) XORE_TOAST(err.message, 'error');
  }} finally {{
    btn.disabled = false;
    btn.innerHTML = '👻 بدء Ghost';
  }}
}}

function renderResult(r) {{
  const wrap = document.getElementById('resultWrap');
  const isOk = r.status === 'completed' && r.accounts_logged > 0;
  const logged = r.accounts_logged || 0;
  const ran = r.accounts_ran || 0;
  const elapsed = r.elapsed || 0;
  const team = r.team || '?';
  const results = (r.results || []).slice(0, 20);
  const badgeCls = s => s === 'success' ? 'success'
    : (String(s).includes('timeout') || s === 'no_team_data' ? 'warn' : 'error');
  const rowsHtml = results.map(x => {{
    const c1 = x.chat || '-'; const o1 = x.online || '-';
    const c2 = x.chat2 || '-'; const o2 = x.online2 || '-';
    return `<tr>
      <td class="mono">${{x.uid || '?'}}</td>
      <td><span class="badge ${{badgeCls(c1)}}">${{c1}}</span></td>
      <td><span class="badge ${{badgeCls(o1)}}">${{o1}}</span></td>
      <td><span class="badge ${{badgeCls(c2)}}">${{c2}}</span></td>
      <td><span class="badge ${{badgeCls(o2)}}">${{o2}}</span></td>
      <td class="mono">${{x.total_sent || 0}}</td>
    </tr>`;
  }}).join('') || '<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:20px">لا نتائج</td></tr>';
  const extra = (r.results || []).length > 20
    ? `<tr><td colspan="6" style="text-align:center;color:var(--muted);padding:12px">… و ${{r.results.length - 20}} حساب إضافي</td></tr>`
    : '';
  const badge = isOk ? '<span class="badge success">نجح</span>'
    : (r.status === 'failed' ? '<span class="badge error">فشل</span>' : '<span class="badge warn">غير معروف</span>');
  wrap.innerHTML = `
    <div class="animate-in" style="margin-top:24px">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px;
                  padding-bottom:16px;border-bottom:1px solid var(--border)">
        ${{badge}}
        <span class="badge purple">فريق: ${{team}}</span>
        <span class="badge info">${{elapsed}}s</span>
        <span class="badge info">${{r.hb_per_account || {HB_PER_ACCOUNT}}} HB/حساب</span>
      </div>
      <div class="stats" style="margin-bottom:20px">
        <div class="stat"><div class="label">حسابات دخلت</div>
          <div class="value green">${{logged}}</div></div>
        <div class="stat"><div class="label">حسابات نفذت</div>
          <div class="value purple">${{ran}}</div></div>
        <div class="stat"><div class="label">المدة</div>
          <div class="value cyan">${{elapsed}}s</div></div>
      </div>
      <h3 style="font-size:14px;font-weight:800;margin-bottom:12px;
                 letter-spacing:1px;color:var(--muted);text-transform:uppercase">
        📊 تفاصيل الحسابات
      </h3>
      <div style="overflow-x:auto;border:1px solid var(--border);border-radius:12px">
        <table class="table">
          <thead><tr><th>UID</th><th>ChaT</th><th>OnLinE</th>
            <th>ChaT2</th><th>OnLinE2</th><th>Sent</th></tr></thead>
          <tbody>${{rowsHtml}}${{extra}}</tbody>
        </table>
      </div>
    </div>`;
  wrap.scrollIntoView({{ behavior: 'smooth', block: 'nearest' }});
}}
</script>
"""
    return _wrap("XORE", body)


# ═══════════════════════════════════════════════════════════
#  📄  ADMIN PAGE — v5.1
# ═══════════════════════════════════════════════════════════

def render_admin(key):
    count = count_accounts()
    live = get_live_status()
    stats = _stats_snapshot()
    ws = _watch_snapshot(); sp = _spam_snapshot()
    bz = _blitz_snapshot(); gs = _ghost_snapshot()

    if live["checked"] and not live["checking"]:
        live_html = f"""
        <div class="result-box">
          <div><div class="label">شغّالة</div>
            <div class="big green">{live["alive"]}</div></div>
          <div style="width:1px;height:50px;background:var(--border)"></div>
          <div><div class="label">معطّلة</div>
            <div class="big red">{live["dead"]}</div></div>
          <div style="width:1px;height:50px;background:var(--border)"></div>
          <div><div class="label">الإجمالي</div>
            <div class="big purple">{live["total"]}</div></div>
          <div style="margin-right:auto"><span class="badge success">محدّث</span></div>
        </div>"""
    elif live["checking"]:
        live_html = '<div class="result-box"><div class="label">⏳ جاري الفحص...</div></div>'
    else:
        live_html = '<div class="result-box"><div class="label">لم يتم الفحص بعد</div></div>'

    mods_html = f"""
    <div class="mods">
      <span class="mod {'on' if gs['active'] else ''}">
        <span class="dot"></span> Ghost</span>
      <span class="mod {'on' if bz['active'] else ''}">
        <span class="dot"></span> Blitz</span>
      <span class="mod {'on' if sp['active'] else ''}">
        <span class="dot"></span> Spam</span>
      <span class="mod {'on' if ws['active'] else ''}">
        <span class="dot"></span> Watch</span>
      <span class="mod {'on' if live['checking'] else ''}">
        <span class="dot"></span> Check</span>
    </div>
    """

    body = f"""
<div class="header">
  <div class="logo">XORE</div>
  <div class="tagline"><span class="admin-tag">DEV v5.1</span> CONTROL PANEL</div>
  <div class="status-bar">
    <div class="pill live"><span class="dot"></span> ADMIN</div>
    <div class="pill">إجمالي: <span id="hdrTotal">{count}</span></div>
    <div class="pill">الحد: {MAX_ACCOUNTS}</div>
    <div class="pill">{HB_PER_ACCOUNT} HB/حساب</div>
    <div class="pill">Speed 6x</div>
    <button class="sm ghost" onclick="toggleTheme()" id="themeBtn">🌙</button>
    <button class="sm ghost" onclick="toggleSound()" id="soundBtn">🔇</button>
    <button class="sm ghost" onclick="toggleAutoRefresh()" id="arBtn">⏸ تلقائي</button>
  </div>
</div>

{mods_html}

<div class="stats" id="statsGrid">
  <div class="stat"><div class="label">حسابات محمّلة</div>
    <div class="value purple" id="s-total">{count}</div></div>
  <div class="stat"><div class="label">شغّالة</div>
    <div class="value green" id="s-alive">{live["alive"] if live["checked"] else "—"}</div></div>
  <div class="stat"><div class="label">معطّلة</div>
    <div class="value red" id="s-dead">{live["dead"] if live["checked"] else "—"}</div></div>
  <div class="stat"><div class="label">Ghost runs</div>
    <div class="value cyan" id="s-ghost">{stats.get("ghost_runs",0)}</div></div>
  <div class="stat"><div class="label">Blitz runs</div>
    <div class="value gold" id="s-blitz">{stats.get("blitz_runs",0)}</div></div>
  <div class="stat"><div class="label">Spam runs</div>
    <div class="value red" id="s-spam">{stats.get("spam_runs",0)}</div></div>
  <div class="stat"><div class="label">Watch runs</div>
    <div class="value green" id="s-watch">{stats.get("watch_runs",0)}</div></div>
  <div class="stat"><div class="label">Uptime</div>
    <div class="value cyan" style="font-size:22px" id="s-uptime">{stats.get("uptime",0)}s</div></div>
</div>

<!-- BLITZ -->
<div class="card blitz">
  <h2 style="color:var(--warn)">🌍 Global Blitz — انفجار عالمي</h2>
  <div class="input-row">
    <input type="text" id="blitzTeam" placeholder="كود الفريق..."
           minlength="1" maxlength="20" autocomplete="off" list="presetTeams">
    <input type="text" id="blitzCount" placeholder="عدد"
           value="{BLITZ_ACCOUNTS_MAX}" style="max-width:100px">
    <input type="text" id="blitzLinger" placeholder="مدة (s)"
           value="{BLITZ_LINGER_S}" style="max-width:100px">
    <input type="text" id="blitzMsg" placeholder="الرسالة"
           value="{WELCOME_MSG}" style="min-width:180px">
  </div>
  <div class="toolbar" style="margin-top:12px">
    <button onclick="startBlitz()" id="blitzBtn" class="gold" style="flex:1">
      🌍 ابدأ الانفجار
    </button>
    <button onclick="stopBlitz()" class="gray" style="flex:0">⏹ إيقاف</button>
    <button onclick="saveTeam('blitzTeam')" class="sm cyan">⭐ احفظ كود</button>
  </div>
  <div id="blitzPresets" style="margin-top:10px"></div>
  <div id="blitzStatus" style="margin-top:16px"></div>
</div>

<!-- GHOST -->
<div class="card">
  <h2>👻 Ghost (4HB · Speed 6x)</h2>
  <div class="input-row">
    <input type="text" id="ghostTeam" placeholder="كود الفريق..."
           minlength="1" maxlength="20" autocomplete="off" list="presetTeams">
    <button onclick="startGhost()" id="ghostBtn">👻 بدء Ghost</button>
    <button onclick="saveTeam('ghostTeam')" class="sm cyan">⭐ احفظ كود</button>
  </div>
  <div id="ghostResult" style="margin-top:14px"></div>
</div>

<!-- WATCH -->
<div class="card">
  <h2>👋 Auto-Welcome <span class="admin-tag">v5.1 FIX</span></h2>
  <p style="color:var(--muted);font-size:13px;margin-bottom:12px">
    الترحيب: <code style="background:#000;padding:2px 8px;border-radius:4px;color:var(--xore-2)">{WELCOME_MSG}</code>
    · قناة أساسية: {WELCOME_CHANNEL} · fallback: {WELCOME_CHANNELS_TRY}
  </p>
  <div class="input-row">
    <input type="text" id="watchTeam" placeholder="كود الفريق..."
           minlength="1" maxlength="20" autocomplete="off" list="presetTeams">
    <button onclick="startWatch()" id="watchBtn" class="green">👋 ابدأ</button>
    <button onclick="stopWatch()" class="danger">⏹ إيقاف</button>
    <button onclick="saveTeam('watchTeam')" class="sm cyan">⭐ احفظ</button>
  </div>
  <div id="watchStatus" style="margin-top:14px"></div>
  <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
    <button onclick="showWatchDebug()" class="sm cyan">🔍 عرض Packets</button>
    <button onclick="testWelcome()" class="sm purple" style="background:linear-gradient(135deg,var(--xore-1),var(--xore-3))">🧪 اختبار 4 قنوات</button>
  </div>
  <div id="watchDebugResult" style="margin-top:14px"></div>
</div>

<!-- SPAM -->
<div class="card" style="border-color:rgba(244,63,94,.5)">
  <h2 style="color:var(--error)">💥 Spam JOIN/EXIT</h2>
  <div class="input-row">
    <input type="text" id="spamTeam" placeholder="كود الفريق..."
           minlength="1" maxlength="20" autocomplete="off" list="presetTeams">
    <input type="text" id="spamRate" placeholder="تأخير/cycle (s)"
           value="{SPAM_RATE}" style="max-width:120px">
    <input type="text" id="spamDuration" placeholder="مدة (s)"
           value="{SPAM_DURATION}" style="max-width:120px">
    <input type="text" id="spamAccounts" placeholder="حسابات"
           value="{min(SPAM_ACCOUNTS_MAX, 30)}" style="max-width:120px">
  </div>
  <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap">
    <button onclick="startSpam()" id="spamBtn" class="danger">💥 بدء</button>
    <button onclick="stopSpam()" class="gray">⏹ إيقاف</button>
    <button onclick="saveTeam('spamTeam')" class="sm cyan">⭐ احفظ كود</button>
  </div>
  <div id="spamStatus" style="margin-top:14px"></div>
</div>

<!-- CHECK -->
<div class="card">
  <h2>🔍 فحص الحسابات</h2>
  <div class="toolbar">
    <button onclick="checkAccounts()" id="checkBtn">▶ فحص الكل</button>
  </div>
  <div id="liveResult">{live_html}</div>
</div>

<!-- ACCOUNTS MANAGER -->
<div class="card">
  <h2>👥 إدارة الحسابات <span class="badge purple" id="acctCountBadge">{count}</span></h2>

  <div id="addResult" style="margin-bottom:14px"></div>

  <textarea id="rawInput" placeholder="password:uid&#10;password:uid&#10;..." spellcheck="false"></textarea>
  <div style="margin-top:12px;display:flex;gap:10px;flex-wrap:wrap">
    <button type="button" onclick="submitAccounts('append')" class="green" id="btnAppend">➕ إضافة (AJAX)</button>
    <button type="button" onclick="submitAccounts('replace')" class="danger" id="btnReplace">🔄 استبدال الكل</button>
    <button type="button" onclick="exportAccounts('txt')" class="cyan">⬇ TXT</button>
    <button type="button" onclick="exportAccounts('csv')" class="cyan">⬇ CSV</button>
    <button type="button" onclick="exportAccounts('json')" class="cyan">⬇ JSON</button>
    <button type="button" onclick="clearAccounts()" class="gray">🗑 مسح الكل</button>
  </div>
  <div class="hint">
    الصيغة: <code>password:uid</code> سطر لكل حساب. التكرارات تُتجاهل. بدون إعادة تحميل الصفحة.
  </div>
</div>

<!-- ACCOUNT LIST -->
<div class="card">
  <h2>📋 قائمة الحسابات</h2>

  <div class="toolbar">
    <input type="search" id="accSearch" placeholder="🔎 ابحث في UID / Alias / Note..." oninput="onSearchChange()">
    <select id="sortSel" onchange="reloadList()" style="max-width:180px">
      <option value="added_desc">الأحدث أولاً</option>
      <option value="added_asc">الأقدم أولاً</option>
      <option value="uid_asc">UID تصاعدي</option>
      <option value="uid_desc">UID تنازلي</option>
      <option value="alias_asc">الاسم (A-Z)</option>
      <option value="status_alive">الحالة: شغّال</option>
      <option value="status_dead">الحالة: معطّل</option>
    </select>
    <select id="pageSizeSel" onchange="reloadList()" style="max-width:100px">
      <option value="25">25</option>
      <option value="50" selected>50</option>
      <option value="100">100</option>
      <option value="200">200</option>
    </select>
    <button onclick="reloadList()" class="sm cyan">🔄</button>
    <button onclick="toggleRevealAll()" class="sm gray" id="revealBtn">👁 كشف</button>
  </div>

  <div class="filters">
    <span class="fchip active" data-filter="all" onclick="setFilter('all')">الكل</span>
    <span class="fchip" data-filter="enabled" onclick="setFilter('enabled')">شغّال</span>
    <span class="fchip" data-filter="disabled" onclick="setFilter('disabled')">معطّل</span>
    <span class="fchip" data-filter="alive" onclick="setFilter('alive')">Alive</span>
    <span class="fchip" data-filter="dead" onclick="setFilter('dead')">Dead</span>
    <span class="fchip" data-filter="unknown" onclick="setFilter('unknown')">غير مفحوص</span>
  </div>

  <div class="batch-bar" id="batchBar">
    <span>محدد: <span class="count" id="batchCount">0</span></span>
    <button class="sm green" onclick="bulkOp('enable')">▶ تفعيل</button>
    <button class="sm warn" onclick="bulkOp('disable')">⏸ تعطيل</button>
    <button class="sm cyan" onclick="bulkOp('test')">🔍 اختبار</button>
    <button class="sm danger" onclick="bulkOp('delete')">🗑 حذف</button>
    <button class="sm gray" onclick="clearSelection()">✖ إلغاء</button>
  </div>

  <div class="scroll-y tall">
    <table class="table" id="accTable">
      <thead>
        <tr>
          <th style="width:34px"><input type="checkbox" class="chk" id="chkAll" onchange="toggleAll(this.checked)"></th>
          <th style="width:48px">#</th>
          <th>UID</th>
          <th>Alias / Note</th>
          <th>Password</th>
          <th>الحالة</th>
          <th style="width:230px">إجراءات</th>
        </tr>
      </thead>
      <tbody id="accBody"><tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px">تحميل...</td></tr></tbody>
    </table>
  </div>

  <div class="pager" id="pager"></div>
  <div style="text-align:center;margin-top:8px;font-size:12px;color:var(--muted)" id="pagerInfo"></div>
</div>

<!-- HISTORY -->
<div class="card">
  <h2>🕐 سجل الجلسات (آخر 50)</h2>
  <div class="scroll-y">
    <table class="table" id="historyTable">
      <thead><tr><th>الوقت</th><th>النوع</th><th>الفريق</th><th>حسابات</th></tr></thead>
      <tbody id="historyBody"><tr><td colspan="4" style="text-align:center;color:var(--muted);padding:16px">لا يوجد سجل</td></tr></tbody>
    </table>
  </div>
</div>

<!-- ACTIVITY LOG -->
<div class="card">
  <h2>📜 سجل النشاط المباشر</h2>
  <div class="scroll-y" id="activityLog" style="max-height:340px">
    <div style="padding:20px;text-align:center;color:var(--muted)">لا يوجد نشاط بعد...</div>
  </div>
</div>

<datalist id="presetTeams"></datalist>

<script>
const KEY = "{key}";
const MAX_ACCOUNTS = {MAX_ACCOUNTS};
const DEFAULT_WELCOME = "{WELCOME_MSG}";

const UI = {{
  page: 1, pageSize: 50, filter: 'all', sort: 'added_desc', q: '',
  reveal: false, autoRefresh: true,
  selected: new Set(),
  lastList: null,
}};

// ═══ PRESETS ═══
function getPresets() {{
  try {{ return JSON.parse(localStorage.getItem('xore_presets') || '[]'); }}
  catch {{ return []; }}
}}
function setPresets(arr) {{
  localStorage.setItem('xore_presets', JSON.stringify(arr.slice(0, 12)));
  renderPresets();
}}
function saveTeam(inputId) {{
  const v = document.getElementById(inputId).value.trim();
  if (!v) return;
  const p = getPresets();
  if (p.includes(v)) {{ toast('موجود مسبقاً', 'info'); return; }}
  p.unshift(v); setPresets(p); toast('تم الحفظ', 'success');
}}
function removeTeam(t) {{ setPresets(getPresets().filter(x => x !== t)); }}
function renderPresets() {{
  const p = getPresets();
  document.getElementById('presetTeams').innerHTML =
    p.map(t => `<option value="${{t}}">`).join('');
  const el = document.getElementById('blitzPresets');
  if (!el) return;
  if (!p.length) {{ el.innerHTML = ''; return; }}
  el.innerHTML = p.map(t =>
    `<span class="preset-chip" onclick="pickTeam('${{t}}')">
      ⭐ ${{t}}<button onclick="event.stopPropagation();removeTeam('${{t}}')">×</button>
    </span>`
  ).join(' ');
}}
function pickTeam(t) {{
  ['blitzTeam','ghostTeam','watchTeam','spamTeam'].forEach(id => {{
    const e = document.getElementById(id);
    if (e) e.value = t;
  }});
}}
renderPresets();

// ═══ UTILS ═══
function toast(msg, kind) {{ if (window.XORE_TOAST) window.XORE_TOAST(msg, kind || 'info'); }}
async function copyText(t) {{
  try {{
    await navigator.clipboard.writeText(t);
    toast('تم النسخ: ' + t, 'success');
  }} catch {{
    const ta = document.createElement('textarea');
    ta.value = t; document.body.appendChild(ta);
    ta.select(); document.execCommand('copy');
    document.body.removeChild(ta);
    toast('تم النسخ', 'success');
  }}
}}
function esc(s) {{
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}}

// ═══ THEME / SOUND / AUTOREFRESH ═══
function toggleTheme() {{
  const light = document.body.classList.toggle('light');
  document.getElementById('themeBtn').textContent = light ? '☀️' : '🌙';
  localStorage.setItem('xore_theme', light ? 'light' : 'dark');
}}
(function() {{
  if (localStorage.getItem('xore_theme') === 'light') {{
    document.body.classList.add('light');
    const b = document.getElementById('themeBtn'); if (b) b.textContent = '☀️';
  }}
}})();
function toggleSound() {{
  window.XORE_SOUNDON = !window.XORE_SOUNDON;
  document.getElementById('soundBtn').textContent = window.XORE_SOUNDON ? '🔔' : '🔇';
  localStorage.setItem('xore_sound', window.XORE_SOUNDON ? '1' : '0');
}}
window.XORE_SOUNDON = localStorage.getItem('xore_sound') === '1';
(function() {{
  const b = document.getElementById('soundBtn');
  if (b) b.textContent = window.XORE_SOUNDON ? '🔔' : '🔇';
}})();
function toggleAutoRefresh() {{
  UI.autoRefresh = !UI.autoRefresh;
  document.getElementById('arBtn').textContent = UI.autoRefresh ? '⏸ تلقائي' : '▶ تلقائي';
  toast(UI.autoRefresh ? 'التحديث التلقائي مفعل' : 'التحديث التلقائي موقوف', 'info');
}}

// ═══ INLINE ACCOUNT SUBMIT ═══
async function submitAccounts(mode) {{
  const raw = document.getElementById('rawInput').value;
  const out = document.getElementById('addResult');
  if (!raw.trim()) {{
    out.innerHTML = '<div class="result-box" style="border-color:var(--warn)"><div class="label" style="color:var(--warn)">⚠️ أدخل بيانات أولاً</div></div>';
    toast('الحقل فارغ', 'warn'); return;
  }}
  const btn = mode === 'replace' ? document.getElementById('btnReplace') : document.getElementById('btnAppend');
  const oldTxt = btn.textContent;
  btn.disabled = true; btn.textContent = '...';
  try {{
    const fd = new FormData();
    fd.append('raw', raw); fd.append('mode', mode); fd.append('key', KEY);
    const r = await fetch('/accounts/submit', {{ method: 'POST', body: fd }});
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'فشل');
    let extra = '';
    if (mode === 'append') {{
      extra = `أضيف: <strong style="color:var(--success)">${{d.added}}</strong> · متجاهل: <strong style="color:var(--warn)">${{d.skipped_dup}}</strong>`;
    }} else {{
      extra = `استُبدلت بـ <strong style="color:var(--success)">${{d.total}}</strong> حساب`;
    }}
    out.innerHTML = `
      <div class="result-box animate-in" style="border-color:var(--success)">
        <div><div class="label">الحالة</div>
          <div class="big green" style="font-size:22px">✅ نجح</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">الإجمالي الآن</div>
          <div class="big purple">${{d.total}}</div></div>
        <div style="margin-right:auto;color:var(--muted);font-size:13px">${{extra}}</div>
      </div>`;
    toast(mode === 'append' ? ('أضيف ' + d.added + ' حساب') : 'استُبدل الكل', 'success');
    document.getElementById('rawInput').value = '';
    localStorage.removeItem('xore_draft');
    document.getElementById('hdrTotal').textContent = d.total;
    document.getElementById('acctCountBadge').textContent = d.total;
    UI.page = 1;
    reloadList();
  }} catch (e) {{
    out.innerHTML = `<div class="result-box" style="border-color:var(--error)"><div class="label" style="color:var(--error)">❌ ${{esc(e.message)}}</div></div>`;
    toast(e.message, 'error');
  }} finally {{
    btn.disabled = false; btn.textContent = oldTxt;
  }}
}}

const rawEl = document.getElementById('rawInput');
rawEl.value = localStorage.getItem('xore_draft') || '';
rawEl.addEventListener('input', () => {{
  localStorage.setItem('xore_draft', rawEl.value);
}});

// ═══ EXPORT ═══
function exportAccounts(fmt) {{
  window.location.href = '/accounts/export-json?key=' + KEY + '&fmt=' + fmt;
}}

// ═══ ACCOUNT LIST ═══
let searchTimer = null;
function onSearchChange() {{
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {{
    UI.q = document.getElementById('accSearch').value.trim();
    UI.page = 1;
    reloadList();
  }}, 220);
}}
function setFilter(f) {{
  UI.filter = f; UI.page = 1;
  document.querySelectorAll('.fchip').forEach(c => {{
    c.classList.toggle('active', c.dataset.filter === f);
  }});
  reloadList();
}}
function toggleAll(chk) {{
  if (!UI.lastList) return;
  const items = UI.lastList.items || [];
  items.forEach(it => {{
    if (chk) UI.selected.add(it.uid);
    else UI.selected.delete(it.uid);
  }});
  renderBatchBar(); renderAccountRows();
}}
function clearSelection() {{
  UI.selected.clear(); renderBatchBar(); renderAccountRows();
}}
function toggleSelect(uid, chk) {{
  if (chk) UI.selected.add(uid);
  else UI.selected.delete(uid);
  renderBatchBar();
  const tr = document.querySelector(`tr[data-uid="${{uid}}"]`);
  if (tr) tr.classList.toggle('selected', chk);
}}
function renderBatchBar() {{
  const bar = document.getElementById('batchBar');
  const c = document.getElementById('batchCount');
  const n = UI.selected.size;
  bar.classList.toggle('on', n > 0);
  c.textContent = n;
}}
async function bulkOp(op) {{
  const uids = Array.from(UI.selected);
  if (!uids.length) return;
  if (op === 'delete') {{
    if (!confirm(`حذف ${{uids.length}} حساب؟`)) return;
  }}
  try {{
    const r = await fetch('/accounts/bulk', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ key: KEY, op, uids }}),
    }});
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'فشل');
    if (op === 'delete') toast(`حُذف ${{d.affected}}`, 'success');
    else if (op === 'enable') toast(`فُعّل ${{d.affected}}`, 'success');
    else if (op === 'disable') toast(`عُطّل ${{d.affected}}`, 'warn');
    else if (op === 'test') toast(`اختُبر ${{d.affected}} — شغّال:${{d.alive}} معطّل:${{d.dead}}`, 'info');
    UI.selected.clear(); renderBatchBar(); reloadList();
  }} catch (e) {{ toast(e.message, 'error'); }}
}}
async function reloadList() {{
  try {{
    const params = new URLSearchParams({{
      page: UI.page, page_size: UI.pageSize,
      filter: UI.filter, sort: UI.sort, q: UI.q,
    }});
    const r = await fetch('/accounts/list?' + params.toString());
    const d = await r.json();
    if (!d.ok) throw new Error(d.error || 'failed');
    UI.lastList = d;
    document.getElementById('acctCountBadge').textContent = d.total_all;
    document.getElementById('hdrTotal').textContent = d.total_all;
    renderAccountRows(); renderPager();
    UI.selected.forEach(uid => {{
      const tr = document.querySelector(`tr[data-uid="${{uid}}"]`);
      if (tr) tr.classList.add('selected');
    }});
  }} catch (e) {{
    document.getElementById('accBody').innerHTML =
      `<tr><td colspan="7" style="text-align:center;color:var(--error);padding:20px">خطأ: ${{esc(e.message)}}</td></tr>`;
  }}
}}
function renderAccountRows() {{
  const d = UI.lastList; if (!d) return;
  const items = d.items || [];
  if (!items.length) {{
    document.getElementById('accBody').innerHTML =
      '<tr><td colspan="7" style="text-align:center;color:var(--muted);padding:20px">لا نتائج</td></tr>';
    return;
  }}
  const statusBadge = (it) => {{
    if (!it.enabled) return '<span class="badge off">معطّل</span>';
    if (it.last_status === 'alive') return '<span class="badge success">شغّال</span>';
    if (it.last_status === 'dead') return '<span class="badge error">معطّل الحساب</span>';
    return '<span class="badge info">غير مفحوص</span>';
  }};
  const pwDisplay = UI.reveal ? esc(it.password)
    : `<span class="pw-hidden">${{esc(it.password)}}</span>`;
  document.getElementById('accBody').innerHTML = items.map((it, idx) => {{
    const num = (d.page - 1) * d.page_size + idx + 1;
    const sel = UI.selected.has(it.uid) ? 'selected' : '';
    const dis = it.enabled ? '' : 'disabled';
    const meta = [];
    if (it.alias) meta.push(`<strong>${{esc(it.alias)}}</strong>`);
    if (it.note) meta.push(`<span style="color:var(--muted);font-size:11.5px">${{esc(it.note)}}</span>`);
    const metaHtml = meta.join(' · ') || '<span style="color:var(--muted)">—</span>';
    return `<tr data-uid="${{esc(it.uid)}}" class="${{dis}} ${{sel}}">
      <td><input type="checkbox" class="chk" ${{UI.selected.has(it.uid)?'checked':''}}
                 onchange="toggleSelect('${{esc(it.uid)}}', this.checked)"></td>
      <td class="mono">${{num}}</td>
      <td class="mono">${{esc(it.uid)}}</td>
      <td>${{metaHtml}}</td>
      <td class="mono pw-cell">${{pwDisplay}}</td>
      <td>${{statusBadge(it)}}</td>
      <td style="white-space:nowrap">
        <button class="xs cyan" onclick="copyText('${{esc(it.uid)}}')" title="نسخ UID">📋</button>
        <button class="xs cyan" onclick="copyText('${{esc(it.password)}}')" title="نسخ PW">🔑</button>
        <button class="xs ${{it.enabled?'warn':'green'}}"
                onclick="toggleAccount('${{esc(it.uid)}}')">${{it.enabled?'⏸':'▶'}}</button>
        <button class="xs purple" style="background:linear-gradient(135deg,var(--xore-1),var(--xore-3))"
                onclick="testOne('${{esc(it.uid)}}')">🔍</button>
        <button class="xs gold" style="background:linear-gradient(135deg,#f5b800,#d97706);color:#1a1000"
                onclick="editMeta('${{esc(it.uid)}}')">✏️</button>
        <button class="xs danger" onclick="deleteAccount('${{esc(it.uid)}}')">🗑</button>
      </td>
    </tr>`;
  }}).join('');
}}
function renderPager() {{
  const d = UI.lastList;
  const totalPages = Math.max(1, Math.ceil(d.total_filtered / d.page_size));
  const pager = document.getElementById('pager');
  const info = document.getElementById('pagerInfo');
  info.textContent = `عرض ${{d.items.length}} من ${{d.total_filtered}} (إجمالي الكل: ${{d.total_all}})`;
  if (totalPages <= 1) {{ pager.innerHTML = ''; return; }}
  const cur = d.page; const buttons = [];
  buttons.push(`<button class="sm gray" onclick="goPage(1)" ${{cur===1?'disabled':''}}>⏮</button>`);
  buttons.push(`<button class="sm gray" onclick="goPage(${{cur-1}})" ${{cur===1?'disabled':''}}>◀</button>`);
  const start = Math.max(1, cur - 3), end = Math.min(totalPages, cur + 3);
  for (let p = start; p <= end; p++) {{
    buttons.push(`<button class="sm ${{p===cur?'cyan':'gray'}}" onclick="goPage(${{p}})">${{p}}</button>`);
  }}
  buttons.push(`<button class="sm gray" onclick="goPage(${{cur+1}})" ${{cur===totalPages?'disabled':''}}>▶</button>`);
  buttons.push(`<button class="sm gray" onclick="goPage(${{totalPages}})" ${{cur===totalPages?'disabled':''}}>⏭</button>`);
  pager.innerHTML = buttons.join('');
}}
function goPage(p) {{ UI.page = p; reloadList(); }}
function toggleRevealAll() {{
  UI.reveal = !UI.reveal;
  document.getElementById('revealBtn').textContent = UI.reveal ? '🙈 إخفاء' : '👁 كشف';
  renderAccountRows();
}}

async function toggleAccount(uid) {{
  try {{
    const r = await fetch('/accounts/toggle?uid=' + encodeURIComponent(uid) + '&key=' + KEY);
    const d = await r.json();
    if (d.ok) {{ toast(d.enabled ? 'مفعّل' : 'معطّل', d.enabled?'success':'warn'); reloadList(); }}
  }} catch (e) {{ toast(e.message, 'error'); }}
}}
async function deleteAccount(uid) {{
  if (!confirm('حذف ' + uid + '؟')) return;
  try {{
    const r = await fetch('/accounts/delete?uid=' + encodeURIComponent(uid) + '&key=' + KEY);
    const d = await r.json();
    if (d.ok) {{ toast('تم الحذف', 'success'); reloadList(); }}
  }} catch (e) {{ toast(e.message, 'error'); }}
}}
async function testOne(uid) {{
  toast('جاري اختبار ' + uid + '...', 'info');
  try {{
    const r = await fetch('/accounts/test-one?uid=' + encodeURIComponent(uid) + '&key=' + KEY,
      {{ method: 'POST' }});
    const d = await r.json();
    if (d.alive) toast('✅ شغّال: ' + (d.name || uid), 'success');
    else toast('❌ معطّل: ' + uid, 'error');
    reloadList();
  }} catch (e) {{ toast(e.message, 'error'); }}
}}
async function editMeta(uid) {{
  const it = (UI.lastList.items || []).find(x => x.uid === uid);
  if (!it) return;
  const alias = prompt('Alias:', it.alias || ''); if (alias === null) return;
  const note = prompt('ملاحظة:', it.note || ''); if (note === null) return;
  try {{
    const r = await fetch('/accounts/meta', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{ key: KEY, uid, alias, note }}),
    }});
    const d = await r.json();
    if (d.ok) {{ toast('تم التحديث', 'success'); reloadList(); }}
    else toast(d.error || 'فشل', 'error');
  }} catch (e) {{ toast(e.message, 'error'); }}
}}
async function clearAccounts() {{
  if (!confirm('مسح كل الحسابات؟ لا يمكن التراجع.')) return;
  if (!confirm('تأكيد أخير — سيتم حذف الكل.')) return;
  try {{
    const r = await fetch('/accounts/clear?key=' + KEY);
    const d = await r.json();
    if (d.ok) {{
      toast('حُذف ' + d.removed + ' حساب', 'success');
      reloadList();
      document.getElementById('hdrTotal').textContent = '0';
    }}
  }} catch (e) {{ toast(e.message, 'error'); }}
}}

// ═══ GHOST ═══
async function startGhost() {{
  const team = document.getElementById('ghostTeam').value.trim();
  if (!team) return toast('أدخل كود الفريق', 'warn');
  const btn = document.getElementById('ghostBtn');
  const out = document.getElementById('ghostResult');
  btn.disabled = true; btn.innerHTML = '...<span class="spinner"></span>';
  out.innerHTML = '<div class="result-box"><div class="label">⏳ يشتغل...</div></div>';
  try {{
    const r = await fetch('/start?team=' + encodeURIComponent(team) + '&format=json');
    const d = await r.json();
    out.innerHTML = `
      <div class="result-box">
        <div><div class="label">دخلت</div><div class="big green">${{d.accounts_logged||0}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">نفذت</div><div class="big purple">${{d.accounts_ran||0}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">مدة</div><div class="big cyan">${{d.elapsed||0}}s</div></div>
      </div>`;
    toast('Ghost: ' + (d.accounts_logged||0) + ' حساب', 'success');
  }} catch(e) {{
    out.innerHTML = `<div class="result-box"><div class="label" style="color:var(--error)">${{e.message}}</div></div>`;
    toast(e.message, 'error');
  }}
  btn.disabled = false; btn.innerHTML = '👻 بدء Ghost';
}}

// ═══ BLITZ ═══
async function startBlitz() {{
  const team = document.getElementById('blitzTeam').value.trim();
  const cnt = document.getElementById('blitzCount').value.trim() || '{BLITZ_ACCOUNTS_MAX}';
  const lng = document.getElementById('blitzLinger').value.trim() || '{BLITZ_LINGER_S}';
  const msg = document.getElementById('blitzMsg').value.trim() || DEFAULT_WELCOME;
  if (!team) return toast('أدخل كود الفريق', 'warn');
  const btn = document.getElementById('blitzBtn');
  btn.disabled = true; btn.textContent = '...';
  try {{
    const url = `/blitz?team=${{encodeURIComponent(team)}}&accounts=${{cnt}}&linger=${{lng}}`
      + `&msg=${{encodeURIComponent(msg)}}&key=${{KEY}}`;
    const r = await fetch(url);
    const d = await r.json();
    if (!d.ok) toast('خطأ: ' + (d.error || 'فشل'), 'error');
    else toast('Blitz بدأ على ' + d.accounts + ' حساب', 'success');
  }} catch(e) {{ toast(e.message, 'error'); }}
  btn.disabled = false; btn.textContent = '🌍 ابدأ الانفجار';
  refreshBlitz();
}}
async function stopBlitz() {{
  await fetch('/stop-blitz?key=' + KEY);
  refreshBlitz();
  toast('Blitz موقوف', 'warn');
}}
async function refreshBlitz() {{
  if (!UI.autoRefresh) return;
  try {{
    const r = await fetch('/blitz-status');
    const d = await r.json();
    const el = document.getElementById('blitzStatus');
    if (!d.active) {{ el.innerHTML = '<div class="result-box"><div class="label">غير نشط</div></div>'; return; }}
    const pct = d.total ? Math.floor((d.joined / d.total) * 100) : 0;
    const evs = (d.events || []).slice(0, 12).map(e =>
      `<tr><td class="mono">${{e.t}}</td><td>${{e.kind}}</td>
       <td class="mono">${{e.uid || '-'}}</td></tr>`).join('')
      || '<tr><td colspan="3" style="text-align:center;color:var(--muted)">لا أحداث</
