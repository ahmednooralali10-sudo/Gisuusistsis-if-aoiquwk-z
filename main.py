"""
FF Ghost Bot API — نسخة داشبورد
================================
Dashboard + API لبوت فري فاير — Vercel-ready.

Endpoints:
    GET  /                       → داشبورد
    GET  /start?team=<code>      → تشغيل التسلسل (HTML)
    GET  /start?team=<code>&format=json  → JSON خام
    GET  /login?format=json      → فحص تسجيل الدخول
    GET  /accounts               → عرض الحسابات
    POST /add                    → إضافة حسابات
    GET  /api/status             → JSON للإحصائيات
"""
import json
import os
import random
import socket
import threading
import time
import urllib3

import requests
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from concurrent.futures import ThreadPoolExecutor

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

MAX_SESSION_SECONDS = 50
MAX_ACCOUNTS = 500

# ─── الحسابات (pw:uid) ───
_DEFAULT_ACCOUNTS_RAW = """
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
S7LYQLRHGKY8-S1X_TEAM:4555625950
S7LEQABTL51X-S1X_TEAM:4555626124
S7LCHCUI22IQ-S1X_TEAM:4555626284
S7LGUYGC5Z5H-S1X_TEAM:4555626414
S7LG79GTDB4A-S1X_TEAM:4555626580
S7LR8I2JSA3B-S1X_TEAM:4555626858
S7LSOD3DWSDH-S1X_TEAM:4555626925
S7L2R4WFRI5K-S1X_TEAM:4555626978
S7LGIIOKVQXD-S1X_TEAM:4555629318
S7LROQKCQWWW-S1X_TEAM:4555629643
S7LT5555B7VZ-S1X_TEAM:4555629698
S7L432EGSDTQ-S1X_TEAM:4555629769
S7L8VMQJFCAY-S1X_TEAM:4555629853
S7LRNC59NLFO-S1X_TEAM:4555630041
S7LDO092IQHZ-S1X_TEAM:4555630092
S7LIBUAQMKIF-S1X_TEAM:4555630883
S7LS6V9T1BOP-S1X_TEAM:4555631918
S7LKFJ8EWQTE-S1X_TEAM:4555632289
S7LRPTVFY61P-S1X_TEAM:4555632916
S7LWOJ68GAHY-S1X_TEAM:4555633110
S7LBPLQSWOIE-S1X_TEAM:4555633862
S7LDKJEZ6I12-S1X_TEAM:4555719862
S7LLLYSK70YR-S1X_TEAM:4555720054
S7LBW8CPZYGK-S1X_TEAM:4555720196
S7LXBIREJV4Z-S1X_TEAM:4555720320
S7LSBIQKNRWB-S1X_TEAM:4555720526
S7LXN1W9JZYC-S1X_TEAM:4555720745
S7L4TR5HF11C-S1X_TEAM:4555720853
S7LPAHS9NU82-S1X_TEAM:4556615537
S7LVFV4GPKRB-S1X_TEAM:4556615620
S7LHXQXDKFMG-S1X_TEAM:4556615700
S7LRB1WFIPQC-S1X_TEAM:4556615992
S7LJFPJVDZHZ-S1X_TEAM:4556616059
S7LRTTSMMWJA-S1X_TEAM:4556616132
S7LYKHVUMTBG-S1X_TEAM:4556616203
S7L5ECXOVAVD-S1X_TEAM:4556616278
S7LUHFJEQXAK-S1X_TEAM:4556616363
S7LIASVXGD6V-S1X_TEAM:4556616453
S7LJ8Y0A026N-S1X_TEAM:4556616638
S7LU478JQBY3-S1X_TEAM:4556616730
S7LUQCTE5EGO-S1X_TEAM:4556616834
S7LENS9OZTMY-S1X_TEAM:4556616957
S7LLFQRRJVXC-S1X_TEAM:4556617098
S7LF936MSJXR-S1X_TEAM:4556617214
S7LGGVVKN7KJ-S1X_TEAM:4556617302
S7LVXYZP4KKK-S1X_TEAM:4556617415
S7LOOJ2OSS0N-S1X_TEAM:4556617491
S7LFEPHKOOD5-S1X_TEAM:4556617569
S7LLI53DJS4H-S1X_TEAM:4556617663
S7LWHKTK4AT4-S1X_TEAM:4556617747
S7L0BQW2SU0X-S1X_TEAM:4556617848
S7L53PSOYW1S-S1X_TEAM:4556617917
S7LXNL4QNUNH-S1X_TEAM:4556617982
S7LTY54YUAZ2-S1X_TEAM:4556618108
S7LO0TWRMC0B-S1X_TEAM:4556618270
S7L1AT8VV05L-S1X_TEAM:4556618530
S7LKGDYQQCNY-S1X_TEAM:4556618619
S7LS67JTBCEG-S1X_TEAM:4556618696
S7L3LCD0JRLO-S1X_TEAM:4556618793
S7LDD1LYABUS-S1X_TEAM:4556618873
S7L1THS8JL0A-S1X_TEAM:4556619046
S7LD5EXTUVEB-S1X_TEAM:4556619227
S7LJOK6FG2G4-S1X_TEAM:4556619521
S7L4IPW7VPIK-S1X_TEAM:4556619713
S7LNUQTQIHXB-S1X_TEAM:4556619886
S7LDEC8IZ2ZN-S1X_TEAM:4556620078
S7LU4ANGICCC-S1X_TEAM:4556620242
S7LJXJHO7GAL-S1X_TEAM:4556620339
S7LZWJHDP87N-S1X_TEAM:4556620465
S7LVE0SNULN7-S1X_TEAM:4556620628
S7LMYZX5T8PN-S1X_TEAM:4556620827
S7LSTGT0W2FC-S1X_TEAM:4556620938
S7LER1NO1DZV-S1X_TEAM:4556621023
S7LDEVR90TK0-S1X_TEAM:4556621217
S7LG16WVVPEX-S1X_TEAM:4556621305
S7L2LLJ7CDXN-S1X_TEAM:4556621393
S7LBZVOMQGLD-S1X_TEAM:4556621575
S7LVDMQ0W4XT-S1X_TEAM:4556621858
S7LSA7RCOQWX-S1X_TEAM:4556622080
S7LMJVS3RPX4-S1X_TEAM:4556622274
S7LDFONYFONV-S1X_TEAM:4556622373
S7LPEWRHCHID-S1X_TEAM:4556622464
S7LDSTSZIZB5-S1X_TEAM:4556622534
S7LERBB1QC5T-S1X_TEAM:4556622607
S7LFLVZPYEQX-S1X_TEAM:4556622688
S7LYEB7QD2GO-S1X_TEAM:4556622781
S7LKQRN2ASL4-S1X_TEAM:4556623075
S7LREQHLGKZN-S1X_TEAM:4556623267
S7LJOTP8NIZE-S1X_TEAM:4556623375
S7LBNZEXOL9L-S1X_TEAM:4556623467
S7LJCVP53Y8C-S1X_TEAM:4556623543
S7LM7ZFSFWCZ-S1X_TEAM:4556623639
S7LJOHHYPRIR-S1X_TEAM:4556623766
S7LQH3OEUPI7-S1X_TEAM:4556623883
S7LUVHAWLI7L-S1X_TEAM:4556623992
S7LNEY4SHV5K-S1X_TEAM:4556624135
S7LDAFUL4AXK-S1X_TEAM:4556624258
S7L9OR6KCB8G-S1X_TEAM:4556624361
S7LPU0LPV3LN-S1X_TEAM:4556624483
S7LD6YX3ZGQN-S1X_TEAM:4556624586
S7LB8UNTTEDQ-S1X_TEAM:4556624695
S7L0CUUX310F-S1X_TEAM:4556624760
S7LDHUW3FEIZ-S1X_TEAM:4556624854
S7LPRSIK5SNW-S1X_TEAM:4556624928
S7LP6DISUSET-S1X_TEAM:4556625007
S7LFERTAKWWC-S1X_TEAM:4556625120
S7LF6PG8Q3OL-S1X_TEAM:4556625278
S7LSZO5WOFEI-S1X_TEAM:4556625414
S7LIZL4WS0G5-S1X_TEAM:4556625511
S7L3TYQ00EYL-S1X_TEAM:4556625607
S7LFCQY6WN1H-S1X_TEAM:4556625685
S7LL51LU2MEG-S1X_TEAM:4556625781
S7LS5GCNZC9L-S1X_TEAM:4556625895
S7LEFGEFO4NF-S1X_TEAM:4556625979
S7L2GDZSOBDE-S1X_TEAM:4556626058
S7LRLU7QFRUR-S1X_TEAM:4556626144
S7LO2C3FZMYK-S1X_TEAM:4556626243
S7LSR5DAVVHE-S1X_TEAM:4556626368
S7LCOBPUKZWZ-S1X_TEAM:4556626471
S7LJAKS7YQUV-S1X_TEAM:4556626630
S7LCFSKN3DMJ-S1X_TEAM:4556626750
S7LX7S8FD44K-S1X_TEAM:4556626871
S7LIPJ5KBKRC-S1X_TEAM:4556626959
S7L9RZYLFZHE-S1X_TEAM:4556627058
S7LTCZK6RWCW-S1X_TEAM:4556627131
S7LSHZT3Y4A1-S1X_TEAM:4556627218
S7LR4ORUMAI5-S1X_TEAM:4556627294
S7LEJ1RI0NA6-S1X_TEAM:4556627408
S7LNS768PLPJ-S1X_TEAM:4556627552
S7LWVWB7KD0N-S1X_TEAM:4556627681
S7LVMQVQO77L-S1X_TEAM:4556627775
S7LBAONCOOUN-S1X_TEAM:4556627859
S7LMHYNJJESF-S1X_TEAM:4556628115
S7LNQCP4T8E6-S1X_TEAM:4556629935
S7LUN3WUDSNH-S1X_TEAM:4556630056
S7LIW7XKPPC1-S1X_TEAM:4556630344
S7LXXC0AEGLF-S1X_TEAM:4556630552
S7LG4YD0CTH0-S1X_TEAM:4556630642
S7LAQI5BWJN8-S1X_TEAM:4556630751
S7L7R9RKBQKY-S1X_TEAM:4556630844
S7LQNW5IJ6WP-S1X_TEAM:4556630935
S7LTKC2SZPX4-S1X_TEAM:4556631061
S7LZD5OF0GZM-S1X_TEAM:4556631177
S7LINI1E6BGE-S1X_TEAM:4556631357
S7LUSZRCFQPS-S1X_TEAM:4556631445
S7LJ9AJESU3Z-S1X_TEAM:4556631557
S7L3VKF58LGG-S1X_TEAM:4556631634
S7L9BAOHBZS0-S1X_TEAM:4556631732
S7L6FUGTKIIG-S1X_TEAM:4556631828
S7LMTVPGHZLG-S1X_TEAM:4556631930
S7LREHLT9FCE-S1X_TEAM:4556632043
S7LL3GHWEUIK-S1X_TEAM:4556632122
S7LREDRZDSAJ-S1X_TEAM:4556632232
S7L3RGLZHLDO-S1X_TEAM:4556632317
S7L0SNBBG84I-S1X_TEAM:4556632507
S7LWZE2PEL3W-S1X_TEAM:4556632761
S7LFETLQ71U9-S1X_TEAM:4556632862
S7LXEYIXW2CG-S1X_TEAM:4556632965
S7L1BHKOPC1M-S1X_TEAM:4556633045
S7LYPO4SPLFK-S1X_TEAM:4556633123
S7L1RTSWA5YE-S1X_TEAM:4556633220
S7LWCRAMH25Y-S1X_TEAM:4556633352
S7LQHZ6MEWCD-S1X_TEAM:4556633483
S7LKIFDAUBC6-S1X_TEAM:4556633607
S7L7XW2QLWWX-S1X_TEAM:4556633791
S7LHL6J5TBCS-S1X_TEAM:4556633932
S7LMKR47ZXFQ-S1X_TEAM:4556634035
S7LWTF3HPMXQ-S1X_TEAM:4556634146
S7LCUTKTMTNR-S1X_TEAM:4556634256
S7LAHZVO6V7D-S1X_TEAM:4556634373
S7LZURLPY57Z-S1X_TEAM:4556634436
S7L8EBPMY8CZ-S1X_TEAM:4556634509
S7LTNBCLUL2S-S1X_TEAM:4556634606
S7LV3NGR304T-S1X_TEAM:4556634711
S7LTJSAZELZZ-S1X_TEAM:4556634808
S7LEERBCZS5L-S1X_TEAM:4556634926
S7L0SMKNBL5F-S1X_TEAM:4556635032
S7LD5POOHCTJ-S1X_TEAM:4556635118
S7LPTEZ2R8XM-S1X_TEAM:4556635207
S7LBY7EJQVPU-S1X_TEAM:4556635278
S7LSYB3IYDIG-S1X_TEAM:4556635388
S7LXTKINM26Z-S1X_TEAM:4556635461
S7L1GQG7J96P-S1X_TEAM:4556635535
S7LCC5FZE6ZK-S1X_TEAM:4556635646
S7LITKQF7WPX-S1X_TEAM:4556635723
S7L6OGSBMCYX-S1X_TEAM:4556635803
S7L2KJ92LH15-S1X_TEAM:4556635885
S7L2N6KEYQAP-S1X_TEAM:4556636048
S7LB11QEQIGO-S1X_TEAM:4556636147
S7LGQZOKDZJB-S1X_TEAM:4556636234
S7LQJU9IJ8HA-S1X_TEAM:4556636354
S7LO7CSXSRQQ-S1X_TEAM:4556636423
S7LJAYJJMHUL-S1X_TEAM:4556636520
S7LUTYPMGATS-S1X_TEAM:4556636589
S7L0SN2UZDCD-S1X_TEAM:4556636710
S7LZKQHBMXM1-S1X_TEAM:4556636787
S7LCEGV86NXS-S1X_TEAM:4556636888
S7LUK7XND75L-S1X_TEAM:4556636957
S7LLSFQXJP9F-S1X_TEAM:4556637056
S7L4D2WYOPBQ-S1X_TEAM:4556637178
S7L4KZY1RM8P-S1X_TEAM:4556637277
S7LPYJMWMNBN-S1X_TEAM:4556637515
S7LXIU9HPN9B-S1X_TEAM:4556637621
S7LLA4OL2GAO-S1X_TEAM:4556637694
S7LTHMA0WTNW-S1X_TEAM:4556637763
S7LM2EFL0PN6-S1X_TEAM:4556637873
S7LYOF1QHZGY-S1X_TEAM:4556637963
S7LF10DITOXW-S1X_TEAM:4556638060
S7L0J5WGMGZV-S1X_TEAM:4556638139
S7LXQTVUA7S9-S1X_TEAM:4556638238
S7LSWEHOLSNQ-S1X_TEAM:4556638302
S7LCFYLEJKGD-S1X_TEAM:4556638471
S7LEUCQ9RKVY-S1X_TEAM:4556638571
S7LEOC9SP8SH-S1X_TEAM:4556638671
S7LCPEX6VO9I-S1X_TEAM:4556638777
S7LQY3P9CYMB-S1X_TEAM:4556638861
S7LPW84CFCBT-S1X_TEAM:4556638973
S7LVEZHYPSVZ-S1X_TEAM:4556639065
S7LWDPZAQTSZ-S1X_TEAM:4556639271
S7LVGCA4L2BK-S1X_TEAM:4556639481
S7LJPVKNECHY-S1X_TEAM:4556639704
S7LYNR7AATEQ-S1X_TEAM:4556639918
S7LQKNTKUK0L-S1X_TEAM:4556640098
S7L0GUVJQBKU-S1X_TEAM:4556640187
S7LHUFHJF1BC-S1X_TEAM:4556640403
S7LDVL1NGZXM-S1X_TEAM:4556640669
S7LBPAHCIXZN-S1X_TEAM:4556640763
S7LTOKDK599W-S1X_TEAM:4556641419
S7L5Q983BHEA-S1X_TEAM:4556641623
S7LKEADH1VRY-S1X_TEAM:4556641741
S7LLT8Z6B9AM-S1X_TEAM:4556641937
S7LKSALT7ZOP-S1X_TEAM:4556642016
S7LPCOATMAK4-S1X_TEAM:4556642210
"""


def _parse_accounts(raw):
    if not raw or not raw.strip():
        return []
    parts = []
    for chunk in raw.replace(";", "\n").replace(",", "\n").splitlines():
        chunk = chunk.strip()
        if not chunk or chunk.startswith("#") or ":" not in chunk:
            continue
        pw, uid = chunk.split(":", 1)
        pw, uid = pw.strip(), uid.strip()
        if pw and uid:
            parts.append((uid, pw))
    return parts[:MAX_ACCOUNTS]


_ACCOUNTS = _parse_accounts(
    os.environ.get("FF_ACCOUNTS", "") or _DEFAULT_ACCOUNTS_RAW
)
_ACCOUNTS_LOCK = threading.Lock()


def get_accounts():
    with _ACCOUNTS_LOCK:
        return list(_ACCOUNTS)


def set_accounts(new_list):
    global _ACCOUNTS
    with _ACCOUNTS_LOCK:
        _ACCOUNTS = new_list[:MAX_ACCOUNTS]


def add_accounts(raw):
    with _ACCOUNTS_LOCK:
        existing = {(u, p) for u, p in _ACCOUNTS}
        added = 0
        for u, p in _parse_accounts(raw):
            if (u, p) not in existing and len(_ACCOUNTS) < MAX_ACCOUNTS:
                _ACCOUNTS.append((u, p))
                existing.add((u, p))
                added += 1
        return added


# ═══════════════════════════════════════════════════════════
#  🔐  CRYPTO / PROTOBUF
# ═══════════════════════════════════════════════════════════

def EnV_VaRiAnT(n):
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


def ProToBuF(fields):
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


def Read_VaRiAnT(data, pos):
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


def Parse_ProToBuF(data):
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


def Ua():
    return random.choice([
        "4.0.18P6", "4.0.19P7", "4.0.20P1", "4.1.0P3", "4.1.5P2",
        "4.2.1P8", "4.2.3P1", "5.0.1B2", "5.0.2P4", "5.1.0P1",
        "5.2.0B1", "5.2.5P3", "5.3.0B1", "5.3.2P2", "5.4.0P1",
        "5.4.3B2", "5.5.0P1", "5.5.2P3",
    ])


def EnC_PacKeT(HeX, K, V):
    return AES.new(K, AES.MODE_CBC, V).encrypt(
        pad(bytes.fromhex(HeX), 16)
    ).hex()


def DEc_PacKeT(HeX, K, V):
    return unpad(
        AES.new(K, AES.MODE_CBC, V).decrypt(bytes.fromhex(HeX)), 16
    ).hex()


def EnC_Vr(N):
    H = []
    while True:
        b = N & 0x7F
        N >>= 7
        if N:
            b |= 0x80
        H.append(b)
        if not N:
            break
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
        len(length_hex), "00000"
    )
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
        1: bytes.fromhex("01090a0b121619201d2729"),
        2: 40,
        3: bytes.fromhex("01090a0b121619201d2729"),
        4: "w\\Z]", 6: 12,
        7: bytes.fromhex("01090a0b121619201d2729"),
        8: "1.132.9", 9: 6, 10: 2,
        11: bytes.fromhex("01090a0b121619201d2729"),
    }
    main = {
        1: 4,
        2: {
            4: bytes.fromhex("01090a0b121619201d2729"),
            5: str(team_code),
            6: 6, 8: 1, 9: sub,
            11: {1: "IDC1", 2: 99, 3: "ME"},
            13: "ar",
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


def Send_GhosTs(uid, name, sq, key, iv, lang="en"):
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
    headers = {"User-Agent": Ua(), "Content-Type": "application/json; charset=utf-8"}
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
                          verify=False, timeout=15)
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
    return {"access_token": d.get("access_token"), "open_id": d.get("open_id")}


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
                          verify=False, timeout=15)
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
                          verify=False, timeout=15)
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
    ah = f"{int(uid):x}"
    if len(ah) > 16:
        raise ValueError("uid hex too long")
    ah = ah.zfill(16)
    enc = AES.new(key, AES.MODE_CBC, iv).encrypt(
        pad(jwt_str.encode(), 16)
    ).hex()
    th = f"{int(ts):x}"
    if len(th) % 2:
        th = "0" + th
    tsz = f"{len(enc) // 2:02x}"
    pad_ = "00000" if mode == "chat" else "0000000000000"
    return f"9015{ah}{th}{pad_}{tsz}{enc}"


def _TuneSock(s):
    s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    try:
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
        s.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
    except Exception:
        pass


def _Session(host, port, uid, jwt, ts, key, iv, mode, tag,
             team_code, barrier, deadline):
    s = None
    result = {"tag": tag, "uid": uid, "status": "started",
              "sent": 0, "error": None}
    try:
        s = socket.create_connection((host, int(port)), timeout=15)
        s.settimeout(20)
        _TuneSock(s)
        s.sendall(bytes.fromhex(BuildAuthToken(uid, jwt, ts, key, iv, mode=mode)))

        try:
            barrier.wait(timeout=max(1, deadline - time.time()))
        except Exception:
            pass
        if time.time() > deadline:
            result["status"] = "timeout_before_join"
            return result

        s.sendall(Join_Team(team_code, key, iv))
        result["sent"] += 1

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

        s.sendall(SendInv(uid, target_uid, key, iv))
        result["sent"] += 1
        for _ in range(3):
            s.sendall(Join_Team(team_code, key, iv))
            time.sleep(0.02)

        try:
            barrier.wait(timeout=max(1, deadline - time.time()))
        except Exception:
            pass
        if time.time() > deadline:
            result["status"] = "timeout_before_ghost"
            return result

        ghost_pkt = Send_GhosTs(int(target_uid), "[C][B][FF00FF]YAKOUB XV",
                                squad_code, key, iv)
        for _ in range(3):
            try:
                s.sendall(ghost_pkt)
                result["sent"] += 1
            except Exception:
                break
            time.sleep(0.01)

        try:
            barrier.wait(timeout=max(1, deadline - time.time()))
        except Exception:
            pass
        if time.time() < deadline:
            try:
                s.sendall(ExiT(key, iv))
                result["sent"] += 1
            except Exception:
                pass

        result["status"] = "success"
        return result
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        return result
    finally:
        try:
            if s:
                s.close()
        except Exception:
            pass


def run_one_account(session_data, team_code, barrier, deadline):
    uid = session_data["uid"]
    jwt = session_data["jwt"]; ts = session_data["ts"]
    key = session_data["key"]; iv = session_data["iv"]
    results = []

    t1 = threading.Thread(
        target=lambda: results.append(
            _Session(session_data["ip"], session_data["port"], uid,
                     jwt, ts, key, iv, "online", "ChaT",
                     team_code, barrier, deadline)),
        daemon=True,
    )
    t2 = threading.Thread(
        target=lambda: results.append(
            _Session(session_data["ip2"], session_data["port2"], uid,
                     jwt, ts, key, iv, "chat", "OnLinE",
                     team_code, barrier, deadline)),
        daemon=True,
    )
    t1.start(); t2.start()
    remaining = max(1, deadline - time.time())
    t1.join(timeout=remaining)
    t2.join(timeout=remaining)
    return results


# ═══════════════════════════════════════════════════════════
#  🎨  HTML
# ═══════════════════════════════════════════════════════════

BASE_CSS = """
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0a0a0f;--card:#14141c;--card-2:#1a1a24;--border:#2a2a3a;
--text:#e8e8f0;--muted:#7a7a8c;--accent:#ff2d6c;--accent-2:#00e5ff;
--success:#00ff88;--warn:#ffb800;--error:#ff4444}
html,body{background:var(--bg);color:var(--text);
font-family:'JetBrains Mono','Cairo',system-ui,monospace;min-height:100vh;line-height:1.6}
body::before{content:'';position:fixed;inset:0;
background:radial-gradient(circle at 20% 10%,rgba(255,45,108,.08),transparent 40%),
radial-gradient(circle at 80% 90%,rgba(0,229,255,.08),transparent 40%);
pointer-events:none;z-index:-1}
a{color:var(--accent-2);text-decoration:none}
.container{max-width:1100px;margin:0 auto;padding:28px 20px 60px}
header.top{display:flex;align-items:center;justify-content:space-between;
padding-bottom:20px;border-bottom:1px solid var(--border);margin-bottom:28px;
flex-wrap:wrap;gap:12px}
.logo{font-size:22px;font-weight:800;letter-spacing:1px;
background:linear-gradient(90deg,var(--accent),var(--accent-2));
-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}
.logo::before{content:'◢ ';-webkit-text-fill-color:var(--accent)}
.logo::after{content:' ◣';-webkit-text-fill-color:var(--accent-2)}
.status-pill{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;
border-radius:999px;background:var(--card-2);border:1px solid var(--border);font-size:13px}
.dot{width:8px;height:8px;border-radius:50%;background:var(--success);
box-shadow:0 0 10px var(--success);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
gap:16px;margin-bottom:28px}
.stat{background:var(--card);border:1px solid var(--border);border-radius:14px;
padding:18px;position:relative;overflow:hidden}
.stat::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;
background:linear-gradient(90deg,var(--accent),var(--accent-2))}
.stat .label{font-size:12px;color:var(--muted);text-transform:uppercase;
letter-spacing:1px;margin-bottom:8px}
.stat .value{font-size:26px;font-weight:800}
.stat .value.accent{color:var(--accent)}
.stat .value.accent2{color:var(--accent-2)}
.stat .value.success{color:var(--success)}
.card{background:var(--card);border:1px solid var(--border);border-radius:16px;
padding:22px;margin-bottom:20px}
.card h2{font-size:16px;font-weight:700;margin-bottom:16px;
display:flex;align-items:center;gap:10px}
.card h2::before{content:'';width:4px;height:18px;
background:linear-gradient(180deg,var(--accent),var(--accent-2));border-radius:2px}
.input-row{display:flex;gap:10px;flex-wrap:wrap}
input[type=text],textarea{flex:1;background:var(--card-2);
border:1px solid var(--border);border-radius:10px;padding:13px 16px;
color:var(--text);font-family:inherit;font-size:14px;outline:none;
transition:border-color .15s,box-shadow .15s;min-width:200px}
input[type=text]:focus,textarea:focus{border-color:var(--accent);
box-shadow:0 0 0 3px rgba(255,45,108,.15)}
textarea{resize:vertical;min-height:130px;font-size:13px}
button{background:linear-gradient(135deg,var(--accent),#ff4d88);color:#fff;
border:none;padding:13px 26px;border-radius:10px;font-weight:700;
font-family:inherit;font-size:14px;cursor:pointer;letter-spacing:.5px;
transition:transform .1s,box-shadow .15s;box-shadow:0 0 20px rgba(255,45,108,.35)}
button:hover{transform:translateY(-1px)}
button.ghost{background:transparent;color:var(--accent-2);
border:1px solid var(--accent-2);box-shadow:none}
.badge{display:inline-block;padding:4px 12px;border-radius:6px;font-size:12px;
font-weight:700;letter-spacing:.5px;text-transform:uppercase}
.badge.success{background:rgba(0,255,136,.12);color:var(--success);
border:1px solid rgba(0,255,136,.3)}
.badge.error{background:rgba(255,68,68,.12);color:var(--error);
border:1px solid rgba(255,68,68,.3)}
.badge.warn{background:rgba(255,184,0,.12);color:var(--warn);
border:1px solid rgba(255,184,0,.3)}
.badge.info{background:rgba(0,229,255,.12);color:var(--accent-2);
border:1px solid rgba(0,229,255,.3)}
.table{width:100%;border-collapse:collapse;font-size:13px}
.table th,.table td{text-align:left;padding:10px 12px;
border-bottom:1px solid var(--border)}
.table th{color:var(--muted);font-weight:600;text-transform:uppercase;
font-size:11px;letter-spacing:1px}
.table tr:hover td{background:var(--card-2)}
.mono{font-family:'JetBrains Mono',monospace}
.log{background:#0d0d14;border:1px solid var(--border);border-radius:10px;
padding:14px;font-size:12px;max-height:260px;overflow-y:auto;
white-space:pre-wrap;word-break:break-all;color:var(--muted)}
.hint{color:var(--muted);font-size:12px;margin-top:10px;padding:10px 14px;
background:var(--card-2);border-left:3px solid var(--accent);border-radius:6px}
.hint code{background:#000;padding:2px 6px;border-radius:4px;
color:var(--accent-2);font-size:12px}
footer{margin-top:60px;padding-top:20px;border-top:1px solid var(--border);
color:var(--muted);font-size:12px;text-align:center}
footer .cr{color:var(--accent);font-weight:700}
@media (max-width:600px){.container{padding:16px 14px 40px}
.stat .value{font-size:22px}.card{padding:16px}}
"""


def _html_wrap(title, body):
    return f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} — FF Ghost Bot</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;800&family=Cairo:wght@400;600;800&display=swap" rel="stylesheet">
<style>{BASE_CSS}</style>
</head>
<body>
<div class="container">
<header class="top">
<div class="logo">FF GHOST BOT</div>
<div class="status-pill"><span class="dot"></span> ONLINE</div>
</header>
{body}
<footer>Powered by <span class="cr">ALPHA XK</span> · 6767 · Free Fire OB55</footer>
</div>
</body>
</html>"""


def render_dashboard():
    accs = get_accounts()
    count = len(accs)

    body = f"""
<div class="grid">
<div class="stat"><div class="label">Accounts</div><div class="value accent">{count} / {MAX_ACCOUNTS}</div></div>
<div class="stat"><div class="label">Max Session</div><div class="value accent2">{MAX_SESSION_SECONDS}s</div></div>
<div class="stat"><div class="label">Region</div><div class="value success">ME</div></div>
<div class="stat"><div class="label">Release</div><div class="value">OB55</div></div>
</div>

<div class="card">
<h2>🚀 تشغيل البوت</h2>
<form method="get" action="/start">
<div class="input-row">
<input type="text" name="team" placeholder="أدخل كود الفريق..." required minlength="1" maxlength="20" autocomplete="off">
<button type="submit">▶ START</button>
<button type="submit" class="ghost" formaction="/login">🔑 Login Only</button>
</div>
</form>
<div class="hint">صيغة الحسابات: <code>password:uid</code> — كل حساب في سطر.</div>
</div>

<div class="card">
<h2>👥 الحسابات ({count})</h2>
<table class="table">
<thead><tr><th>#</th><th>UID</th><th>Password</th></tr></thead>
<tbody>
{"".join(
    f'<tr><td class="mono">{i+1}</td><td class="mono">{u}</td>'
    f'<td class="mono">{p[:8]}…{p[-6:] if len(p)>14 else ""}</td></tr>'
    for i,(u,p) in enumerate(accs[:50])
)}
{f'<tr><td colspan="3" style="text-align:center;color:var(--muted)">… و {count-50} حساب إضافي</td></tr>' if count > 50 else ''}
</tbody>
</table>
</div>

<div class="card">
<h2>➕ إضافة حسابات</h2>
<form method="post" action="/add">
<textarea name="raw" placeholder="password1:uid1&#10;password2:uid2&#10;..."></textarea>
<div style="margin-top:12px"><button type="submit">➕ إضافة</button></div>
</form>
<div class="hint">الحد الأقصى: <code>{MAX_ACCOUNTS}</code>. يقبل أسطر أو فواصل أو <code>;</code>.</div>
</div>

<div class="card">
<h2>📋 API Endpoints</h2>
<table class="table">
<thead><tr><th>Method</th><th>Path</th><th>Description</th></tr></thead>
<tbody>
<tr><td><span class="badge info">GET</span></td><td class="mono">/</td><td>Dashboard</td></tr>
<tr><td><span class="badge success">GET</span></td><td class="mono">/start?team=XXX</td><td>Run (HTML)</td></tr>
<tr><td><span class="badge success">GET</span></td><td class="mono">/start?team=XXX&format=json</td><td>Run (JSON)</td></tr>
<tr><td><span class="badge warn">GET</span></td><td class="mono">/login</td><td>Login check</td></tr>
<tr><td><span class="badge info">GET</span></td><td class="mono">/accounts</td><td>List accounts</td></tr>
<tr><td><span class="badge error">POST</span></td><td class="mono">/add</td><td>Add accounts</td></tr>
</tbody>
</table>
</div>
"""
    return _html_wrap("Dashboard", body)


def render_result(r):
    team = r.get("team", "?")
    status = r.get("status", "unknown")
    elapsed = r.get("elapsed", 0)
    logged = r.get("accounts_logged", 0)
    ran = r.get("accounts_ran", 0)
    results = r.get("results", [])
    login_errors = r.get("login_errors", [])

    if status == "completed" and logged > 0:
        badge = '<span class="badge success">COMPLETED</span>'
    elif status == "failed":
        badge = '<span class="badge error">FAILED</span>'
    else:
        badge = '<span class="badge warn">UNKNOWN</span>'

    def stat_badge(s):
        if s == "success":
            return '<span class="badge success">OK</span>'
        if s and s.startswith("timeout"):
            return f'<span class="badge warn">{s}</span>'
        if s == "no_team_data":
            return '<span class="badge warn">no_team_data</span>'
        if s == "error":
            return '<span class="badge error">ERR</span>'
        return f'<span class="badge info">{s}</span>'

    rows = "".join(
        f'<tr><td class="mono">{x.get("uid","?")}</td>'
        f'<td>{stat_badge(x.get("chat"))}</td>'
        f'<td>{stat_badge(x.get("online"))}</td>'
        f'<td class="mono">{x.get("total_sent",0)}</td></tr>'
        for x in results
    ) or '<tr><td colspan="4" style="text-align:center;color:var(--muted)">لا نتائج</td></tr>'

    login_err_html = ""
    if login_errors:
        errs = "".join(
            f'<tr><td class="mono">{e.get("uid","?")}</td>'
            f'<td style="color:var(--error)">{e.get("error","?")}</td></tr>'
            for e in login_errors
        )
        login_err_html = f"""
<div class="card"><h2>⚠️ Login Errors</h2>
<table class="table"><thead><tr><th>UID</th><th>Error</th></tr></thead>
<tbody>{errs}</tbody></table></div>
"""

    body = f"""
<div class="card">
<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:16px">
{badge}
<span class="badge info">Team: {team}</span>
<span class="badge info">{elapsed}s</span>
</div>
<div class="grid" style="margin-bottom:0">
<div class="stat"><div class="label">Logged</div><div class="value success">{logged}</div></div>
<div class="stat"><div class="label">Ran</div><div class="value accent">{ran}</div></div>
<div class="stat"><div class="label">Duration</div><div class="value accent2">{elapsed}s</div></div>
</div>
</div>

<div class="card"><h2>📊 Results</h2>
<table class="table">
<thead><tr><th>UID</th><th>Chat</th><th>Online</th><th>Sent</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</div>

{login_err_html}

<div class="card"><h2>🔍 Raw JSON</h2>
<div class="log">{json.dumps(r, indent=2, ensure_ascii=False)}</div>
</div>

<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:10px">
<a href="/" style="padding:13px 26px;border-radius:10px;background:linear-gradient(135deg,var(--accent),#ff4d88);color:#fff;font-weight:700;display:inline-block">← Dashboard</a>
<a href="/start?team={team}" style="padding:13px 26px;border-radius:10px;background:transparent;color:var(--accent-2);border:1px solid var(--accent-2);font-weight:700;display:inline-block">🔄 Retry</a>
</div>
"""
    return _html_wrap(f"Result · {team}", body)


def render_login(result):
    total = result.get("total", 0)
    ok = result.get("ok", 0)
    failed = result.get("failed", 0)
    results = result.get("results", [])

    rows = "".join(
        f'<tr><td class="mono">{i+1}</td>'
        f'<td>{"<span class=badge success>OK</span>" if r.get("ok") else "<span class=badge error>FAIL</span>"}</td>'
        f'<td class="mono">{r.get("uid") or "-"}</td>'
        f'<td class="mono">{r.get("name") or "-"}</td></tr>'
        for i, r in enumerate(results)
    ) or '<tr><td colspan="4" style="text-align:center;color:var(--muted)">لا نتائج</td></tr>'

    body = f"""
<div class="grid">
<div class="stat"><div class="label">Total</div><div class="value">{total}</div></div>
<div class="stat"><div class="label">Success</div><div class="value success">{ok}</div></div>
<div class="stat"><div class="label">Failed</div><div class="value" style="color:var(--error)">{failed}</div></div>
</div>
<div class="card"><h2>🔑 Login Status</h2>
<table class="table">
<thead><tr><th>#</th><th>Status</th><th>UID</th><th>Name</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<div style="margin-top:10px">
<a href="/" style="padding:13px 26px;border-radius:10px;background:linear-gradient(135deg,var(--accent),#ff4d88);color:#fff;font-weight:700;display:inline-block">← Dashboard</a>
</div>
"""
    return _html_wrap("Login Status", body)


# ═══════════════════════════════════════════════════════════
#  🚀  FASTAPI APP
# ═══════════════════════════════════════════════════════════

app = FastAPI(title="FF Ghost Bot", version="2.0.0")


@app.get("/", response_class=HTMLResponse)
def root():
    return render_dashboard()


@app.get("/login", response_class=HTMLResponse)
def login_only(format: str = Query("html")):
    accounts = get_accounts()
    with ThreadPoolExecutor(max_workers=min(len(accounts), 15)) as pool:
        futures = [pool.submit(login_account, u, p) for u, p in accounts]
        results = []
        for f in futures:
            try:
                r = f.result(timeout=25)
            except Exception:
                r = None
            results.append({
                "ok": r is not None,
                "uid": r["uid"] if r else None,
                "name": r["name"] if r else None,
            })
    ok_count = sum(1 for r in results if r["ok"])
    payload = {"total": len(accounts), "ok": ok_count,
               "failed": len(accounts) - ok_count, "results": results}
    if format == "json":
        return JSONResponse(payload)
    return render_login(payload)


@app.get("/start")
def start_bot(
    team: str = Query(..., min_length=1, max_length=20),
    format: str = Query("html"),
):
    if not team.strip():
        raise HTTPException(400, "Team code required")

    start_time = time.time()
    deadline = start_time + MAX_SESSION_SECONDS

    accounts = get_accounts()
    if not accounts:
        raise HTTPException(400, "لا يوجد حسابات")

    sessions = []
    login_errors = []
    with ThreadPoolExecutor(max_workers=min(len(accounts), 15)) as pool:
        futures = {uid: pool.submit(login_account, uid, pw)
                   for uid, pw in accounts}
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
        payload = {"status": "failed", "reason": "no sessions",
                   "team": team, "elapsed": round(time.time() - start_time, 2),
                   "login_errors": login_errors, "results": [],
                   "accounts_logged": 0, "accounts_ran": 0}
        if format == "json":
            return JSONResponse(status_code=502, content=payload)
        return HTMLResponse(render_result(payload), status_code=502)

    barrier = threading.Barrier(len(sessions))
    results = []
    threads = []
    for s in sessions:
        t = threading.Thread(
            target=lambda sdata=s: results.extend(
                run_one_account(sdata, team, barrier, deadline)),
            daemon=True,
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=max(0.1, deadline - time.time()))

    by_account = {}
    for r in results:
        uid = str(r.get("uid"))
        entry = by_account.setdefault(uid, {
            "uid": uid, "chat": None, "online": None,
            "total_sent": 0, "errors": [],
        })
        if r["tag"] == "ChaT":
            entry["chat"] = r["status"]
        else:
            entry["online"] = r["status"]
        entry["total_sent"] += r.get("sent", 0)
        if r.get("error"):
            entry["errors"].append(f"{r['tag']}: {r['error']}")

    payload = {
        "status": "completed", "team": team,
        "elapsed": round(time.time() - start_time, 2),
        "accounts_logged": len(sessions),
        "accounts_ran": len(by_account),
        "login_errors": login_errors,
        "results": list(by_account.values()),
    }

    if format == "json":
        return JSONResponse(payload)
    return HTMLResponse(render_result(payload))


@app.get("/accounts")
def list_accounts():
    accs = get_accounts()
    return {
        "count": len(accs), "max": MAX_ACCOUNTS,
        "accounts": [
            {"uid": u, "password_masked": p[:6] + "..." + p[-4:] if len(p) > 12 else "***"}
            for u, p in accs
        ],
    }


@app.post("/add")
async def add_accounts_endpoint(request: Request):
    raw = ""
    ct = request.headers.get("content-type", "")
    if "application/json" in ct:
        try:
            body = await request.json()
            raw = body.get("raw", "") if isinstance(body, dict) else ""
        except Exception:
            raw = ""
    else:
        try:
            form = await request.form()
            raw = form.get("raw", "")
        except Exception:
            pass
        if not raw:
            try:
                body = await request.body()
                raw = body.decode("utf-8", errors="ignore")
            except Exception:
                raw = ""
    if not raw.strip():
        raise HTTPException(400, "No data")
    added = add_accounts(raw)
    return JSONResponse({"added": added, "total": len(get_accounts()),
                         "max": MAX_ACCOUNTS})


@app.get("/api/status")
def api_status():
    return {
        "status": "ok",
        "accounts": len(get_accounts()),
        "max_accounts": MAX_ACCOUNTS,
        "max_session_seconds": MAX_SESSION_SECONDS,
        "release": "OB55", "region": "ME",
    }
