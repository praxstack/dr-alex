"""A pure Unicode-block sparkline renderer for the 30-day mood arc (right rail + export).

Deterministic and side-effect-free so it unit-tests trivially. Maps a series of numeric
values onto the eight block glyphs ``▁▂▃▄▅▆▇█``; ``None`` gaps render as a space so a
missing day reads as a gap, not a fabricated low.
"""

from __future__ import annotations

from collections.abc import Sequence

_BLOCKS = "▁▂▃▄▅▆▇█"
_GAP = " "


def sparkline(
    values: Sequence[float | None],
    *,
    lo: float | None = None,
    hi: float | None = None,
) -> str:
    """Render ``values`` as a block-glyph sparkline.

    ``lo``/``hi`` fix the scale (default: the min/max of the present values). For mood the
    caller passes ``lo=1, hi=10`` so the arc is comparable across sessions. A flat series
    renders at the low block; an all-empty series renders as spaces.
    """
    present = [v for v in values if v is not None]
    if not present:
        return _GAP * len(values)
    lo = min(present) if lo is None else lo
    hi = max(present) if hi is None else hi
    span = (hi - lo) or 1.0
    out = []
    for v in values:
        if v is None:
            out.append(_GAP)
            continue
        # clamp into [lo, hi] then bucket into 0..7
        frac = (min(max(v, lo), hi) - lo) / span
        out.append(_BLOCKS[min(int(frac * (len(_BLOCKS) - 1) + 0.5), len(_BLOCKS) - 1)])
    return "".join(out)
