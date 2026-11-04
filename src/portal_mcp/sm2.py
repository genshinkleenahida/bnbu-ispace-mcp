"""Pure-Python SM3 hash and SM2 encryption (C1C3C2): just what the BNBU single sign-on login form needs."""
import secrets
import struct

P = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF00000000FFFFFFFFFFFFFFFF
A = P - 3
N = 0xFFFFFFFEFFFFFFFFFFFFFFFFFFFFFFFF7203DF6B21C6052B53BBF40939D54123
G = (0x32C4AE2C1F1981195F9904466A39C9948FE30BBFF2660BE1715A4589334C74C7,
     0xBC3736A2F4F6779C59BDCEE36B692153D0A9877CC62A474002DF32E52139F0A0)
M = 0xFFFFFFFF


def _rl(x, n):
    n %= 32
    return ((x << n) | (x >> (32 - n))) & M


def sm3(data: bytes) -> bytes:
    v = [0x7380166F, 0x4914B2B9, 0x172442D7, 0xDA8A0600, 0xA96F30BC, 0x163138AA, 0xE38DEE4D, 0xB0FB0E4E]
    data += b"\x80" + b"\x00" * ((55 - len(data)) % 64) + struct.pack(">Q", len(data) * 8)
    for off in range(0, len(data), 64):
        w = list(struct.unpack(">16I", data[off:off + 64]))
        for j in range(16, 68):
            x = w[j - 16] ^ w[j - 9] ^ _rl(w[j - 3], 15)
            w.append(x ^ _rl(x, 15) ^ _rl(x, 23) ^ _rl(w[j - 13], 7) ^ w[j - 6])
        a, b, c, d, e, f, g, h = v
        for j in range(64):
            ss1 = _rl((_rl(a, 12) + e + _rl(0x79CC4519 if j < 16 else 0x7A879D8A, j)) & M, 7)
            ss2 = ss1 ^ _rl(a, 12)
            ff, gg = (a ^ b ^ c, e ^ f ^ g) if j < 16 else ((a & b) | (a & c) | (b & c), (e & f) | (~e & M & g))
            tt1 = (ff + d + ss2 + (w[j] ^ w[j + 4])) & M
            tt2 = (gg + h + ss1 + w[j]) & M
            d, c, b, a = c, _rl(b, 9), a, tt1
            h, g, f, e = g, _rl(f, 19), e, tt2 ^ _rl(tt2, 9) ^ _rl(tt2, 17)
        v = [x ^ y for x, y in zip(v, [a, b, c, d, e, f, g, h])]
    return b"".join(struct.pack(">I", x) for x in v)


def _add(p, q):
    if p is None or q is None:
        return p or q
    (x1, y1), (x2, y2) = p, q
    if x1 == x2:
        if (y1 + y2) % P == 0:
            return None
        lam = (3 * x1 * x1 + A) * pow(2 * y1, -1, P) % P
    else:
        lam = (y2 - y1) * pow(x2 - x1, -1, P) % P
    x3 = (lam * lam - x1 - x2) % P
    return x3, (lam * (x1 - x3) - y1) % P


def _mul(k, p):
    r = None
    while k:
        if k & 1:
            r = _add(r, p)
        p, k = _add(p, p), k >> 1
    return r


def _kdf(z: bytes, n: int) -> bytes:
    out, ct = b"", 1
    while len(out) < n:
        out += sm3(z + struct.pack(">I", ct))
        ct += 1
    return out[:n]


def encrypt(public_key_hex: str, plaintext: bytes) -> str:
    """Return lowercase hex 04||x1||y1||C3||C2. The key is x||y in hex (a leading 04 is accepted)."""
    pk = public_key_hex.strip()[-128:]
    pub = (int(pk[:64], 16), int(pk[64:], 16))
    while True:
        k = secrets.randbelow(N - 1) + 1
        x2, y2 = (c.to_bytes(32, "big") for c in _mul(k, pub))
        t = _kdf(x2 + y2, len(plaintext))
        if any(t):
            break
    c1 = b"".join(c.to_bytes(32, "big") for c in _mul(k, G))
    return (b"\x04" + c1 + sm3(x2 + plaintext + y2) + bytes(a ^ b for a, b in zip(plaintext, t))).hex()
