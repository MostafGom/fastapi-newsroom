"""Remove camera, location, and editing metadata from an uploaded image without re-encoding it.

The pixels are copied byte for byte. Only blocks that describe the picture are dropped:
EXIF (GPS, camera serial, time), XMP, IPTC, comments, and anything after the end of the image.
Colour profiles stay, and a JPEG keeps its orientation so the original still displays upright.
"""

from PIL import Image

_ORIENTATION = 0x0112


class MalformedImage(ValueError):
    pass


def strip_metadata(data: bytes, mime: str) -> bytes:
    try:
        match mime:
            case "image/jpeg":
                return _jpeg(data)
            case "image/png":
                return _png(data)
            case "image/webp":
                return _webp(data)
            case "image/gif":
                return _gif(data)
    except IndexError as exc:
        raise MalformedImage("image ends early") from exc
    raise MalformedImage(f"unsupported type {mime}")


def _jpeg(data: bytes) -> bytes:
    if not data.startswith(b"\xff\xd8"):
        raise MalformedImage("missing start of image")
    out = bytearray(b"\xff\xd8")
    orientation: int | None = None
    i = 2
    while True:
        if data[i] != 0xFF:
            raise MalformedImage("expected a marker")
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xD9:
            out += b"\xff\xd9"
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[i : i + 2]
            i += 2
            continue
        length = int.from_bytes(data[i + 2 : i + 4], "big")
        end = i + 2 + length
        if length < 2 or end > len(data):
            raise MalformedImage("segment runs past the end")
        payload = data[i + 4 : end]
        if marker == 0xE1 and payload.startswith(b"Exif\x00\x00") and orientation is None:
            orientation = _orientation(payload)
        if not _drop_jpeg_segment(marker, payload):
            out += data[i:end]
        i = end
        if marker == 0xDA:
            scan_end = _entropy_end(data, i)
            out += data[i:scan_end]
            i = scan_end
    if orientation is not None and orientation != 1:
        exif = Image.Exif()
        exif[_ORIENTATION] = orientation
        block = exif.tobytes()
        out[2:2] = b"\xff\xe1" + (len(block) + 2).to_bytes(2, "big") + block
    return bytes(out)


def _drop_jpeg_segment(marker: int, payload: bytes) -> bool:
    if marker == 0xFE:
        return True
    if not 0xE1 <= marker <= 0xEF:
        return False
    if marker == 0xE2 and payload.startswith(b"ICC_PROFILE\x00"):
        return False
    # APP14 "Adobe" says how to read CMYK and YCCK colour.
    return not (marker == 0xEE and payload.startswith(b"Adobe"))


def _entropy_end(data: bytes, i: int) -> int:
    """Skip compressed scan data: 0xFF is a marker unless stuffed (00), a restart, or fill."""
    while True:
        i = data.find(b"\xff", i)
        if i < 0 or i + 1 >= len(data):
            raise MalformedImage("scan has no end")
        following = data[i + 1]
        if following == 0x00 or 0xD0 <= following <= 0xD7:
            i += 2
        elif following == 0xFF:
            i += 1
        else:
            return i


def _orientation(payload: bytes) -> int | None:
    exif = Image.Exif()
    try:
        exif.load(payload)
    except Exception:
        # A broken EXIF block is dropped with the rest, not fatal.
        return None
    value = exif.get(_ORIENTATION)
    return value if isinstance(value, int) and 1 <= value <= 8 else None


_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_PNG_DROP = {b"tEXt", b"zTXt", b"iTXt", b"eXIf", b"tIME"}


def _png(data: bytes) -> bytes:
    if not data.startswith(_PNG_SIGNATURE):
        raise MalformedImage("missing PNG signature")
    out = bytearray(_PNG_SIGNATURE)
    i = len(_PNG_SIGNATURE)
    while True:
        if i + 8 > len(data):
            raise MalformedImage("PNG has no end chunk")
        length = int.from_bytes(data[i : i + 4], "big")
        kind = data[i + 4 : i + 8]
        end = i + 12 + length
        if end > len(data):
            raise MalformedImage("chunk runs past the end")
        if kind not in _PNG_DROP:
            out += data[i:end]
        i = end
        if kind == b"IEND":
            return bytes(out)


_VP8X_EXIF = 0x08
_VP8X_XMP = 0x04


def _webp(data: bytes) -> bytes:
    if not (data.startswith(b"RIFF") and data[8:12] == b"WEBP"):
        raise MalformedImage("missing WebP header")
    declared = int.from_bytes(data[4:8], "little") + 8
    if declared > len(data):
        raise MalformedImage("WebP is shorter than its header says")
    out = bytearray(data[:12])
    i = 12
    while i < declared:
        if i + 8 > declared:
            raise MalformedImage("chunk header runs past the end")
        kind = data[i : i + 4]
        size = int.from_bytes(data[i + 4 : i + 8], "little")
        end = i + 8 + size + (size & 1)
        if end > declared:
            raise MalformedImage("chunk runs past the end")
        if kind == b"VP8X":
            chunk = bytearray(data[i:end])
            chunk[8] &= ~(_VP8X_EXIF | _VP8X_XMP) & 0xFF
            out += chunk
        elif kind not in {b"EXIF", b"XMP "}:
            out += data[i:end]
        i = end
    out[4:8] = (len(out) - 8).to_bytes(4, "little")
    return bytes(out)


_GIF_LOOPING = {b"NETSCAPE2.0", b"ANIMEXTS1.0"}


def _gif(data: bytes) -> bytes:
    if not data.startswith((b"GIF87a", b"GIF89a")):
        raise MalformedImage("missing GIF header")
    flags = data[10]
    i = 13 + (3 * 2 ** ((flags & 0x07) + 1) if flags & 0x80 else 0)
    out = bytearray(data[:i])
    while True:
        introducer = data[i]
        if introducer == 0x3B:
            out.append(0x3B)
            return bytes(out)
        if introducer == 0x2C:
            descriptor_flags = data[i + 9]
            start = i
            i += 10
            if descriptor_flags & 0x80:
                i += 3 * 2 ** ((descriptor_flags & 0x07) + 1)
            i = _gif_sub_blocks(data, i + 1)
            out += data[start:i]
        elif introducer == 0x21:
            label = data[i + 1]
            start = i
            i = _gif_sub_blocks(data, i + 2)
            identifier = data[start + 3 : start + 14]
            keep = label not in {0xFE, 0xFF} or (label == 0xFF and identifier in _GIF_LOOPING)
            if keep:
                out += data[start:i]
        else:
            raise MalformedImage("unknown GIF block")


def _gif_sub_blocks(data: bytes, i: int) -> int:
    while True:
        size = data[i]
        i += 1 + size
        if size == 0:
            return i
        if i > len(data):
            raise MalformedImage("sub-block runs past the end")
