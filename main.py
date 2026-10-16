#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XORE FF BOT — v4.1 (FULL SINGLE FILE)
======================================
Public  : Ghost 4HB ONLY (speed 6x)
Admin   : Ghost + Global Blitz + Spam + Auto-Welcome + Live Check + Accounts
"""
import asyncio
import json
import os
import random
import socket
import struct
import threading
import time
import urllib3

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
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
WATCH_KEEPALIVE      = int(os.environ.get("WATCH_KEEPALIVE", "600"))
WATCH_KEEPALIVE_PING = int(os.environ.get("WATCH_KEEPALIVE_PING", "18"))
WATCH_BASELINE_WAIT  = float(os.environ.get("WATCH_BASELINE_WAIT", "3.0"))

SPAM_RATE            = float(os.environ.get("SPAM_RATE", "0.15"))
SPAM_DURATION        = int(os.environ.get("SPAM_DURATION", "120"))
SPAM_ACCOUNTS_MAX    = int(os.environ.get("SPAM_ACCOUNTS_MAX", "100"))

BLITZ_ACCOUNTS_MAX   = int(os.environ.get("BLITZ_ACCOUNTS_MAX", "100"))
BLITZ_LINGER_S       = float(os.environ.get("BLITZ_LINGER_S", "3.0"))
BLITZ_CHANNEL        = int(os.environ.get("BLITZ_CHANNEL", "2"))

XORE_DEBUG           = os.environ.get("XORE_DEBUG", "0") == "1"


def _log(*a):
    if XORE_DEBUG:
        print("[XORE]", *a, flush=True)


_DEFAULT_ACCOUNTS_RAW = os.environ.get("FF_ACCOUNTS_RAW", "") or """
S7L8QUXNKDY8-S1X_TEAM:4555612051
S7LFDZ8ZEEMF-S1X_TEAM:4555612941
S7LYRBXKENCE-S1X_TEAM:4555613802
S7LDK8QTXOX0-S1X_TEAM:4555613964
S7LZFLTWZ3J7-S1X_TEAM:4555614387
S7LEZNRDKML8-S1X_TEAM:4555614764
S7LHR6RDFK17-S1X_TEAM:4555614870
S7LXPOMEKAEI-S1X_TEAM:4555614971
S7LJ2WHEYG3P-S1X_TEAM:4555615013
S7LUP4A85QZR-S1X_TEAM:4555625755
"""


def _parse_accounts(raw):
    if not raw or not raw.strip():
        return []
    out = []
    for chunk in raw.replace(";", "\n").replace(",", "\n").splitlines():
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#") or ":" not in chunk:
            continue
        pw, uid = chunk.split(":", 1)
        pw, uid = pw.strip(), uid.strip()
        if pw and uid:
            out.append((uid, pw))
    return out[:MAX_ACCOUNTS]


_ACCOUNTS = _parse_accounts(_DEFAULT_ACCOUNTS_RAW)
_ACCOUNTS_LOCK = threading.Lock()

_LIVE_STATUS = {
    "checked": False, "total": 0, "alive": 0, "dead": 0,
    "checking": False, "results": [],
    "started_at": 0, "finished_at": 0,
}
_LIVE_LOCK = threading.Lock()

_WATCH_STATE = {
    "active": False, "team": None, "started_at": 0,
    "sessions": 0, "welcomed": 0, "events": [],
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


def get_accounts():
    with _ACCOUNTS_LOCK:
        return list(_ACCOUNTS)


def add_accounts(raw):
    with _ACCOUNTS_LOCK:
        existing = {(u, p) for u, p in _ACCOUNTS}
        added = 0
        for u, p in _parse_accounts(raw):
            if (u, p) not in existing and len(_ACCOUNTS) < MAX_ACCOUNTS:
                _ACCOUNTS.append((u, p)); existing.add((u, p)); added += 1
        return added


def replace_accounts(raw):
    global _ACCOUNTS
    new_list = _parse_accounts(raw)
    with _ACCOUNTS_LOCK:
        _ACCOUNTS = new_list[:MAX_ACCOUNTS]
    return len(_ACCOUNTS)


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


def _extract_member_uids(packet):
    uids = set()
    if not isinstance(packet, dict):
        return uids

    def walk(node, depth=0):
        if depth > 8 or not isinstance(node, dict):
            return
        for k, v in node.items():
            if isinstance(v, dict) and "data" in v:
                d = v["data"]
                if isinstance(d, int) and 100_000 < d < 99_999_999_999:
                    uids.add(d)
                walk(d, depth + 1)
            elif isinstance(v, list):
                for item in v:
                    walk(item, depth + 1)
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
        1: 100,
        2: {
            1: int(bot_uid),
            2: text,
            3: int(channel),
        },
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
        return None
    access_token = td["access_token"]; open_id = td["open_id"]
    if not access_token or not open_id:
        return None
    login_payload = PyL(access_token, open_id)
    ml = MajorLogin(login_payload)
    if not ml:
        return None
    ad = ExtractMajorLogin(ml)
    if not ad:
        return None

    jwt = ad["jwt"]; ts = ad["ts"]; key = ad["key"]; iv = ad["iv"]
    url = ad["url"] or "https://clientbp.ppmainecoonghj.com"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    account_id = ad["account_id"]

    ld = GeTLoginDaTa(url, login_payload, jwt)
    if not ld:
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
        return None
    ip, port = func_addr.split(":")
    ip2, port2 = info_addr.split(":")
    if not account_id:
        account_id = gi(1) or gi(5) or 0
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

        if watch_state is not None and WELCOME_ENABLED:
            result["status"] = "watching"
            watch_deadline = time.time() + WATCH_KEEPALIVE
            last_ping = time.time()
            s.settimeout(0.8)

            while (time.time() < watch_deadline
                   and not watch_state["stop"].is_set()):
                try:
                    data = s.recv(65536)
                    if not data:
                        break
                    hx = data.hex()
                    if not hx.startswith("0500") or len(hx) < 20:
                        continue
                    try:
                        js = DeCode_PackEt(hx[10:])
                        if not js: continue
                        packet = json.loads(js)
                    except Exception:
                        continue

                    members = _extract_member_uids(packet)
                    if not members: continue

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
                        if nu == int(uid): continue
                        is_new = False
                        with watch_state["lock"]:
                            if nu not in watch_state["known"]:
                                watch_state["known"].add(nu)
                                is_new = True
                        if is_new:
                            try:
                                pkt = Send_TeamChat(
                                    uid, WELCOME_MSG, squad_code,
                                    key, iv, channel=WELCOME_CHANNEL)
                                s.sendall(pkt)
                                result["welcomed"] += 1
                                _watch_push_event("welcome", uid=nu)
                            except Exception as ex:
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
#  💥  SPAM MODE
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
                    _spam_push("join", uid)
                except Exception:
                    _spam_push("error", uid); break

            time.sleep(rate)

            for _ in range(3):
                if stop_event.is_set(): break
                try:
                    s.sendall(exit_pkt); exits += 1
                    _spam_push("exit", uid)
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


# ═══════════════════════════════════════════════════════════
#  🌍  GLOBAL BLITZ
# ═══════════════════════════════════════════════════════════

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
#  🎨  CSS
# ═══════════════════════════════════════════════════════════

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#06060a;--bg-2:#0d0d14;--card:#12121b;--card-2:#1a1a26;
 --border:#25253a;--text:#eaeaf2;--muted:#6f6f88;
 --xore-1:#8b5cf6;--xore-2:#06b6d4;--xore-3:#ec4899;
 --success:#10f098;--warn:#f5b800;--error:#f43f5e}
html,body{background:var(--bg);color:var(--text);
 font-family:'Cairo','JetBrains Mono',system-ui,sans-serif;
 min-height:100vh;line-height:1.65}
body::before{content:'';position:fixed;inset:0;pointer-events:none;z-index:-1;
 background:radial-gradient(circle at 15% 5%,rgba(139,92,246,.14),transparent 45%),
 radial-gradient(circle at 85% 95%,rgba(6,182,212,.14),transparent 45%)}
a{color:var(--xore-2);text-decoration:none}
a:hover{color:var(--xore-3)}
.container{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
.header{text-align:center;margin-bottom:40px;padding:40px 20px;position:relative}
.header::after{content:'';position:absolute;bottom:0;left:50%;transform:translateX(-50%);
 width:80px;height:2px;background:linear-gradient(90deg,transparent,var(--xore-1),var(--xore-2),transparent)}
.logo{font-size:56px;font-weight:900;letter-spacing:14px;margin-bottom:6px;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3),var(--xore-2));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent;
 filter:drop-shadow(0 0 40px rgba(139,92,246,.45))}
.tagline{color:var(--muted);font-size:12px;letter-spacing:6px;text-transform:uppercase;font-weight:700}
.status-bar{display:flex;align-items:center;justify-content:center;gap:12px;margin-top:22px;flex-wrap:wrap}
.pill{display:inline-flex;align-items:center;gap:8px;padding:7px 16px;
 border-radius:999px;background:var(--card);border:1px solid var(--border);
 font-size:12px;font-weight:700;color:var(--muted)}
.pill.live{color:var(--success);border-color:rgba(16,240,152,.3)}
.pill.live .dot{background:var(--success);box-shadow:0 0 12px var(--success);animation:pulse 2s infinite}
.dot{width:8px;height:8px;border-radius:50%}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
.hero{display:flex;justify-content:center;margin:40px 0}
.hero-stat{background:var(--card);border:1px solid var(--border);border-radius:24px;
 padding:40px 60px;text-align:center;position:relative;overflow:hidden;min-width:280px}
.hero-stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
 background:linear-gradient(90deg,var(--xore-1),var(--xore-3),var(--xore-2))}
.hero-stat .lbl{font-size:12px;color:var(--muted);text-transform:uppercase;
 letter-spacing:2px;font-weight:800;margin-bottom:12px}
.hero-stat .val{font-size:72px;font-weight:900;line-height:1;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:18px;margin-bottom:32px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:18px;
 padding:22px;position:relative;overflow:hidden;transition:transform .15s}
.stat:hover{transform:translateY(-3px)}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
 background:linear-gradient(90deg,var(--xore-1),var(--xore-3),var(--xore-2))}
.stat .label{font-size:11px;color:var(--muted);text-transform:uppercase;
 letter-spacing:1.5px;margin-bottom:10px;font-weight:800}
.stat .value{font-size:32px;font-weight:900;line-height:1}
.stat .value.purple{background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat .value.cyan{background:linear-gradient(135deg,var(--xore-2),var(--xore-1));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.stat .value.green{color:var(--success)}
.stat .value.red{color:var(--error)}
.card{background:var(--card);border:1px solid var(--border);border-radius:20px;
 padding:26px;margin-bottom:22px}
.card h2{font-size:17px;font-weight:800;margin-bottom:20px;
 display:flex;align-items:center;gap:12px}
.card h2::before{content:'';width:5px;height:22px;border-radius:3px;
 background:linear-gradient(180deg,var(--xore-1),var(--xore-2))}
.input-row{display:flex;gap:12px;flex-wrap:wrap}
input[type=text],textarea{flex:1;background:var(--bg-2);
 border:1.5px solid var(--border);border-radius:12px;padding:15px 18px;
 color:var(--text);font-family:inherit;font-size:14px;outline:none;
 transition:border-color .15s,box-shadow .15s;min-width:200px}
input[type=text]:focus,textarea:focus{border-color:var(--xore-1);
 box-shadow:0 0 0 4px rgba(139,92,246,.12)}
textarea{resize:vertical;min-height:180px;font-family:'JetBrains Mono',monospace;
 font-size:12.5px;line-height:1.7}
button,.btn{display:inline-block;padding:15px 30px;border-radius:12px;
 font-weight:800;font-family:inherit;font-size:14px;letter-spacing:.8px;
 border:none;cursor:pointer;transition:all .18s;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 color:#fff;box-shadow:0 8px 24px -8px rgba(139,92,246,.7);text-align:center}
button:hover,.btn:hover{transform:translateY(-2px)}
button:disabled{opacity:.5;cursor:not-allowed;transform:none}
button.ghost,.btn.ghost{background:transparent;color:var(--xore-2);
 border:1.5px solid var(--xore-2);box-shadow:none}
button.danger{background:linear-gradient(135deg,var(--error),#b91c1c)}
button.green{background:linear-gradient(135deg,var(--success),#059669);color:#04140c}
button.warn{background:linear-gradient(135deg,var(--warn),#c2410c);color:#1a1000}
button.gold{background:linear-gradient(135deg,#f5b800,#d97706);color:#1a1000}
.btn-full{width:100%;padding:18px;font-size:16px;letter-spacing:2px}
.badge{display:inline-block;padding:5px 13px;border-radius:7px;font-size:11px;
 font-weight:800;letter-spacing:.6px;text-transform:uppercase}
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
.table{width:100%;border-collapse:collapse;font-size:13px}
.table th,.table td{text-align:left;padding:12px 14px;border-bottom:1px solid var(--border)}
.table th{color:var(--muted);font-weight:800;text-transform:uppercase;
 font-size:11px;letter-spacing:1.2px;background:var(--bg-2)}
.table tr:hover td{background:var(--card-2)}
.mono{font-family:'JetBrains Mono',monospace;font-size:12.5px}
.hint{color:var(--muted);font-size:12.5px;margin-top:14px;padding:14px 18px;
 background:var(--bg-2);border-left:3px solid var(--xore-1);border-radius:8px;line-height:1.7}
.hint code{background:#000;padding:3px 8px;border-radius:5px;color:var(--xore-2);font-size:12px}
.result-box{display:flex;align-items:center;gap:20px;flex-wrap:wrap;
 padding:22px;background:var(--bg-2);border-radius:16px;margin-top:16px;
 border:1px solid var(--border)}
.result-box .big{font-size:38px;font-weight:900;line-height:1}
.result-box .big.green{color:var(--success)}
.result-box .big.red{color:var(--error)}
.result-box .big.purple{background:linear-gradient(135deg,var(--xore-1),var(--xore-3));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.result-box .big.cyan{background:linear-gradient(135deg,var(--xore-2),var(--xore-1));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.result-box .big.gold{background:linear-gradient(135deg,#f5b800,#d97706);
 -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.result-box .label{font-size:11px;color:var(--muted);
 text-transform:uppercase;letter-spacing:1.4px;font-weight:800;margin-bottom:6px}
.progress-outer{height:10px;background:var(--bg-2);border-radius:99px;overflow:hidden;
 border:1px solid var(--border);margin-top:12px}
.progress-inner{height:100%;width:0%;
 background:linear-gradient(90deg,#f5b800,#ec4899,#8b5cf6);
 transition:width .3s;border-radius:99px}
footer{margin-top:70px;padding-top:28px;border-top:1px solid var(--border);
 text-align:center;color:var(--muted);font-size:12.5px}
footer .xore{font-size:16px;font-weight:900;letter-spacing:8px;
 background:linear-gradient(135deg,var(--xore-1),var(--xore-3),var(--xore-2));
 -webkit-background-clip:text;-webkit-text-fill-color:transparent;display:inline-block;margin-bottom:8px}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{display:inline-block;width:16px;height:16px;border:2px solid rgba(255,255,255,.3);
 border-top-color:#fff;border-radius:50%;animation:spin 1s linear infinite;
 vertical-align:middle;margin-left:8px}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px)}to{opacity:1;transform:translateY(0)}}
.animate-in{animation:fadeIn .4s ease-out}
.blitz{border-color:rgba(245,184,0,.5);
 background:linear-gradient(180deg,rgba(245,184,0,.06),transparent)}
.admin-tag{display:inline-block;padding:3px 10px;background:linear-gradient(135deg,#8b5cf6,#ec4899);
 color:#fff;border-radius:6px;font-size:10px;font-weight:900;letter-spacing:1px;
 margin-right:8px}
@media (max-width:600px){
 .container{padding:20px 14px 50px}
 .logo{font-size:38px;letter-spacing:8px}
 .hero-stat{padding:30px 40px}
 .hero-stat .val{font-size:56px}
 .stat .value{font-size:26px}
 .card{padding:18px}
 button,.btn{padding:13px 22px;font-size:13px}
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
  <div>Powered by XORE · Free Fire OB55 · ME · v4.1</div>
</footer>
</div>
</body>
</html>"""


# ═══════════════════════════════════════════════════════════
#  📄  PUBLIC PAGE — GHOST ONLY
# ═══════════════════════════════════════════════════════════

def render_public():
    count = len(get_accounts())
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
  }} catch (err) {{
    clearInterval(timerInterval);
    progressWrap.style.display = 'none';
    resultWrap.innerHTML = `
      <div class="result-box animate-in" style="border-color:var(--error)">
        <div class="label" style="color:var(--error)">خطأ: ${{err.message}}</div>
      </div>`;
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
#  📄  ADMIN PAGE
# ═══════════════════════════════════════════════════════════

def render_admin(key):
    accs = get_accounts()
    count = len(accs)
    live = get_live_status()

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

    rows = "".join(
        f'<tr><td class="mono">{i+1}</td><td class="mono">{u}</td>'
        f'<td class="mono">{p[:10]}…{p[-6:] if len(p)>16 else ""}</td></tr>'
        for i, (u, p) in enumerate(accs[:60])
    )
    more = (f'<tr><td colspan="3" style="text-align:center;color:var(--muted);'
            f'padding:16px">… و {count-60} إضافي</td></tr>') if count > 60 else ""

    body = f"""
<div class="header">
  <div class="logo">XORE</div>
  <div class="tagline"><span class="admin-tag">DEV</span> ADMIN PANEL · v4.1 · ALL FEATURES</div>
  <div class="status-bar">
    <div class="pill live"><span class="dot"></span> ADMIN</div>
    <div class="pill">إجمالي: {count}</div>
    <div class="pill">الحد: {MAX_ACCOUNTS}</div>
    <div class="pill">{HB_PER_ACCOUNT} HB/حساب</div>
    <div class="pill">Speed 6x</div>
  </div>
</div>

<div class="stats">
  <div class="stat"><div class="label">الحسابات المحمّلة</div>
    <div class="value purple">{count}</div></div>
  <div class="stat"><div class="label">حسابات شغّالة</div>
    <div class="value green">{live["alive"] if live["checked"] else "—"}</div></div>
  <div class="stat"><div class="label">حسابات معطّلة</div>
    <div class="value red">{live["dead"] if live["checked"] else "—"}</div></div>
  <div class="stat"><div class="label">Global Blitz حد</div>
    <div class="value cyan">{BLITZ_ACCOUNTS_MAX}</div></div>
</div>

<!-- GLOBAL BLITZ -->
<div class="card blitz">
  <h2 style="color:var(--warn)">🌍 Global Blitz — انفجار عالمي</h2>
  <p style="color:var(--muted);font-size:13.5px;margin-bottom:14px">
    <strong style="color:var(--warn)">{BLITZ_ACCOUNTS_MAX} حساب</strong> يدخلون <strong>العالمية</strong> عشوائياً،
    يرسلون رسالة، ثم <strong>يخرجون بعد {BLITZ_LINGER_S} ثانية</strong>.
  </p>
  <div class="input-row">
    <input type="text" id="blitzTeam" placeholder="كود الفريق..."
           minlength="1" maxlength="20" autocomplete="off">
    <input type="text" id="blitzCount" placeholder="عدد"
           value="{BLITZ_ACCOUNTS_MAX}" style="max-width:110px">
    <input type="text" id="blitzLinger" placeholder="مدة (s)"
           value="{BLITZ_LINGER_S}" style="max-width:110px">
    <input type="text" id="blitzMsg" placeholder="الرسالة"
           value="{WELCOME_MSG}" style="min-width:200px">
  </div>
  <div style="margin-top:14px;display:flex;gap:12px;flex-wrap:wrap">
    <button onclick="startBlitz()" id="blitzBtn" class="gold" style="flex:1">
      🌍 ابدأ الانفجار العالمي
    </button>
    <button onclick="stopBlitz()" style="background:linear-gradient(135deg,#6f6f88,#3f3f55)">
      ⏹ إيقاف</button>
  </div>
  <div id="blitzStatus" style="margin-top:16px"></div>
</div>

<!-- GHOST -->
<div class="card">
  <h2>👻 تشغيل Ghost (4HB · Speed 6x)</h2>
  <form method="get" action="/start" target="_blank">
    <input type="hidden" name="key" value="{key}">
    <div class="input-row">
      <input type="text" name="team" placeholder="كود الفريق..."
             required minlength="1" maxlength="20" autocomplete="off">
      <button type="submit">👻 START</button>
    </div>
  </form>
</div>

<!-- CHECK -->
<div class="card">
  <h2>🔍 فحص الحسابات الحية</h2>
  <button onclick="checkAccounts()" id="checkBtn">▶ فحص الآن</button>
  <div id="liveResult">{live_html}</div>
</div>

<!-- WATCH -->
<div class="card">
  <h2>👋 وضع الترحيب التلقائي</h2>
  <p style="color:var(--muted);font-size:13.5px;margin-bottom:14px">
    البوت يبقى متصل ويترحّب بكل عضو جديد:
    <code style="background:#000;padding:2px 8px;border-radius:4px;
          color:var(--xore-2)">{WELCOME_MSG}</code>
    <span style="color:var(--muted);font-size:12px">
      (قناة: {WELCOME_CHANNEL} — 1=فريق, 2=عالم, 3=سكواد)
    </span>
  </p>
  <div class="input-row">
    <input type="text" id="watchTeam" placeholder="كود الفريق..."
           minlength="1" maxlength="20" autocomplete="off">
    <button onclick="startWatch()" id="watchBtn" class="green">👋 بدء الترحيب</button>
    <button onclick="stopWatch()" class="danger">⏹ إيقاف</button>
  </div>
  <div id="watchStatus" style="margin-top:16px"></div>
</div>

<!-- SPAM -->
<div class="card" style="border-color:rgba(244,63,94,.5)">
  <h2 style="color:var(--error)">💥 سبام دخول وخروج</h2>
  <div class="input-row">
    <input type="text" id="spamTeam" placeholder="كود الفريق..."
           minlength="1" maxlength="20" autocomplete="off">
    <input type="text" id="spamRate" placeholder="تأخير/cycle (s)"
           value="{SPAM_RATE}" style="max-width:140px">
    <input type="text" id="spamDuration" placeholder="المدة (s)"
           value="{SPAM_DURATION}" style="max-width:140px">
    <input type="text" id="spamAccounts" placeholder="حسابات"
           value="{min(SPAM_ACCOUNTS_MAX, 30)}" style="max-width:140px">
  </div>
  <div style="margin-top:14px;display:flex;gap:12px;flex-wrap:wrap">
    <button onclick="startSpam()" id="spamBtn" class="danger">💥 بدء السبام</button>
    <button onclick="stopSpam()" style="background:linear-gradient(135deg,#6f6f88,#3f3f55)">
      ⏹ إيقاف السبام</button>
  </div>
  <div id="spamStatus" style="margin-top:16px"></div>
</div>

<!-- ACCOUNTS -->
<div class="card">
  <h2>➕ إدارة الحسابات</h2>
  <form method="post" action="/replace">
    <input type="hidden" name="key" value="{key}">
    <textarea name="raw"
placeholder="password1:uid1&#10;password2:uid2&#10;... (حتى {MAX_ACCOUNTS})"></textarea>
    <div style="margin-top:16px;display:flex;gap:12px;flex-wrap:wrap">
      <button type="submit" name="mode" value="replace" class="danger">🔄 استبدال</button>
      <button type="submit" name="mode" value="append" class="green">➕ إضافة</button>
    </div>
  </form>
  <div class="hint">الصيغة: <code>password:uid</code> — سطر لكل حساب.</div>
</div>

<div class="card">
  <h2>👥 قائمة الحسابات ({count})</h2>
  <table class="table">
    <thead><tr><th style="width:50px">#</th><th>UID</th><th>Password</th></tr></thead>
    <tbody>{rows}{more}</tbody>
  </table>
</div>

<script>
async function checkAccounts() {{
  const btn = document.getElementById('checkBtn');
  const out = document.getElementById('liveResult');
  btn.disabled = true; btn.textContent = '⏳ ...';
  out.innerHTML = '<div class="result-box"><div class="label">⏳ يفحص...</div></div>';
  try {{
    const r = await fetch('/check?key={key}', {{ method: 'POST' }});
    const data = await r.json();
    if (!data.ok) throw new Error(data.error || 'failed');
    out.innerHTML = `
      <div class="result-box">
        <div><div class="label">شغّالة</div><div class="big green">${{data.alive}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">معطّلة</div><div class="big red">${{data.dead}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">الإجمالي</div><div class="big purple">${{data.total}}</div></div>
        <div style="margin-right:auto"><span class="badge success">محدّث</span></div>
      </div>`;
  }} catch (e) {{
    out.innerHTML = `<div class="result-box"><div class="label" style="color:var(--error)">خطأ: ${{e.message}}</div></div>`;
  }} finally {{
    btn.disabled = false; btn.textContent = '▶ إعادة الفحص';
  }}
}}

async function refreshWatch() {{
  try {{
    const r = await fetch('/watch-status');
    const d = await r.json();
    const el = document.getElementById('watchStatus');
    if (!d.active) {{
      el.innerHTML = '<div class="result-box"><div class="label">غير نشط</div></div>';
      return;
    }}
    const evs = (d.events || []).slice(0, 8).map(e =>
      `<tr><td class="mono">${{e.t}}</td><td>${{e.kind}}</td>
       <td class="mono">${{e.uid || '-'}}</td></tr>`).join('')
      || '<tr><td colspan="3" style="text-align:center;color:var(--muted)">لا أحداث</td></tr>';
    el.innerHTML = `
      <div class="result-box">
        <div><div class="label">الفريق</div>
          <div class="big purple" style="font-size:22px">${{d.team||'?'}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">جلسات</div><div class="big green">${{d.sessions}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">رحّب</div><div class="big cyan">${{d.welcomed}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">مدة</div><div class="big purple">${{d.uptime||0}}s</div></div>
      </div>
      <table class="table" style="margin-top:14px">
        <thead><tr><th>الوقت</th><th>الحدث</th><th>UID</th></tr></thead>
        <tbody>${{evs}}</tbody>
      </table>`;
  }} catch(e) {{}}
}}

async function startWatch() {{
  const team = document.getElementById('watchTeam').value.trim();
  if (!team) return;
  const btn = document.getElementById('watchBtn');
  btn.disabled = true; btn.textContent = '...';
  try {{
    const r = await fetch('/watch?team=' + encodeURIComponent(team) + '&key={key}');
    const d = await r.json();
    if (!d.ok) alert('خطأ: ' + (d.error || 'فشل'));
  }} catch(e) {{ alert(e.message); }}
  btn.disabled = false; btn.textContent = '👋 بدء الترحيب';
  refreshWatch();
}}

async function stopWatch() {{
  await fetch('/stop-watch?key={key}');
  refreshWatch();
}}

async function refreshSpam() {{
  try {{
    const r = await fetch('/spam-status');
    const d = await r.json();
    const el = document.getElementById('spamStatus');
    if (!d.active) {{
      el.innerHTML = '<div class="result-box"><div class="label">غير نشط</div></div>';
      return;
    }}
    const evs = (d.events || []).slice(0, 8).map(e =>
      `<tr><td class="mono">${{e.t}}</td><td>${{e.kind}}</td>
       <td class="mono">${{e.uid || '-'}}</td></tr>`).join('')
      || '<tr><td colspan="3" style="text-align:center;color:var(--muted)">لا أحداث</td></tr>';
    el.innerHTML = `
      <div class="result-box">
        <div><div class="label">الفريق</div>
          <div class="big purple" style="font-size:22px">${{d.team||'?'}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">حسابات</div><div class="big cyan">${{d.accounts}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">دورات</div><div class="big green">${{d.cycles}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">JOIN</div><div class="big green">${{d.joins}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">EXIT</div><div class="big red">${{d.exits}}</div></div>
      </div>
      <table class="table" style="margin-top:14px">
        <thead><tr><th>الوقت</th><th>الحدث</th><th>UID</th></tr></thead>
        <tbody>${{evs}}</tbody>
      </table>`;
  }} catch(e) {{}}
}}

async function refreshBlitz() {{
  try {{
    const r = await fetch('/blitz-status');
    const d = await r.json();
    const el = document.getElementById('blitzStatus');
    if (!d.active) {{
      el.innerHTML = '<div class="result-box"><div class="label">غير نشط</div></div>';
      return;
    }}
    const pct = d.total ? Math.floor((d.joined / d.total) * 100) : 0;
    const evs = (d.events || []).slice(0, 12).map(e =>
      `<tr><td class="mono">${{e.t}}</td><td>${{e.kind}}</td>
       <td class="mono">${{e.uid || '-'}}</td></tr>`).join('')
      || '<tr><td colspan="3" style="text-align:center;color:var(--muted)">لا أحداث بعد...</td></tr>';
    el.innerHTML = `
      <div class="result-box">
        <div><div class="label">دخلوا</div><div class="big green">${{d.joined}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">رحّبوا</div><div class="big gold">${{d.welcomed}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">خرجوا</div><div class="big red">${{d.exited}}</div></div>
        <div style="width:1px;height:50px;background:var(--border)"></div>
        <div><div class="label">أخطاء</div><div class="big red" style="font-size:22px">${{d.errors}}</div></div>
      </div>
      <div class="progress-outer" style="margin-top:14px">
        <div class="progress-inner" style="width:${{pct}}%"></div>
      </div>
      <div style="text-align:center;margin-top:8px;font-size:12px;color:var(--muted);font-weight:700">
        ${{d.joined}}/${{d.total}} — ${{pct}}%
      </div>
      <table class="table" style="margin-top:14px">
        <thead><tr><th>الوقت</th><th>الحدث</th><th>UID</th></tr></thead>
        <tbody>${{evs}}</tbody>
      </table>`;
  }} catch(e) {{}}
}}

async function startSpam() {{
  const team = document.getElementById('spamTeam').value.trim();
  const rate = document.getElementById('spamRate').value.trim() || '0.15';
  const dur = document.getElementById('spamDuration').value.trim() || '120';
  const accs = document.getElementById('spamAccounts').value.trim() || '30';
  if (!team) return;
  const btn = document.getElementById('spamBtn');
  btn.disabled = true; btn.textContent = '...';
  try {{
    const url = `/spam?team=${{encodeURIComponent(team)}}&rate=${{rate}}`
      + `&duration=${{dur}}&accounts=${{accs}}&key={key}`;
    const r = await fetch(url);
    const d = await r.json();
    if (!d.ok) alert('خطأ: ' + (d.error || 'فشل'));
  }} catch(e) {{ alert(e.message); }}
  btn.disabled = false; btn.textContent = '💥 بدء السبام';
  refreshSpam();
}}

async function stopSpam() {{
  await fetch('/stop-spam?key={key}');
  refreshSpam();
}}

async function startBlitz() {{
  const team = document.getElementById('blitzTeam').value.trim();
  const cnt = document.getElementById('blitzCount').value.trim() || '{BLITZ_ACCOUNTS_MAX}';
  const lng = document.getElementById('blitzLinger').value.trim() || '{BLITZ_LINGER_S}';
  const msg = document.getElementById('blitzMsg').value.trim() || '{WELCOME_MSG}';
  if (!team) return;
  const btn = document.getElementById('blitzBtn');
  btn.disabled = true; btn.textContent = '...';
  try {{
    const url = `/blitz?team=${{encodeURIComponent(team)}}`
      + `&accounts=${{cnt}}&linger=${{lng}}`
      + `&msg=${{encodeURIComponent(msg)}}&key={key}`;
    const r = await fetch(url);
    const d = await r.json();
    if (!d.ok) alert('خطأ: ' + (d.error || 'فشل'));
  }} catch(e) {{ alert(e.message); }}
  btn.disabled = false; btn.textContent = '🌍 ابدأ الانفجار العالمي';
  refreshBlitz();
}}

async function stopBlitz() {{
  await fetch('/stop-blitz?key={key}');
  refreshBlitz();
}}

setInterval(refreshWatch, 3000);
setInterval(refreshSpam, 2500);
setInterval(refreshBlitz, 1500);
refreshWatch(); refreshSpam(); refreshBlitz();
</script>
"""
    return _wrap("Admin", body)


# ═══════════════════════════════════════════════════════════
#  🚀  FASTAPI APP
# ═══════════════════════════════════════════════════════════

app = FastAPI(title="XORE FF Bot", version="4.1.0")


@app.get("/", response_class=HTMLResponse)
def root(key: str = Query("")):
    if key and is_admin(key):
        return render_admin(key)
    return render_public()


@app.get("/health")
def health():
    ws = _watch_snapshot(); sp = _spam_snapshot(); bz = _blitz_snapshot()
    return {
        "ok": True, "version": "4.1.0",
        "hb_per_account": HB_PER_ACCOUNT,
        "max_session_seconds": MAX_SESSION_SECONDS,
        "welcome_enabled": WELCOME_ENABLED,
        "welcome_msg": WELCOME_MSG,
        "welcome_channel": WELCOME_CHANNEL,
        "watch_active": ws["active"], "watch_team": ws["team"],
        "spam_active": sp["active"], "spam_team": sp["team"],
        "blitz_active": bz["active"], "blitz_team": bz["team"],
        "speed_multiplier": 6,
    }


@app.post("/check")
def check_live(key: str = Query("")):
    if not is_admin(key):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "invalid key"})
    accounts = get_accounts()
    if not accounts:
        return {"ok": False, "error": "no accounts"}
    _set_live_status(checking=True, checked=False,
                     total=len(accounts), started_at=time.time())
    results = []
    with ThreadPoolExecutor(max_workers=min(len(accounts), LOGIN_POOL)) as pool:
        futures = {pool.submit(login_account, u, p): u for u, p in accounts}
        for f in as_completed(futures, timeout=90):
            uid = futures[f]
            try:
                r = f.result(timeout=LOGIN_TIMEOUT + 4)
            except Exception:
                r = None
            results.append({"uid": uid, "ok": r is not None,
                            "name": r["name"] if r else None,
                            "error": None if r else "login failed"})
    alive = sum(1 for r in results if r["ok"])
    dead = len(results) - alive
    _set_live_status(checking=False, checked=True,
                     total=len(results), alive=alive, dead=dead,
                     results=results, finished_at=time.time())
    return {"ok": True, "total": len(results), "alive": alive,
            "dead": dead, "results": results}


@app.get("/start")
def start_bot(
    team: str = Query(..., min_length=1, max_length=20),
    key: str = Query(""),
    format: str = Query("json"),
):
    if not team.strip():
        raise HTTPException(400, "Team code required")
    start_time = time.time()
    deadline = start_time + MAX_SESSION_SECONDS
    accounts = get_accounts()
    if not accounts:
        return JSONResponse(status_code=400, content={
            "status": "failed", "reason": "no accounts",
            "team": team, "results": [],
        })
    sessions = []; login_errors = []
    with ThreadPoolExecutor(max_workers=min(len(accounts), LOGIN_POOL)) as pool:
        futures = {uid: pool.submit(login_account, uid, pw)
                   for uid, pw in accounts}
        for uid, f in futures.items():
            try:
                r = f.result(timeout=LOGIN_TIMEOUT)
            except Exception as e:
                r = None
                login_errors.append({"uid": uid, "error": str(e)})
            if r:
                sessions.append(r)
            else:
                login_errors.append({"uid": uid, "error": "login failed"})
    if not sessions:
        return JSONResponse(status_code=502, content={
            "status": "failed", "reason": "no sessions",
            "team": team, "elapsed": round(time.time() - start_time, 2),
            "login_errors": login_errors, "results": [],
            "accounts_logged": 0, "accounts_ran": 0,
            "hb_per_account": HB_PER_ACCOUNT,
        })
    barrier = threading.Barrier(len(sessions) * HB_PER_ACCOUNT)
    results = []; threads = []
    for s in sessions:
        t = threading.Thread(
            target=lambda sd=s: results.extend(
                run_one_account(sd, team, barrier, deadline)),
            daemon=True)
        threads.append(t); t.start()
    for t in threads:
        t.join(timeout=max(0.1, deadline - time.time()))
    by_account = {}
    for r in results:
        uid = str(r.get("uid"))
        e = by_account.setdefault(uid, {
            "uid": uid, "chat": None, "online": None,
            "chat2": None, "online2": None,
            "total_sent": 0, "errors": []})
        tag = r["tag"]
        if   tag == "ChaT":    e["chat"]    = r["status"]
        elif tag == "OnLinE":  e["online"]  = r["status"]
        elif tag == "ChaT2":   e["chat2"]   = r["status"]
        elif tag == "OnLinE2": e["online2"] = r["status"]
        e["total_sent"] += r.get("sent", 0)
        if r.get("error"): e["errors"].append(f"{tag}: {r['error']}")
    return {
        "status": "completed", "team": team,
        "elapsed": round(time.time() - start_time, 2),
        "accounts_logged": len(sessions),
        "accounts_ran": len(by_account),
        "hb_per_account": HB_PER_ACCOUNT,
        "login_errors": login_errors,
        "results": list(by_account.values()),
    }


@app.get("/watch")
def watch_bot(
    team: str = Query(..., min_length=1, max_length=20),
    key: str = Query(""),
    duration: int = Query(0),
):
    if not team.strip():
        raise HTTPException(400, "Team code required")
    if not is_admin(key):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "invalid key"})
    snap = _watch_snapshot()
    if snap["active"]:
        return JSONResponse(status_code=409, content={
            "ok": False, "error": "watch already active",
            "team": snap["team"], "sessions": snap["sessions"],
        })
    global _WATCH_STOP_EVENTS
    stop_event = threading.Event()
    _WATCH_STOP_EVENTS.append(stop_event)
    accounts = get_accounts()
    if not accounts:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "no accounts"})
    sessions_data = []; login_errors = []
    with ThreadPoolExecutor(max_workers=min(len(accounts), LOGIN_POOL)) as pool:
        futures = {uid: pool.submit(login_account, uid, pw)
                   for uid, pw in accounts}
        for uid, f in futures.items():
            try:
                r = f.result(timeout=LOGIN_TIMEOUT)
            except Exception as e:
                r = None
                login_errors.append({"uid": uid, "error": str(e)})
            if r: sessions_data.append(r)
            else: login_errors.append({"uid": uid, "error": "login failed"})
    if not sessions_data:
        return JSONResponse(status_code=502, content={
            "ok": False, "error": "no sessions",
            "login_errors": login_errors,
        })
    barrier = threading.Barrier(len(sessions_data))

    def _watch_worker(sd):
        ws = {
            "stop": stop_event,
            "lock": threading.Lock(),
            "known": {int(sd["uid"])},
            "baseline_done": False,
            "started": time.time(),
        }
        try:
            run_one_account(sd, team, barrier, time.time() + 60, ws)
        except Exception:
            pass

    for sd in sessions_data:
        threading.Thread(target=_watch_worker, args=(sd,),
                         daemon=True).start()

    with _WATCH_LOCK:
        _WATCH_STATE["active"] = True
        _WATCH_STATE["team"] = team
        _WATCH_STATE["started_at"] = time.time()
        _WATCH_STATE["sessions"] = len(sessions_data)
        _WATCH_STATE["welcomed"] = 0
        _WATCH_STATE["events"] = []

    if duration > 0:
        def _auto_stop():
            time.sleep(duration)
            stop_event.set()
            with _WATCH_LOCK:
                _WATCH_STATE["active"] = False
        threading.Thread(target=_auto_stop, daemon=True).start()

    return {
        "ok": True, "team": team,
        "sessions": len(sessions_data),
        "login_errors": login_errors,
        "welcome_msg": WELCOME_MSG,
        "keepalive_s": WATCH_KEEPALIVE,
        "duration_s": duration or WATCH_KEEPALIVE,
    }


@app.get("/stop-watch")
def stop_watch(key: str = Query("")):
    if not is_admin(key):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "invalid key"})
    global _WATCH_STOP_EVENTS
    with _WATCH_LOCK:
        n = len(_WATCH_STOP_EVENTS)
        for ev in _WATCH_STOP_EVENTS:
            ev.set()
        _WATCH_STOP_EVENTS.clear()
        _WATCH_STATE["active"] = False
    return {"ok": True, "stopped": n}


@app.get("/watch-status")
def watch_status():
    snap = _watch_snapshot()
    if snap["active"]:
        snap["uptime"] = round(time.time() - snap["started_at"], 1)
    return {"ok": True, **snap, "welcome_msg": WELCOME_MSG}


@app.get("/spam")
def spam_bot(
    team: str = Query(..., min_length=1, max_length=20),
    key: str = Query(""),
    rate: float = Query(SPAM_RATE),
    duration: int = Query(SPAM_DURATION),
    accounts: int = Query(20),
):
    if not team.strip():
        raise HTTPException(400, "Team code required")
    if not is_admin(key):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "invalid key"})
    snap = _spam_snapshot()
    if snap["active"]:
        return JSONResponse(status_code=409, content={
            "ok": False, "error": "spam already active",
            "team": snap["team"],
        })

    rate = max(0.02, min(rate, 5.0))
    duration = max(5, min(duration, 1800))
    accounts = max(1, min(accounts, SPAM_ACCOUNTS_MAX))

    all_accs = get_accounts()
    if not all_accs:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "no accounts"})
    sel = all_accs[:accounts]

    sessions_data = []; login_errors = []
    with ThreadPoolExecutor(max_workers=min(len(sel), LOGIN_POOL)) as pool:
        futures = {uid: pool.submit(login_account, uid, pw)
                   for uid, pw in sel}
        for uid, f in futures.items():
            try:
                r = f.result(timeout=LOGIN_TIMEOUT)
            except Exception as e:
                r = None
                login_errors.append({"uid": uid, "error": str(e)})
            if r: sessions_data.append(r)
            else: login_errors.append({"uid": uid, "error": "login failed"})

    if not sessions_data:
        return JSONResponse(status_code=502, content={
            "ok": False, "error": "no sessions",
            "login_errors": login_errors,
        })

    global _SPAM_STOP_EVENTS
    stop_event = threading.Event()
    _SPAM_STOP_EVENTS.append(stop_event)

    def _spam_worker(sd):
        try:
            _SpamCycle(sd, team, stop_event, rate, duration)
        except Exception:
            _spam_push("error", sd["uid"])

    for sd in sessions_data:
        threading.Thread(target=_spam_worker, args=(sd,),
                         daemon=True).start()

    with _SPAM_LOCK:
        _SPAM_STATE["active"] = True
        _SPAM_STATE["team"] = team
        _SPAM_STATE["started_at"] = time.time()
        _SPAM_STATE["accounts"] = len(sessions_data)
        _SPAM_STATE["cycles"] = 0
        _SPAM_STATE["joins"] = 0
        _SPAM_STATE["exits"] = 0
        _SPAM_STATE["errors"] = 0
        _SPAM_STATE["events"] = []

    def _auto_stop():
        time.sleep(duration + 2)
        stop_event.set()
        with _SPAM_LOCK:
            _SPAM_STATE["active"] = False
    threading.Thread(target=_auto_stop, daemon=True).start()

    return {
        "ok": True, "team": team,
        "accounts": len(sessions_data),
        "rate_s": rate, "duration_s": duration,
        "login_errors": login_errors,
    }


@app.get("/stop-spam")
def stop_spam(key: str = Query("")):
    if not is_admin(key):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "invalid key"})
    global _SPAM_STOP_EVENTS
    with _SPAM_LOCK:
        n = len(_SPAM_STOP_EVENTS)
        for ev in _SPAM_STOP_EVENTS:
            ev.set()
        _SPAM_STOP_EVENTS.clear()
        _SPAM_STATE["active"] = False
    return {"ok": True, "stopped": n}


@app.get("/spam-status")
def spam_status():
    snap = _spam_snapshot()
    if snap["active"]:
        snap["uptime"] = round(time.time() - snap["started_at"], 1)
    return {"ok": True, **snap}


# ═══════════════════════════════════════════════════════════
#  🌍  GLOBAL BLITZ ENDPOINTS
# ═══════════════════════════════════════════════════════════

@app.get("/blitz")
def blitz_bot(
    team: str = Query(..., min_length=1, max_length=20),
    key: str = Query(""),
    accounts: int = Query(BLITZ_ACCOUNTS_MAX),
    linger: float = Query(BLITZ_LINGER_S),
    msg: str = Query(WELCOME_MSG),
):
    if not team.strip():
        raise HTTPException(400, "Team code required")
    if not is_admin(key):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "invalid key"})
    snap = _blitz_snapshot()
    if snap["active"]:
        return JSONResponse(status_code=409, content={
            "ok": False, "error": "blitz already active",
            "team": snap["team"],
        })

    accounts = max(10, min(int(accounts), BLITZ_ACCOUNTS_MAX, MAX_ACCOUNTS))
    linger   = max(0.5, min(float(linger), 30.0))
    msg      = (msg or WELCOME_MSG)[:120]

    all_accs = get_accounts()
    if not all_accs:
        return JSONResponse(status_code=400,
                            content={"ok": False, "error": "no accounts"})
    sel = all_accs[:accounts]
    random.shuffle(sel)

    login_errors = []
    sessions_data = []
    with ThreadPoolExecutor(max_workers=min(len(sel), LOGIN_POOL)) as pool:
        futures = {uid: pool.submit(login_account, uid, pw)
                   for uid, pw in sel}
        for uid, f in futures.items():
            try:
                r = f.result(timeout=LOGIN_TIMEOUT)
            except Exception as e:
                r = None
                login_errors.append({"uid": uid, "error": str(e)})
            if r: sessions_data.append(r)
            else: login_errors.append({"uid": uid, "error": "login failed"})

    if not sessions_data:
        return JSONResponse(status_code=502, content={
            "ok": False, "error": "no sessions",
            "login_errors": login_errors,
        })

    global _BLITZ_STOP_EVENTS
    stop_event = threading.Event()
    _BLITZ_STOP_EVENTS.append(stop_event)

    with _BLITZ_LOCK:
        _BLITZ_STATE["active"] = True
        _BLITZ_STATE["team"] = team
        _BLITZ_STATE["started_at"] = time.time()
        _BLITZ_STATE["accounts"] = len(sessions_data)
        _BLITZ_STATE["joined"] = 0
        _BLITZ_STATE["welcomed"] = 0
        _BLITZ_STATE["exited"] = 0
        _BLITZ_STATE["errors"] = 0
        _BLITZ_STATE["events"] = []
        _BLITZ_STATE["total"] = len(sessions_data)

    def _worker(sd):
        try:
            _BlitzWorker(sd, team, stop_event, linger, msg)
        except Exception:
            _blitz_push("error", sd["uid"])

    for sd in sessions_data:
        threading.Thread(target=_worker, args=(sd,), daemon=True).start()

    def _auto_finalize():
        time.sleep(linger + 30)
        with _BLITZ_LOCK:
            _BLITZ_STATE["active"] = False
    threading.Thread(target=_auto_finalize, daemon=True).start()

    return {
        "ok": True, "team": team,
        "accounts": len(sessions_data),
        "linger_s": linger,
        "channel": BLITZ_CHANNEL,
        "login_errors": login_errors,
        "msg": msg,
    }


@app.get("/stop-blitz")
def stop_blitz(key: str = Query("")):
    if not is_admin(key):
        return JSONResponse(status_code=403,
                            content={"ok": False, "error": "invalid key"})
    global _BLITZ_STOP_EVENTS
    with _BLITZ_LOCK:
        n = len(_BLITZ_STOP_EVENTS)
        for ev in _BLITZ_STOP_EVENTS:
            ev.set()
        _BLITZ_STOP_EVENTS.clear()
        _BLITZ_STATE["active"] = False
    return {"ok": True, "stopped": n}


@app.get("/blitz-status")
def blitz_status():
    snap = _blitz_snapshot()
    if snap["active"]:
        snap["uptime"] = round(time.time() - snap["started_at"], 1)
    return {"ok": True, **snap}


@app.post("/replace")
async def replace_endpoint(request: Request):
    form = await request.form()
    raw = form.get("raw", "") or ""
    mode = form.get("mode", "replace")
    key = form.get("key", "") or ""
    if not is_admin(key):
        return HTMLResponse(_wrap("Error", """
            <div class="card"><h2 style="color:var(--error)">❌ مفتاح غير صحيح</h2>
            <a href="/" class="btn">← الرجوع</a></div>"""), status_code=403)
    if not raw.strip():
        return HTMLResponse(_wrap("Error", f"""
            <div class="card"><h2 style="color:var(--error)">❌ لا يوجد بيانات</h2>
            <a href="/?key={key}" class="btn">← الرجوع</a></div>"""))
    if mode == "append":
        added = add_accounts(raw)
        msg = f"تمت إضافة {added} حساب"
    else:
        n = replace_accounts(raw)
        msg = f"تم استبدال الحسابات — الإجمالي {n} حساب"
    return HTMLResponse(_wrap("Done", f"""
        <div class="header">
          <div class="logo" style="font-size:34px;letter-spacing:8px">DONE</div>
        </div>
        <div class="card">
          <h2>✅ نجح</h2>
          <p style="font-size:16px;margin-bottom:20px">{msg}</p>
          <div class="stats">
            <div class="stat"><div class="label">الإجمالي الآن</div>
              <div class="value purple">{len(get_accounts())}</div></div>
          </div>
          <div style="margin-top:20px">
            <a href="/?key={key}" class="btn">← الرجوع للوحة</a>
          </div>
        </div>"""))


@app.get("/api/status")
def api_status():
    live = get_live_status(); ws = _watch_snapshot()
    sp = _spam_snapshot(); bz = _blitz_snapshot()
    return {
        "status": "ok", "version": "4.1.0",
        "accounts": len(get_accounts()),
        "max_accounts": MAX_ACCOUNTS,
        "hb_per_account": HB_PER_ACCOUNT,
        "max_session_seconds": MAX_SESSION_SECONDS,
        "alive": live["alive"] if live["checked"] else None,
        "dead": live["dead"] if live["checked"] else None,
        "watch_active": ws["active"],
        "spam_active": sp["active"],
        "blitz_active": bz["active"],
        "release": "OB55", "region": "ME",
        "speed_multiplier": 6,
    }


# ═══════════════════════════════════════════════════════════
#  🏁  ENTRY
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    _log(f"XORE v4.1 starting port {port}, "
         f"HB={HB_PER_ACCOUNT}, pool={LOGIN_POOL}, "
         f"blitz_max={BLITZ_ACCOUNTS_MAX}, linger={BLITZ_LINGER_S}s")
    uvicorn.run(app, host="0.0.0.0", port=port,
                log_level="info", access_log=False)
