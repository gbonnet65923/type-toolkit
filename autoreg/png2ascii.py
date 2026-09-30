import struct
import sys
import zlib

path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\User\tmp\bpproxy_run\cb_captcha.png"
data = open(path, "rb").read()
assert data[:8] == b"\x89PNG\r\n\x1a\n", "not PNG"

pos = 8
idat = b""
plte = None
trns = None
while pos < len(data):
    (ln,) = struct.unpack(">I", data[pos : pos + 4])
    typ = data[pos + 4 : pos + 8]
    chunk = data[pos + 8 : pos + 8 + ln]
    if typ == b"IHDR":
        w, h, depth, ctype, _, _, _ = struct.unpack(">IIBBBBB", chunk)
    elif typ == b"IDAT":
        idat += chunk
    elif typ == b"PLTE":
        plte = chunk
    elif typ == b"tRNS":
        trns = chunk
    pos += 12 + ln

assert depth == 8, f"depth {depth} unsupported"
raw = zlib.decompress(idat)
bpp = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
stride = w * bpp
px = bytearray(h * stride)

# unfilter
ri = 0
prev = bytearray(stride)
for y in range(h):
    f = raw[ri]
    ri += 1
    line = bytearray(raw[ri : ri + stride])
    ri += stride
    if f == 1:
        for i in range(bpp, stride):
            line[i] = (line[i] + line[i - bpp]) & 255
    elif f == 2:
        for i in range(stride):
            line[i] = (line[i] + prev[i]) & 255
    elif f == 3:
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + ((a + prev[i]) >> 1)) & 255
    elif f == 4:
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            p = a + b - c
            pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
            pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
            line[i] = (line[i] + pr) & 255
    px[y * stride : (y + 1) * stride] = line
    prev = line

def lum(x, y):
    o = y * stride + x * bpp
    if ctype == 0:
        return px[o]
    if ctype == 2:
        return (px[o] + px[o + 1] + px[o + 2]) // 3
    if ctype == 3:
        idx = px[o]
        return (plte[idx * 3] + plte[idx * 3 + 1] + plte[idx * 3 + 2]) // 3
    if ctype == 4:
        return px[o]
    if ctype == 6:
        return (px[o] + px[o + 1] + px[o + 2]) // 3

# ASCII downsample
cols = 110
rows = max(1, int(h * (cols / w) * 0.5))
for ry in range(rows):
    y = min(h - 1, int(ry * h / rows))
    line = []
    for rx in range(cols):
        x = min(w - 1, int(rx * w / cols))
        line.append("#" if lum(x, y) < 128 else ".")
    print("".join(line))
