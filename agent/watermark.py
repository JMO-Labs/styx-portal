"""Reference renderer for the encoder-burned watermark (patches/selkies/05).

The pixelflux patch (watermark.rs) implements the same algorithm; this module
is the spec the snapshot test pins. Text comes only from server env; nothing
sent by a client can change it.
"""
import os
from datetime import datetime, timezone

SCALE = 3
PAD = 6
ORIGIN = (16, 16)
FG = (255, 255, 255)
BG = (0, 0, 0)

# 5x7 glyphs, one string of 7 rows (5 chars, '#' = set) joined by '/'.
FONT = {
    " ": "...../...../...../...../...../...../.....",
    "-": "...../...../...../#####/...../...../.....",
    ":": "...../..#../..#../...../..#../..#../.....",
    ".": "...../...../...../...../...../.##../.##..",
    "_": "...../...../...../...../...../...../#####",
    "@": ".###./#...#/#.###/#.###/#.##./#..../.###.",
    "/": "....#/....#/...#./..#../.#.../#..../#....",
    "0": ".###./#...#/#..##/#.#.#/##..#/#...#/.###.",
    "1": "..#../.##../..#../..#../..#../..#../.###.",
    "2": ".###./#...#/....#/...#./..#../.#.../#####",
    "3": "####./....#/....#/.###./....#/....#/####.",
    "4": "...#./..##./.#.#./#..#./#####/...#./...#.",
    "5": "#####/#..../####./....#/....#/#...#/.###.",
    "6": "..##./.#.../#..../####./#...#/#...#/.###.",
    "7": "#####/....#/...#./..#../.#.../.#.../.#...",
    "8": ".###./#...#/#...#/.###./#...#/#...#/.###.",
    "9": ".###./#...#/#...#/.####/....#/...#./.##..",
    "A": ".###./#...#/#...#/#####/#...#/#...#/#...#",
    "B": "####./#...#/#...#/####./#...#/#...#/####.",
    "C": ".###./#...#/#..../#..../#..../#...#/.###.",
    "D": "####./#...#/#...#/#...#/#...#/#...#/####.",
    "E": "#####/#..../#..../####./#..../#..../#####",
    "F": "#####/#..../#..../####./#..../#..../#....",
    "G": ".###./#...#/#..../#.###/#...#/#...#/.###.",
    "H": "#...#/#...#/#...#/#####/#...#/#...#/#...#",
    "I": ".###./..#../..#../..#../..#../..#../.###.",
    "J": "..###/...#./...#./...#./...#./#..#./.##..",
    "K": "#...#/#..#./#.#../##.../#.#../#..#./#...#",
    "L": "#..../#..../#..../#..../#..../#..../#####",
    "M": "#...#/##.##/#.#.#/#.#.#/#...#/#...#/#...#",
    "N": "#...#/##..#/#.#.#/#..##/#...#/#...#/#...#",
    "O": ".###./#...#/#...#/#...#/#...#/#...#/.###.",
    "P": "####./#...#/#...#/####./#..../#..../#....",
    "Q": ".###./#...#/#...#/#...#/#.#.#/#..#./.##.#",
    "R": "####./#...#/#...#/####./#.#../#..#./#...#",
    "S": ".####/#..../#..../.###./....#/....#/####.",
    "T": "#####/..#../..#../..#../..#../..#../..#..",
    "U": "#...#/#...#/#...#/#...#/#...#/#...#/.###.",
    "V": "#...#/#...#/#...#/#...#/#...#/.#.#./..#..",
    "W": "#...#/#...#/#...#/#.#.#/#.#.#/##.##/#...#",
    "X": "#...#/#...#/.#.#./..#../.#.#./#...#/#...#",
    "Y": "#...#/#...#/.#.#./..#../..#../..#../..#..",
    "Z": "#####/....#/...#./..#../.#.../#..../#####",
}
GLYPH_W, GLYPH_H = 5, 7


def text_for(user: str, now: datetime) -> str:
    """Watermark line: user, UTC time. Unknown characters render as '_'."""
    t = now.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    return f"{user} {t}".upper()


def from_env(env=None) -> str:
    """User label comes only from the server environment."""
    env = os.environ if env is None else env
    return env.get("STYX_WATERMARK_USER", "").strip()


def render(frame: bytearray, width: int, height: int, text: str, origin=ORIGIN) -> None:
    """Burn `text` into an RGB (3 bytes/pixel) frame in place."""
    adv = (GLYPH_W + 1) * SCALE
    x0, y0 = origin
    bw = len(text) * adv - SCALE + 2 * PAD
    bh = GLYPH_H * SCALE + 2 * PAD
    px = bytes(BG)
    for y in range(max(y0, 0), min(y0 + bh, height)):
        a = (y * width + max(x0, 0)) * 3
        n = min(x0 + bw, width) - max(x0, 0)
        if n > 0:
            frame[a:a + 3 * n] = px * n
    on = bytes(FG)
    for i, ch in enumerate(text):
        rows = FONT.get(ch, FONT["_"]).split("/")
        gx = x0 + PAD + i * adv
        for r, row in enumerate(rows):
            for c, bit in enumerate(row):
                if bit != "#":
                    continue
                for dy in range(SCALE):
                    y = y0 + PAD + r * SCALE + dy
                    x = gx + c * SCALE
                    if 0 <= y < height and 0 <= x and x + SCALE <= width:
                        a = (y * width + x) * 3
                        frame[a:a + 3 * SCALE] = on * SCALE


class Watermark:
    """Server-owned watermark state. Immutable after construction; there is no client hook."""

    def __init__(self, user: str):
        self._user = user

    @classmethod
    def from_env(cls, env=None):
        return cls(from_env(env))

    def text(self, now: datetime) -> str:
        return text_for(self._user, now)
