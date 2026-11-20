"""Bounded host PNG observation decoder; bytes confer no execution authority."""
import binascii
import hashlib
import struct
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'
MAX_BYTES = 65536


def _require(value):
    if not value:
        raise ValueError('RENDER_PNG_DENIED')


def _paeth(left, up, diagonal):
    point = left + up - diagonal
    a, b, c = abs(point-left), abs(point-up), abs(point-diagonal)
    return left if a <= b and a <= c else up if b <= c else diagonal


def decode_png_summary(raw, *, viewport):
    """Validate bounded noninterlaced 8-bit RGB(A), then derive pixel facts.

    The caller binds these bytes to the same Core sandbox receipt and an exact
    source/profile. This function alone certifies neither Chrome nor a task.
    """
    _require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES and raw.startswith(SIGNATURE))
    _require(type(viewport) is tuple and len(viewport) == 2
             and all(type(value) is int and 0 < value <= 1024 for value in viewport)
             and viewport[0] * viewport[1] <= 262144)
    offset, header, ended, idat_seen, idat_ended = 8, None, False, False, False
    compressed = bytearray()
    ancillary = set()
    chunks = 0
    while offset < len(raw):
        _require(not ended and offset + 12 <= len(raw) and chunks < 128)
        chunks += 1
        size = struct.unpack('>I', raw[offset:offset+4])[0]
        name = raw[offset+4:offset+8]
        _require(size <= MAX_BYTES and offset + 12 + size <= len(raw)
                 and all(65 <= byte <= 90 or 97 <= byte <= 122 for byte in name))
        value = raw[offset+8:offset+8+size]
        crc = struct.unpack('>I', raw[offset+8+size:offset+12+size])[0]
        _require(binascii.crc32(name + value) & 0xFFFFFFFF == crc)
        if header is None:
            _require(name == b'IHDR' and size == 13)
            header = struct.unpack('>IIBBBBB', value)
            width, height, depth, color, compression, filtering, interlace = header
            _require((width, height) == viewport and depth == 8 and color in (2, 6)
                     and compression == filtering == interlace == 0)
        elif name == b'IDAT':
            _require(not idat_ended)
            idat_seen = True
            compressed.extend(value)
            _require(len(compressed) <= MAX_BYTES)
        elif name == b'IEND':
            _require(size == 0 and idat_seen)
            ended = True
        else:
            # Deliberate static RGB(A) subset. Unhandled transparency/animation
            # or color metadata must not create false host-side pixel evidence.
            _require(not idat_seen and name in (b'sRGB', b'gAMA', b'pHYs') and name not in ancillary)
            if name == b'sRGB':
                _require(size == 1 and value[0] <= 3)
            elif name == b'gAMA':
                _require(size == 4 and struct.unpack('>I', value)[0] > 0)
            else:
                _require(size == 9 and value[8] <= 1)
            ancillary.add(name)
        offset += 12 + size
    _require(ended and header is not None and offset == len(raw))
    width, height, _depth, color, *_ = header
    channels = 4 if color == 6 else 3
    stride = width * channels
    expected = (stride + 1) * height
    try:
        inflater = zlib.decompressobj()
        scanlines = inflater.decompress(bytes(compressed), expected + 1)
        _require(len(scanlines) == expected and inflater.eof
                 and not inflater.unused_data and not inflater.unconsumed_tail)
    except zlib.error:
        raise ValueError('RENDER_PNG_DENIED') from None
    previous = bytes(stride)
    ink, first, non_uniform = 0, None, False
    for y in range(height):
        start = y * (stride + 1)
        kind = scanlines[start]
        _require(kind <= 4)
        source = scanlines[start+1:start+1+stride]
        row = bytearray(stride)
        for x, value in enumerate(source):
            left = row[x-channels] if x >= channels else 0
            up = previous[x]
            diagonal = previous[x-channels] if x >= channels else 0
            if kind == 4:
                predictor = _paeth(left, up, diagonal)
            else:
                predictor = (0, left, up, (left+up)//2)[kind]
            row[x] = (value + predictor) & 255
        for x in range(0, stride, channels):
            red, green, blue = row[x:x+3]
            if channels == 4:
                alpha = row[x+3]
                red, green, blue = ((component * alpha + 255 * (255-alpha) + 127) // 255
                                     for component in (red, green, blue))
            pixel = (red, green, blue)
            if first is None:
                first = pixel
            non_uniform = non_uniform or pixel != first
            ink += int(min(pixel) < 250)
        previous = row
    return {'width': width, 'height': height, 'visible_ink_pixels': ink,
            'non_uniform': non_uniform, 'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
