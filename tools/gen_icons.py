"""Genera los íconos PNG de la PWA sin dependencias externas.

Dibuja el logo de Nexus (un nodo central con cuatro satélites conectados,
sobre un cuadrado redondeado morado) y lo exporta a PNG usando solo la
librería estándar (`zlib` + un codificador PNG mínimo).

Renderiza con supersampling para que los bordes queden suaves.

Uso:
    python3 tools/gen_icons.py

Genera:
    static/icons/nexus-192.png
    static/icons/nexus-512.png
    static/icons/nexus-512-maskable.png
    static/icons/apple-touch-icon.png   (180x180, fondo sólido)
"""
from __future__ import annotations

import math
import os
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "static", "icons")

# Paleta (la misma del favicon del hub).
BG = (108, 92, 231)        # #6c5ce7 morado
NODE = (255, 255, 255)     # blanco centro
SAT = (162, 155, 254)      # #a29bfe lavanda
LINE = (255, 255, 255, 120)  # líneas blancas semitransparentes


def _mix(dst, src):
    """Alpha-compositing de src (r,g,b,a) sobre dst (r,g,b,a)."""
    sr, sg, sb, sa = src
    dr, dg, db, da = dst
    a = sa / 255.0
    nr = sr * a + dr * (1 - a)
    ng = sg * a + dg * (1 - a)
    nb = sb * a + db * (1 - a)
    na = sa + da * (1 - a)
    return (nr, ng, nb, na)


def _dist_seg(px, py, ax, ay, bx, by):
    """Distancia de un punto al segmento AB."""
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def render(size: int, maskable: bool = False) -> bytes:
    """Renderiza el ícono a una imagen RGBA de size×size (bytes PNG)."""
    ss = 4  # supersampling
    S = size * ss
    # Buffer de floats RGBA, transparente por defecto.
    buf = [[(0.0, 0.0, 0.0, 0.0) for _ in range(S)] for _ in range(S)]

    cx = cy = S / 2.0
    # Margen: maskable necesita "safe zone" (el ícono vive en el 80% central).
    pad = S * (0.0 if maskable else 0.06)
    rect = (pad, pad, S - pad, S - pad)
    radius = S * 0.22
    # Para maskable el fondo cubre todo el lienzo (sin esquinas redondeadas).
    if maskable:
        radius = 0.0

    # Geometría del logo (relativa al lienzo útil).
    inner = (S / 2.0) * (0.74 if not maskable else 0.62)
    node_r = S * (0.105 if not maskable else 0.088)
    sat_r = S * (0.052 if not maskable else 0.044)
    line_w = S * 0.018
    sats = []
    for ang in (45, 135, 225, 315):
        a = math.radians(ang)
        sats.append((cx + math.cos(a) * inner, cy + math.sin(a) * inner))

    for y in range(S):
        row = buf[y]
        for x in range(S):
            px, py = x + 0.5, y + 0.5
            col = row[x]

            # Fondo redondeado.
            inside_bg = False
            if rect[0] <= px <= rect[2] and rect[1] <= py <= rect[3]:
                if radius <= 0:
                    inside_bg = True
                else:
                    ix = min(max(px, rect[0] + radius), rect[2] - radius)
                    iy = min(max(py, rect[1] + radius), rect[3] - radius)
                    inside_bg = math.hypot(px - ix, py - iy) <= radius
            if inside_bg:
                col = _mix(col, (BG[0], BG[1], BG[2], 255))

            # Líneas centro→satélite.
            for sx, sy in sats:
                d = _dist_seg(px, py, cx, cy, sx, sy)
                if d <= line_w:
                    col = _mix(col, LINE)

            # Satélites.
            for sx, sy in sats:
                if math.hypot(px - sx, py - sy) <= sat_r:
                    col = _mix(col, (SAT[0], SAT[1], SAT[2], 255))

            # Nodo central.
            if math.hypot(px - cx, py - cy) <= node_r:
                col = _mix(col, (NODE[0], NODE[1], NODE[2], 255))

            row[x] = col

    # Downsample (promedio de ss×ss) a RGBA bytes.
    raw = bytearray()
    for y in range(size):
        raw.append(0)  # filtro PNG "none" por fila
        for x in range(size):
            r = g = b = a = 0.0
            for dy in range(ss):
                for dx in range(ss):
                    pr, pg, pb, pa = buf[y * ss + dy][x * ss + dx]
                    r += pr; g += pg; b += pb; a += pa
            n = ss * ss
            raw += bytes((int(r / n + 0.5), int(g / n + 0.5),
                          int(b / n + 0.5), int(a / n + 0.5)))
    return _png(size, size, bytes(raw))


def _png(w: int, h: int, raw: bytes) -> bytes:
    """Codifica RGBA crudo (con byte de filtro por fila) a PNG."""
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return c + struct.pack(">I", crc)

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)  # 8-bit RGBA
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    targets = [
        ("nexus-192.png", 192, False),
        ("nexus-512.png", 512, False),
        ("nexus-512-maskable.png", 512, True),
        ("apple-touch-icon.png", 180, True),
    ]
    for name, size, maskable in targets:
        data = render(size, maskable=maskable)
        path = os.path.join(OUT_DIR, name)
        with open(path, "wb") as fh:
            fh.write(data)
        print(f"✓ {name}  ({len(data)} bytes)")


if __name__ == "__main__":
    main()
