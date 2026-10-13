import io

import pytest
from PIL import Image

from newsroom.media.metadata import MalformedImage, strip_metadata

GPS = 0x8825
ORIENTATION = 0x0112
SECRET = b"source-house-33.51N"


def _exif(orientation: int = 1) -> Image.Exif:
    exif = Image.Exif()
    exif[ORIENTATION] = orientation
    exif[0x010F] = SECRET.decode()
    exif[GPS] = {1: "N", 2: (33.0, 51.0, 0.0), 3: "E", 4: (35.0, 30.0, 0.0)}
    return exif


def _picture() -> Image.Image:
    image = Image.new("RGB", (40, 20), (200, 30, 30))
    image.paste((20, 20, 180), (0, 0, 20, 20))
    return image


def _saved(image: Image.Image, fmt: str, **options: object) -> bytes:
    out = io.BytesIO()
    image.save(out, format=fmt, **options)
    return out.getvalue()


def _pixels(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        return image.convert("RGB").tobytes()


def _gps(data: bytes) -> dict:
    with Image.open(io.BytesIO(data)) as image:
        return dict(image.getexif().get_ifd(GPS))


XMP = b'<x:xmpmeta xmlns:x="adobe:ns:meta/">' + SECRET + b"</x:xmpmeta>"


@pytest.mark.parametrize(
    ("fmt", "mime", "options"),
    [
        ("JPEG", "image/jpeg", {"exif": _exif(6), "comment": SECRET, "xmp": XMP, "quality": 90}),
        ("PNG", "image/png", {"exif": _exif()}),
        ("WEBP", "image/webp", {"exif": _exif(), "xmp": XMP, "lossless": True}),
        ("GIF", "image/gif", {"comment": SECRET}),
    ],
)
def test_metadata_is_removed_and_the_pixels_are_untouched(
    fmt: str, mime: str, options: dict
) -> None:
    data = _saved(_picture(), fmt, **options) + b"\x00trailing " + SECRET
    if fmt == "PNG":
        from PIL.PngImagePlugin import PngInfo

        info = PngInfo()
        info.add_text("Location", SECRET.decode())
        info.add_itxt("Source", SECRET.decode(), zip=True)
        data = _saved(_picture(), fmt, pnginfo=info, **options)
    assert SECRET in data

    stripped = strip_metadata(data, mime)

    assert SECRET not in stripped
    assert _gps(stripped) == {}
    assert _pixels(stripped) == _pixels(data)


def test_a_jpeg_keeps_only_its_orientation() -> None:
    data = _saved(_picture(), "JPEG", exif=_exif(6))
    stripped = strip_metadata(data, "image/jpeg")
    with Image.open(io.BytesIO(stripped)) as image:
        exif = image.getexif()
        assert dict(exif) == {ORIENTATION: 6}


def test_an_upright_jpeg_carries_no_exif() -> None:
    stripped = strip_metadata(_saved(_picture(), "JPEG", exif=_exif(1)), "image/jpeg")
    assert b"Exif\x00\x00" not in stripped


def test_an_animated_gif_keeps_its_frames_and_loop() -> None:
    colours = ((255, 0, 0), (0, 255, 0), (0, 0, 255))
    frames = [Image.new("RGB", (8, 8), colour).convert("P") for colour in colours]
    data = _saved(frames[0], "GIF", save_all=True, append_images=frames[1:], loop=0)
    with Image.open(io.BytesIO(data)) as source:
        assert getattr(source, "n_frames", 1) == 3
    stripped = strip_metadata(data, "image/gif")
    with Image.open(io.BytesIO(stripped)) as image:
        assert getattr(image, "n_frames", 1) == 3
        assert image.info.get("loop") == 0


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (b"\xff\xd8\xff\xe1\x00\xff" + b"\x00" * 10, "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\x0dIHDR", "image/png"),
        (b"RIFF\xff\xff\x00\x00WEBPVP8X", "image/webp"),
        (b"GIF89a\x01\x00\x01\x00\x00\x00\x00\x2c", "image/gif"),
    ],
)
def test_a_cut_off_file_is_refused(data: bytes, mime: str) -> None:
    with pytest.raises(MalformedImage):
        strip_metadata(data, mime)
