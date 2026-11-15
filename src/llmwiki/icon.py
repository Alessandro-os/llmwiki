"""L'icona di LLMWiki, disegnata al volo: una sola fonte per l'area di notifica, la finestra
(favicon servita dal server) e l'eseguibile (packaging/build.ps1 la salva come .ico)."""

from __future__ import annotations

import io
from functools import cache

ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)]


def make_icon(size: int = 64):
    """Un quadrato scuro con tre righe e un segno di spunta verde."""
    from PIL import Image, ImageDraw

    scale = size / 64
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2 * scale, 2 * scale, 62 * scale, 62 * scale), radius=14 * scale,
                           fill=(24, 24, 22, 255), outline=(95, 191, 127, 255), width=max(1, round(2 * scale)))
    for y, width in ((20, 30), (30, 22), (40, 26)):
        draw.rounded_rectangle((14 * scale, y * scale, (14 + width) * scale, (y + 4) * scale),
                               radius=2 * scale, fill=(236, 235, 230, 255))
    draw.line([(38 * scale, 42 * scale), (44 * scale, 49 * scale), (54 * scale, 33 * scale)],
              fill=(95, 191, 127, 255), width=max(2, round(5 * scale)), joint="curve")
    return image


@cache
def icon_bytes(kind: str) -> bytes:
    """`ico` (più dimensioni, per Windows) oppure `png` (256 px)."""
    buffer = io.BytesIO()
    if kind == "ico":
        make_icon(256).save(buffer, format="ICO", sizes=ICO_SIZES)
    else:
        make_icon(256).save(buffer, format="PNG")
    return buffer.getvalue()
