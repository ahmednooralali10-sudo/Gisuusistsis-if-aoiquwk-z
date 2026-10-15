"""
FF Ghost Bot API
================
خادم FastAPI لبوت فري فاير — يشتغل على Vercel.

Endpoints:
    GET  /                            → حالة الخدمة
    GET  /login                       → تسجيل دخول كل الحسابات فقط
    GET  /start?team=<code>           → تشغيل التسلسل الكامل (JOIN → INV → GHOST → EXIT)

Author : ALPHA XK
Version: 1.0.0
Python : 3.12
"""

# ═══════════════════════════════════════════════════════════
#  IMPORTS
# ═══════════════════════════════════════════════════════════

import json
import random
import socket
import threading
import time
import urllib3

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from concurrent.futures import ThreadPoolExecutor

try:
    import blackboxprotobuf
    HAS_BLACKBOX = True
except ImportError:
    HAS_BLACKBOX = False
    print("[WARN] blackboxprotobuf not installed — decoding disabled")


urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ═══════════════════════════════════════════════════════════
#  ⚙️ CONFIG
# ═══════════════════════════════════════════════════════════

# مفاتيح AES الخاصة بفري فاير
xK = b"Yg&tc%DEuh6%Zc^8"
xV = b"6oyZDr22E3ychjM%"

# الحسابات: (UID, Password)
ACCOUNTS = [
    ("4555625950", "S7LYQLRHGKY8-S1X_TEAM"),
]

# الحد الأقصى لمدة الجلسة بالثواني
MAX_SESSION_SECONDS = 50


# ═══════════════════════════════════════════════════════════
#  🔐 CRYPTO / PROTOBUF HELPERS
# ═══════════════════════════════════════════════════════════

def EnV_VaRiAnT(n: int) -> bytes:
    """ترميز عدد صحيح كـ varint."""
    out = []
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            b |= 0x80
        out.append(b)
        if not n:
            break
    return bytes(out)


def ProToBuF(fields: dict) -> bytes:
    """بناء رسالة protobuf من dict."""
    p = bytearray()
    for f, v in fields.items():
        if isinstance(v, bool):
            p.extend(EnV_VaRiAnT((f << 3) | 0))
            p.extend(EnV_VaRiAnT(1 if v else 0))
        elif isinstance(v, int):
            p.extend(EnV_VaRiAnT((f << 3) | 0))
            p.extend(EnV_VaRiAnT(v))
        elif isinstance(v, str):
            d = v.encode()
            p.extend(EnV_VaRiAnT((f << 3) | 2))
            p.extend(EnV_VaRiAnT(len(d)))
            p.extend(d)
        elif isinstance(v, (bytes, bytearray)):
            d = bytes(v)
            p.extend(EnV_VaRiAnT((f << 3) | 2))
            p.extend(EnV_VaRiAnT(len(d)))
            p.extend(d)
    return bytes(p)


def Read_VaRiAnT(data: bytes, pos: int):
    """قراءة varint من bytes."""
    result = 0
    shift = 0
    while pos < len(data):
        b = data[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            break
        shift += 7
    return result, pos


def Parse_ProToBuF(data: bytes) -> dict:
    """تحليل protobuf خام إلى dict."""
    fields = {}
    pos = 0
    n = len(data)
    while pos < n:
        try:
            key, pos = Read_VaRiAnT(data, pos)
        except Exception:
            break
        fn = key >> 3
        wt = key & 0x07
        try:
            if wt == 0:
                val, pos = Read_VaRiAnT(data, pos)
            elif wt == 2:
                ln, pos = Read_VaRiAnT(data, pos)
                val = data[pos:pos + ln]
                pos += ln
            elif wt == 5:
                val = data[pos:pos + 4]
                pos += 4
            elif wt == 1:
                val = data[pos:pos + 8]
                pos += 8
            else:
                break
        except Exception:
            break
        fields.setdefault(fn, []).append(val)
    return fields


def Ua() -> str:
    """User-Agent عشوائي لتقليد الأجهزة الحقيقية."""
    return random.choice([
        "4.0.18P6", "4.0.19P7", "4.0.20P1", "4.1.0P3", "4.1.5P2",
        "4.2.1P8", "4.2.3P1", "5.0.1B2", "5.0.2P4", "5.1.0P1",
        "5.2.0B1", "5.2.5P3", "5.3.0B1", "5.3.2P2", "5.4.0P1",
        "5.4.3B2", "5.5.0P1", "5.5.2P3",
    ])


def EnC_PacKeT(HeX: str, K: bytes, V: bytes) -> str:
    """تشفير حزمة بـ AES-128-CBC وإرجاع hex."""
    return AES.new(K, AES.MODE_CBC, V).encrypt(
        pad(bytes.fromhex(HeX), 16)
    ).hex()


def DEc_PacKeT(HeX: str, K: bytes, V: bytes) -> str:
    """فك تشفير حزمة AES-128-CBC من hex."""
    return unpad(
        AES.new(K, AES.MODE_CBC, V).decrypt(bytes.fromhex(HeX)), 16
    ).hex()


def EnC_Vr(N: int) -> bytes:
    """ترميز varint (نسخة بديلة)."""
    out = []
    while True:
        b = N & 0x7F
        N >>= 7
        if N:
            b |= 0x80
        out.append(b)
        if not N:
            break
    return bytes(out)


def CrEaTe_VarianT(field_number: int, value: int) -> bytes:
    return EnC_Vr((field_number << 3) | 0) + EnC_Vr(value)


def CrEaTe_LenGTh(field_number: int, value) -> bytes:
    encoded = value.encode() if isinstance(value, str) else value
    return EnC_Vr((field_number << 3) | 2) + EnC_Vr(len(encoded)) + encoded


def CrEaTe_ProTo(fields: dict) -> bytes:
    """بناء protobuf متكرر (يدعم dict متداخلة و lists)."""
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


def DecodE_HeX(H: int) -> str:
    """تحويل رقم إلى hex بصيغة زوجية."""
    F = hex(H)[2:]
    return "0" + F if len(F) == 1 else F


def GeneRaTePk(Pk: str, N: str, K: bytes, V: bytes) -> bytes:
    """بناء الحزمة النهائية: header + length + payload مشفر."""
    PkEnc = EnC_PacKeT(Pk, K, V)
    length_hex = DecodE_HeX(len(PkEnc) // 2)

    padding = {
        2: "000000",
        3: "00000",
        4: "0000",
        5: "000",
    }.get(len(length_hex), "00000")

    return bytes.fromhex(N + padding + length_hex + PkEnc)


def DeCode_PackEt(input_text):
    """
    فك تشفير protobuf إلى JSON.
    يستخدم blackboxprotobuf إذا متوفر.
    """
    if not HAS_BLACKBOX:
        return None
    try:
        data = bytes.fromhex(input_text) if isinstance(input_text, str) else input_text
        message, _ = blackboxprotobuf.protobuf_to_json(data)
        return message
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
#  📦 PACKET BUILDERS
# ═══════════════════════════════════════════════════════════

def Join_Team(team_code: str, key: bytes, iv: bytes) -> bytes:
    """بناء حزمة دخول الفريق (JOIN)."""
    sub = {
        1: bytes.fromhex("01090a0b121619201d2729"),
        2: 40,
        3: bytes.fromhex("01090a0b121619201d2729"),
        4: "w\\Z]",
        6: 12,
        7: bytes.fromhex("01090a0b121619201d2729"),
        8: "1.132.9",
        9: 6,
        10: 2,
        11: bytes.fromhex("01090a0b121619201d2729"),
    }
    main = {
        1: 4,
        2: {
            4: bytes.fromhex("01090a0b121619201d2729"),
            5: str(team_code),
            6: 6,
            8: 1,
            9: sub,
            11: {1: "IDC1", 2: 99, 3: "ME"},
            13: "ar",
            16: bytes.fromhex("374f521955"),
            20: [
                {1: 3, 2: 360}, {1: 4, 2: 391}, {1: 5, 2: 156},
                {1: 29, 2: 204}, {1: 22, 2: 118}, {1: 14, 2: 139},
                {1: 21},
            ],
            27: {1: 2, 2: 4},
        },
    }
    return GeneRaTePk(CrEaTe_ProTo(main).hex(), "0519", key, iv)


def SendInv(bot_uid: int, uid: int, K: bytes, V: bytes) -> bytes:
    """حزمة دعوة لاعب للفريق."""
    fields = {
        1: 33,
        2: {
            1: int(uid), 2: "ME", 3: 1, 4: 1, 6: "yyt", 7: 330,
            8: 1000, 9: 100, 10: "DZ", 12: 1, 13: int(uid), 16: 1,
            17: {2: 159, 4: "y[WW", 6: 11, 8: "1.118.1", 9: 3, 10: 1},
            18: 306, 19: 18, 24: 902000306,
            26: {}, 27: {1: 11, 2: int(bot_uid), 3: 999}, 28: {},
            31: {1: 1, 2: 32768}, 32: 32768,
            34: {
                1: int(bot_uid), 2: 8,
                3: "\u0010\u0015\b\n\u000b\u0013\f\u000f\u0011\u0004"
                   "\u0007\u0002\u0003\r\u000e\u0012\u0001\u0005\u0006",
            },
        },
    }
    return GeneRaTePk(str(CrEaTe_ProTo(fields).hex()), "0519", K, V)


def Send_GhosTs(uid: int, name: str, sq: str, key: bytes, iv: bytes, lang: str = "en") -> bytes:
    """حزمة دخول شبح (Ghost)."""
    fields = {
        1: 61,
        2: {
            1: int(uid),
            2: {
                1: int(uid), 2: 1159, 3: name, 5: 12, 6: 9999,
                7: 1, 8: {2: 1, 3: 1}, 9: 3, 10: lang,
            },
            3: sq,
        },
    }
    return GeneRaTePk(str(CrEaTe_ProTo(fields).hex()), "0519", key, iv)


def ExiT(key: bytes, iv: bytes) -> bytes:
    """حزمة الخروج من الفريق."""
    fields = {1: 7, 2: {1: 0}}
    return GeneRaTePk(str(CrEaTe_ProTo(fields).hex()), "0519", key, iv)


# ═══════════════════════════════════════════════════════════
#  🔑 LOGIN FLOW
# ═══════════════════════════════════════════════════════════

def PyL(access_token: str, open_id: str) -> bytes:
    """بناء MajorLogin payload (بيانات الجهاز)."""
    P = {
        3: time.strftime("%Y-%m-%d %H:%M:%S"),
        4: "free fire",
        5: 1,
        7: "1.132.9",
        8: "Android OS 14 / API-34 (UP1A.231005.007/V816.0.15.0.UNQMIXM)",
        9: "Handheld",
        10: "Grameenphone",
        11: "CarrierDataNetwork",
        12: 1666, 13: 750, 14: "352",
        15: "ARM64 FP ASIMD AES | 2400 | 8",
        16: 5563, 17: "Mali-G57 MC2",
        18: "OpenGL ES 3.2 v1.r32p1-01eac0.0a0b917d9265b4c01be9925306306139",
        19: "Google|9cc73f7a-91f6-40f6-87ec-5b67e597eb8c",
        20: "59.152.5.188",
        21: "en", 22: open_id, 23: "8", 24: "Handheld",
        25: "Xiaomi 2312DRAABI", 26: "BD",
        29: access_token, 30: 1,
        41: "Grameenphone", 42: "Cellular",
        57: "7428b253defc164018c604a1ebbfebdf",
        60: 109685, 61: 58294, 62: 797, 63: 18000,
        64: 58818, 65: 109685, 66: 58818, 67: 109685,
        73: 2,
        74: "/data/app/~~cqQgpdMykLQEM3odipXatw==/"
            "com.dts.freefireth-G6e5yOt1dtuXG5Ambhj18g==/lib/arm64",
        76: 1,
        77: "b8e0cd5e295eee42f5860d3c86e483dd|/data/app/"
            "~~cqQgpdMykLQEM3odipXatw==/"
            "com.dts.freefireth-G6e5yOt1dtuXG5Ambhj18g==/base.apk",
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


def Strip_MajorLogin_Prefix(body: bytes) -> bytes:
    """إزالة بادئة 64 بايت من استجابة MajorLogin إذا وجدت."""
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


def GeT_AccEss(uid: str, password: str):
    """الخطوة 1: الحصول على access_token + open_id من Garena."""
    url = "https://100067.connect.garena.com/api/v2/oauth/guest/token:grant"
    headers = {
        "User-Agent": Ua(),
        "Content-Type": "application/json; charset=utf-8",
    }
    payload = {
        "client_id": 100067,
        "client_secret": (
            "2ee44819e9b4598845141067b281621874"
            "d0d5d7af9d8f7e00c1e54715b7d1e3"
        ),
        "client_type": 2,
        "device_id": "",
        "password": password,
        "response_type": "token",
        "uid": int(uid),
    }
    R = requests.post(url, headers=headers, json=payload, verify=False, timeout=15)
    print(f"[{uid}] GetAccess => {R.status_code}")

    if R.status_code not in (200, 201):
        return None
    try:
        J = R.json()
    except Exception:
        return None
    if J.get("code") != 0:
        return None

    d = J.get("data", {})
    return {
        "access_token": d.get("access_token"),
        "open_id": d.get("open_id"),
    }


def MajorLogin(Payload: bytes):
    """الخطوة 2: تسجيل الدخول الرئيسي."""
    url = "https://loginbp.ppmainecoonghj.com/MajorLogin"
    headers = {
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-GA-SV": str(int(time.time())),
        "Authorization": "Bearer ",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB55",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    R = requests.post(url, headers=headers, data=Payload, verify=False, timeout=15)
    print(f"MajorLogin => {R.status_code}")
    if R.status_code in (200, 201) and R.content:
        return R.content
    return None


def GeTLoginDaTa(client_url: str, payload: bytes, jwt: str):
    """الخطوة 3: جلب بيانات الاتصال (IP/Port)."""
    url = f"{client_url}/GetLoginData"
    headers = {
        "User-Agent": "UnityPlayer/2018.4.12f1 (UnityWebRequest/1.0, libcurl/8.5.0-DEV)",
        "Accept": "*/*",
        "Accept-Encoding": "deflate, gzip",
        "X-GA-SV": str(int(time.time())),
        "Authorization": f"Bearer {jwt}",
        "X-GA": "v1 1",
        "ReleaseVersion": "OB55",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-Unity-Version": "2018.4.12f1",
    }
    R = requests.post(url, headers=headers, data=payload, verify=False, timeout=15)
    print(f"GetLoginData => {R.status_code}")
    if R.status_code == 200 and R.content:
        return R.content
    return None


def _gv(fields: dict, n: int):
    """جلب قيمة من dict مع دعم list."""
    v = fields.get(n)
    if v is None:
        return None
    return v[0] if isinstance(v, list) else v


def ExtractMajorLogin(ml_resp: bytes):
    """استخراج JWT + Region + Keys من MajorLogin response."""
    body = Strip_MajorLogin_Prefix(ml_resp)
    f = Parse_ProToBuF(body)

    jwt_b = _gv(f, 8)
    url_b = _gv(f, 10)
    ts_v = _gv(f, 21)
    key_b = _gv(f, 22)
    iv_b = _gv(f, 23)
    acct_v = _gv(f, 1)

    jwt = (
        jwt_b.decode("utf-8", errors="ignore")
        if isinstance(jwt_b, (bytes, bytearray))
        else (jwt_b if isinstance(jwt_b, str) else None)
    )
    url = (
        url_b.decode("utf-8", errors="ignore")
        if isinstance(url_b, (bytes, bytearray))
        else (url_b if isinstance(url_b, str) else None)
    )
    ts = ts_v if isinstance(ts_v, int) else None
    acct = acct_v if isinstance(acct_v, int) else None

    if not jwt or not isinstance(key_b, (bytes, bytearray)) or not isinstance(iv_b, (bytes, bytearray)):
        print("[ML] حقول ناقصة")
        return None

    return {
        "jwt": jwt,
        "url": url,
        "ts": ts,
        "key": bytes(key_b),
        "iv": bytes(iv_b),
        "account_id": acct,
    }


def login_account(acc_uid: str, acc_pass: str):
    """تسجيل دخول كامل لحساب واحد."""
    td = GeT_AccEss(acc_uid, acc_pass)
    if not td:
        return None

    access_token = td["access_token"]
    open_id = td["open_id"]
    if not access_token or not open_id:
        return None

    login_payload = PyL(access_token, open_id)
    ml = MajorLogin(login_payload)
    if not ml:
        return None

    ad = ExtractMajorLogin(ml)
    if not ad:
        print(f"[{acc_uid}] MajorLogin فشل")
        return None

    jwt = ad["jwt"]
    ts = ad["ts"]
    key = ad["key"]
    iv = ad["iv"]
    url = ad["url"] or "https://clientbp.ppmainecoonghj.com"
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    account_id = ad["account_id"]
    print(f"[{acc_uid}] JWT len={len(jwt)} | ts={ts} | acct={account_id}")

    ld = GeTLoginDaTa(url, login_payload, jwt)
    if not ld:
        return None

    gl = Parse_ProToBuF(ld)

    def gv(n):
        v = gl.get(n)
        return v[0] if isinstance(v, list) else v

    def gs(n):
        v = gv(n)
        return v.decode() if isinstance(v, (bytes, bytearray)) else v

    def gi(n):
        v = gv(n)
        return int(v) if isinstance(v, int) else None

    player_name = gs(4) or ""
    func_addr = gs(14)
    info_addr = gs(32)

    if not func_addr or not info_addr:
        print(f"[{acc_uid}] IP:Port مفقود")
        return None

    ip, port = func_addr.split(":")
    ip2, port2 = info_addr.split(":")

    if not account_id:
        account_id = gi(1) or gi(5) or 0

    print(f"[{acc_uid}] ✅ متصل | {player_name} | UID: {account_id}")

    return {
        "uid": account_id,
        "jwt": jwt,
        "ts": ts,
        "key": key,
        "iv": iv,
        "ip": ip, "port": port,
        "ip2": ip2, "port2": port2,
        "name": player_name,
        "token": access_token,
    }


# ═══════════════════════════════════════════════════════════
#  🌐 TCP SESSION
# ═══════════════════════════════════════════════════════════

def BuildAuthToken(uid: int, jwt_str: str, ts: int,
                   key: bytes, iv: bytes, mode: str = "online") -> str:
    """بناء توكن المصادقة لاتصال TCP."""
    ah = f"{int(uid):x}"
    if len(ah) > 16:
        raise ValueError("UID hex طويل جداً")
    ah = ah.zfill(16)

    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(
        pad(jwt_str.encode(), 16)
    ).hex()

    th = f"{int(ts):x}"
    if len(th) % 2:
        th = "0" + th

    tsz = f"{len(enc) // 2:02x}"
    padding = "00000" if mode == "chat" else "0000000000000"

    return f"9015{ah}{th}{padding}{tsz}{enc}"


def _TuneSock(s: socket.socket):
    """تفعيل Keep-Alive على socket."""
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except Exception:
        pass


def _Session(host, port, uid, jwt, ts, key, iv,
             mode, tag, team_code, barrier, deadline):
    """جلسة TCP واحدة: JOIN → INV → GHOST → EXIT."""
    s = None
    result = {"tag": tag, "uid": uid, "status": "started",
              "sent": 0, "error": None}

    try:
        # --- الاتصال ---
        s = socket.create_connection((host, int(port)), timeout=15)
        s.settimeout(20)
        _TuneSock(s)
        s.sendall(bytes.fromhex(BuildAuthToken(uid, jwt, ts, key, iv, mode=mode)))
        print(f"[{tag}-{uid}] متصل، انتظار barrier (JOIN)")

        # --- Barrier 1 ---
        try:
            barrier.wait(timeout=max(1, deadline - time.time()))
        except Exception:
            pass
        if time.time() > deadline:
            result["status"] = "timeout_before_join"
            return result

        # --- JOIN ---
        s.sendall(Join_Team(team_code, key, iv))
        result["sent"] += 1
        print(f"[{tag}-{uid}] JOIN أُرسل")

        # --- قراءة بيانات الفريق ---
        s.settimeout(1.0)
        target_uid = None
        squad_code = None
        start = time.time()

        while time.time() - start < 15 and time.time() < deadline:
            try:
                data = s.recv(65536)
                if not data:
                    break
                hex_data = data.hex()

                if hex_data.startswith("0500") and 100 < len(hex_data) < 5000:
                    try:
                        js = DeCode_PackEt(hex_data[10:])
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
                                target_uid = t_uid
                                squad_code = sq
                                print(f"[{tag}-{uid}] 🎯 target={target_uid}")
                                break
                    except Exception:
                        pass
            except socket.timeout:
                pass
            except Exception:
                break

        if not target_uid or not squad_code:
            result["status"] = "no_team_data"
            return result

        # --- إعادة الاتصال ---
        try:
            s.close()
        except Exception:
            pass
        if time.time() > deadline:
            result["status"] = "timeout_before_reconnect"
            return result

        s = socket.create_connection((host, int(port)), timeout=15)
        s.settimeout(20)
        _TuneSock(s)
        s.sendall(bytes.fromhex(BuildAuthToken(uid, jwt, ts, key, iv, mode=mode)))
        time.sleep(0.3)

        # --- INVITE ---
        s.sendall(SendInv(uid, target_uid, key, iv))
        result["sent"] += 1

        for _ in range(3):
            s.sendall(Join_Team(team_code, key, iv))
            time.sleep(0.02)

        # --- Barrier 2 ---
        print(f"[{tag}-{uid}] انتظار barrier (GHOST)")
        try:
            barrier.wait(timeout=max(1, deadline - time.time()))
        except Exception:
            pass
        if time.time() > deadline:
            result["status"] = "timeout_before_ghost"
            return result

        # --- GHOST ---
        ghost_pkt = Send_GhosTs(int(target_uid), "[C][B][FF00FF]YAKOUB XV",
                                squad_code, key, iv)
        for _ in range(3):
            try:
                s.sendall(ghost_pkt)
                result["sent"] += 1
            except Exception:
                break
            time.sleep(0.01)
        print(f"[{tag}-{uid}] GHOST أُرسل ×3")

        # --- Barrier 3 ---
        try:
            barrier.wait(timeout=max(1, deadline - time.time()))
        except Exception:
            pass

        # --- EXIT ---
        if time.time() < deadline:
            try:
                s.sendall(ExiT(key, iv))
                result["sent"] += 1
                print(f"[{tag}-{uid}] EXIT أُرسل")
            except Exception:
                pass

        result["status"] = "success"
        return result

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        print(f"[{tag}-{uid}] خطأ: {e}")
        return result
    finally:
        try:
            if s:
                s.close()
        except Exception:
            pass


def run_one_account(session_data: dict, team_code: str,
                    barrier: threading.Barrier, deadline: float):
    """تشغيل اتصالين (ChaT + OnLinE) لحساب واحد."""
    uid = session_data["uid"]
    jwt = session_data["jwt"]
    ts = session_data["ts"]
    key = session_data["key"]
    iv = session_data["iv"]
    results = []

    t1 = threading.Thread(
        target=lambda: results.append(
            _Session(session_data["ip"], session_data["port"], uid,
                     jwt, ts, key, iv, "online", "ChaT",
                     team_code, barrier, deadline)
        ),
        daemon=True,
    )
    t2 = threading.Thread(
        target=lambda: results.append(
            _Session(session_data["ip2"], session_data["port2"], uid,
                     jwt, ts, key, iv, "chat", "OnLinE",
                     team_code, barrier, deadline)
        ),
        daemon=True,
    )

    t1.start()
    t2.start()

    remaining = max(1, deadline - time.time())
    t1.join(timeout=remaining)
    t2.join(timeout=remaining)

    return results


# ═══════════════════════════════════════════════════════════
#  🚀 FASTAPI APP
# ═══════════════════════════════════════════════════════════

app = FastAPI(
    title="FF Ghost Bot API",
    version="1.0.0",
    description="بوت فري فاير — يشتغل على Vercel",
)


@app.get("/")
def root():
    """حالة الخدمة."""
    return {
        "status": "ok",
        "service": "ff-ghost-bot",
        "accounts_configured": len(ACCOUNTS),
        "max_session_seconds": MAX_SESSION_SECONDS,
        "python_version": "3.12",
        "endpoints": [
            "GET /login              → تسجيل دخول الحسابات",
            "GET /start?team=<code>  → تشغيل التسلسل الكامل",
        ],
    }


@app.get("/login")
def login_only():
    """تسجيل دخول كل الحسابات — بدون TCP."""
    with ThreadPoolExecutor(max_workers=len(ACCOUNTS)) as pool:
        futures = [pool.submit(login_account, uid, pw) for uid, pw in ACCOUNTS]
        results = []
        for f in futures:
            try:
                r = f.result(timeout=20)
            except Exception:
                r = None
            results.append({
                "ok": r is not None,
                "uid": r["uid"] if r else None,
                "name": r["name"] if r else None,
            })

    ok_count = sum(1 for r in results if r["ok"])
    return {
        "total": len(ACCOUNTS),
        "ok": ok_count,
        "failed": len(ACCOUNTS) - ok_count,
        "results": results,
    }


@app.get("/start")
def start_bot(team: str = Query(..., min_length=1, max_length=12)):
    """تشغيل التسلسل الكامل لحساب واحد أو أكثر."""
    if not team.strip():
        raise HTTPException(400, "كود الفريق مطلوب")

    start_time = time.time()
    deadline = start_time + MAX_SESSION_SECONDS
    print(f"\n=== /start team={team} ===")

    # --- تسجيل دخول كل الحسابات ---
    sessions = []
    login_errors = []

    with ThreadPoolExecutor(max_workers=len(ACCOUNTS)) as pool:
        futures = {uid: pool.submit(login_account, uid, pw)
                   for uid, pw in ACCOUNTS}

        for uid, f in futures.items():
            try:
                r = f.result(timeout=25)
            except Exception as e:
                r = None
                login_errors.append({"uid": uid, "error": str(e)})

            if r:
                sessions.append(r)
            else:
                login_errors.append({"uid": uid, "error": "login failed"})

    if not sessions:
        return JSONResponse(
            status_code=502,
            content={
                "status": "failed",
                "reason": "لا يوجد حساب مسجل",
                "errors": login_errors,
                "elapsed": round(time.time() - start_time, 2),
            },
        )

    print(f"=== {len(sessions)} حساب جاهز ===")

    # --- Barrier + تشغيل ---
    barrier = threading.Barrier(len(sessions))
    results = []
    threads = []

    for s in sessions:
        t = threading.Thread(
            target=lambda sdata=s: results.extend(
                run_one_account(sdata, team, barrier, deadline)
            ),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=max(0.1, deadline - time.time()))

    # --- تجميع النتائج ---
    by_account = {}
    for r in results:
        uid = str(r.get("uid"))
        entry = by_account.setdefault(uid, {
            "uid": uid,
            "chat": None,
            "online": None,
            "total_sent": 0,
            "errors": [],
        })
        if r["tag"] == "ChaT":
            entry["chat"] = r["status"]
        else:
            entry["online"] = r["status"]
        entry["total_sent"] += r.get("sent", 0)
        if r.get("error"):
            entry["errors"].append(f"{r['tag']}: {r['error']}")

    return {
        "status": "completed",
        "team": team,
        "elapsed": round(time.time() - start_time, 2),
        "accounts_logged": len(sessions),
        "accounts_ran": len(by_account),
        "login_errors": login_errors,
        "results": list(by_account.values()),
    }
