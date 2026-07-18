"""Date-ranged export → markdown + a SELF-CONTAINED styled HTML (council D6).

``dr-alex export --from <date> --to <date> --redaction summary|full`` emits two files into
``exports/`` (0700, gitignored; filenames = the date range ONLY, never clinical content):

  * a plain **markdown** rollup, and
  * a **self-contained HTML** designed for macOS print-to-PDF: inline CSS, a system font stack,
    an inline-SVG mood chart, and **ZERO external assets**. A stray font/CDN link would be an
    egress beacon, so ``tests/test_export_no_external_fetch.py`` asserts the HTML makes no
    remote link/script/img/@import/webfont request (council D6 rider 1).

Redaction (council D6 rider 3), default ``summary``:
  * ``summary`` — trends and counts only: mood chart + stats, session/turn counts, risk-event
    counts, homework counts, the *names* of the living patterns. No verbatim content.
  * ``full``    — the above plus homework titles, risk-event dates, and the Active File's
    session-log detail for the window (techniques, insights, threads).

The exporter READS the configured Active File + ``state.db`` paths — it never hardcodes them
(council D4 rider 3).
"""

from __future__ import annotations

import datetime as _dt
import html as _html
import os
from dataclasses import dataclass, field
from pathlib import Path

from dr_alex import config, records, statedb, timeutil
from dr_alex.statedb import IST

VALID_REDACTIONS = ("summary", "full")


# ---------------------------------------------------------------------------
# Data collection
# ---------------------------------------------------------------------------


@dataclass
class ExportData:
    from_date: str
    to_date: str
    redaction: str
    generated_at: str
    mood_series: list[tuple[str, float | None]] = field(default_factory=list)  # (date_ist, mood)
    mood_points: int = 0
    mood_mean: float | None = None
    mood_delta: float | None = None
    green: int = 0
    amber: int = 0
    red: int = 0
    risk_events: list[tuple[str, str]] = field(default_factory=list)  # (ts, tier) AMBER/RED
    sessions: int = 0
    homework_open: int = 0
    homework_done: int = 0
    homework_titles_open: list[str] = field(default_factory=list)  # full redaction only
    pattern_names: list[str] = field(default_factory=list)
    late_night_count: int = 0
    late_night_flagged: bool = False
    session_log_detail: str | None = None  # full redaction only


def _coerce_redaction(value: str | None) -> str:
    v = (value or "summary").strip().lower()
    return v if v in VALID_REDACTIONS else "summary"


def _bounds(from_date: str, to_date: str) -> tuple[str, str]:
    return f"{from_date}T00:00:00Z", f"{to_date}T23:59:59Z"


def _iso(now: _dt.datetime) -> str:
    return timeutil.now_iso(now)


def _days_between(from_date: str, to_date: str) -> list[str]:
    d0 = _dt.date.fromisoformat(from_date)
    d1 = _dt.date.fromisoformat(to_date)
    if d1 < d0:
        d0, d1 = d1, d0
    out = []
    cur = d0
    while cur <= d1:
        out.append(cur.isoformat())
        cur += _dt.timedelta(days=1)
    return out


def _daily_series(mood_events: list[tuple[str, int]], days: list[str]) -> list[tuple[str, float | None]]:
    by_day: dict[str, int] = {}
    for ts, mood in mood_events:  # ordered oldest→newest, last write per IST day wins
        try:
            dt = _dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
        except ValueError:
            continue
        by_day[dt.strftime("%Y-%m-%d")] = mood
    return [(d, float(by_day[d]) if d in by_day else None) for d in days]


def collect(
    from_date: str, to_date: str, *, redaction: str, now: _dt.datetime,
    state_path: Path | None = None, active_path: Path | None = None,
) -> ExportData:
    redaction = _coerce_redaction(redaction)
    from_iso, to_iso = _bounds(from_date, to_date)
    days = _days_between(from_date, to_date)

    data = ExportData(
        from_date=from_date, to_date=to_date, redaction=redaction, generated_at=_iso(now),
    )

    mood_events = statedb.mood_events_between(from_iso, to_iso, path=state_path)
    data.mood_series = _daily_series(mood_events, days)
    moods = [m for _ts, m in mood_events]
    if moods:
        data.mood_points = len(moods)
        data.mood_mean = round(sum(moods) / len(moods), 2)
        data.mood_delta = float(moods[-1] - moods[0]) if len(moods) >= 2 else 0.0

    tiers = statedb.turn_tiers_between(from_iso, to_iso, path=state_path)
    for ts, tier in tiers:
        if tier == "GREEN":
            data.green += 1
        elif tier == "AMBER":
            data.amber += 1
            data.risk_events.append((ts, tier))
        elif tier == "RED":
            data.red += 1
            data.risk_events.append((ts, tier))

    # Session count scoped to the requested [from, to] range (not a now-anchored window).
    sessions = statedb.sessions_between(from_iso, to_iso, path=state_path)
    data.sessions = len(sessions)
    data.late_night_count = sum(1 for _id, hour in sessions if hour in statedb.NIGHT_HOURS_IST)
    data.late_night_flagged = data.late_night_count >= statedb.LATE_NIGHT_THRESHOLD

    all_hw = statedb.all_homework(path=state_path)
    data.homework_open = sum(1 for h in all_hw if h.status == "open")
    data.homework_done = sum(1 for h in all_hw if h.status == "done")
    if redaction == "full":
        data.homework_titles_open = [h.title for h in all_hw if h.status == "open"]

    active_text = records.read_text(active_path)
    data.pattern_names = [d.name for d in records.parse_pattern_docs(active_text)]
    if redaction == "full":
        data.session_log_detail = _session_log_in_window(active_text, from_date, to_date)

    return data


def _session_log_in_window(active_text: str | None, from_date: str, to_date: str) -> str | None:
    """Extract the Active File session-log entries whose date falls in [from, to] (full only)."""
    if not active_text or "## Session Log" not in active_text:
        return None
    body = active_text.split("## Session Log", 1)[1].split("\n## ", 1)[0]
    entries = [e for e in body.split("### session ") if e.strip()]
    kept: list[str] = []
    for e in entries:
        # First line: "<id> · <date> · risk <tier>"
        head = e.splitlines()[0]
        parts = [p.strip() for p in head.split("·")]
        date = parts[1] if len(parts) >= 2 else ""
        if from_date <= date <= to_date:
            kept.append("### session " + e.rstrip())
    return "\n\n".join(kept) if kept else None


# ---------------------------------------------------------------------------
# Inline SVG mood chart (no external assets)
# ---------------------------------------------------------------------------


def mood_svg(series: list[tuple[str, float | None]], *, width: int = 640, height: int = 180) -> str:
    """A tiny self-contained SVG line chart of daily mood (1–10). Gaps stay gaps."""
    pad = 24
    n = max(1, len(series))
    plot_w = width - 2 * pad
    plot_h = height - 2 * pad
    step = plot_w / max(1, n - 1) if n > 1 else 0

    def x(i: int) -> float:
        return pad + (i * step if n > 1 else plot_w / 2)

    def y(m: float) -> float:
        # mood 1..10 → bottom..top
        return pad + plot_h * (1 - (m - 1) / 9)

    # Build polyline segments, breaking on None gaps.
    segments: list[list[str]] = []
    cur: list[str] = []
    dots: list[str] = []
    for i, (_d, m) in enumerate(series):
        if m is None:
            if cur:
                segments.append(cur)
                cur = []
            continue
        px, py = x(i), y(m)
        cur.append(f"{px:.1f},{py:.1f}")
        dots.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.5" fill="#6f7fd0"/>')
    if cur:
        segments.append(cur)

    gridlines = "".join(
        f'<line x1="{pad}" y1="{y(v):.1f}" x2="{width - pad}" y2="{y(v):.1f}" '
        f'stroke="#e2e2ee" stroke-width="1"/>'
        for v in (2, 4, 6, 8, 10)
    )
    labels = "".join(
        f'<text x="{pad - 6:.0f}" y="{y(v) + 3:.0f}" font-size="9" fill="#9aa0b5" '
        f'text-anchor="end">{v}</text>' for v in (2, 6, 10)
    )
    polylines = "".join(
        f'<polyline points="{" ".join(seg)}" fill="none" stroke="#6f7fd0" stroke-width="2"/>'
        for seg in segments if len(seg) >= 2
    )
    # For single-point segments, the dots (already added) carry the signal.
    empty = "" if any(m is not None for _d, m in series) else (
        f'<text x="{width / 2:.0f}" y="{height / 2:.0f}" font-size="12" fill="#9aa0b5" '
        f'text-anchor="middle">no mood chips in this window</text>')
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="Daily mood chart" xmlns="http://www.w3.org/2000/svg">'
        f'<rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>'
        f'{gridlines}{labels}{polylines}{"".join(dots)}{empty}</svg>'
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def render_markdown(d: ExportData) -> str:
    lines = [
        f"# Dr. Alex — export {d.from_date} → {d.to_date}",
        "",
        f"_Generated {d.generated_at} · redaction: **{d.redaction}** · IST-labeled._",
        "",
        "> Local export for print-to-PDF. Self-report + observed agent interaction, not a "
        "diagnosis. Never auto-sent.",
        "",
        "## Mood",
        "",
        (f"- points: {d.mood_points} · mean: {d.mood_mean} · net change: {d.mood_delta}"
         if d.mood_points else "- no mood chips recorded in this window"),
    ]
    # A compact text sparkline of the daily series.
    spark = _text_spark(d.mood_series)
    if spark:
        lines += ["", f"`{spark}`  (1–10 per day; `·` = no chip)"]

    lines += [
        "",
        "## Risk events",
        "",
        f"- turns: {d.green + d.amber + d.red} (GREEN {d.green} · AMBER {d.amber} · RED {d.red})",
    ]
    if d.redaction == "full" and d.risk_events:
        lines.append("- flagged turns:")
        lines += [f"  - {ts} — {tier}" for ts, tier in d.risk_events]
    elif d.amber or d.red:
        lines.append(f"- {d.amber + d.red} AMBER/RED turn(s) in window (dates in the full export)")

    lines += [
        "",
        "## Sessions & dependency signal",
        "",
        f"- sessions in window: {d.sessions}",
        (f"- late-night (00:00–05:00 IST): {d.late_night_count}"
         + (" — clustering flagged (G18)" if d.late_night_flagged else "")),
        "",
        "## Homework",
        "",
        f"- open: {d.homework_open} · done: {d.homework_done}",
    ]
    if d.redaction == "full" and d.homework_titles_open:
        lines += [f"  - [ ] {t}" for t in d.homework_titles_open]

    lines += ["", "## Named patterns", ""]
    lines.append("- " + (", ".join(d.pattern_names) if d.pattern_names else "(none named yet)"))

    if d.redaction == "full" and d.session_log_detail:
        lines += ["", "## Session log (window)", "", d.session_log_detail]

    return "\n".join(lines).rstrip() + "\n"


def _text_spark(series: list[tuple[str, float | None]]) -> str:
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for _d, m in series:
        if m is None:
            out.append("·")
        else:
            idx = min(len(blocks) - 1, max(0, int(round((m - 1) / 9 * (len(blocks) - 1)))))
            out.append(blocks[idx])
    return "".join(out)


# ---------------------------------------------------------------------------
# Self-contained HTML rendering (ZERO external assets)
# ---------------------------------------------------------------------------

_CSS = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
       color: #23262f; background: #ffffff; margin: 0; padding: 2rem; line-height: 1.5; }
.wrap { max-width: 760px; margin: 0 auto; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.05rem; margin: 1.5rem 0 .5rem; border-bottom: 1px solid #ececf4; padding-bottom: .2rem; }
.meta { color: #6b7080; font-size: .85rem; }
.note { background: #f6f6fb; border-left: 3px solid #b9b2e6; padding: .6rem .9rem; border-radius: 4px;
        color: #4a4f63; font-size: .9rem; margin: 1rem 0; }
.chart { margin: .75rem 0 1rem; border: 1px solid #ececf4; border-radius: 6px; overflow: hidden; }
ul { margin: .3rem 0 .3rem 1.1rem; padding: 0; }
.kv { display: flex; gap: 1.5rem; flex-wrap: wrap; margin: .4rem 0; }
.kv div { background: #f6f6fb; border-radius: 6px; padding: .5rem .8rem; font-size: .9rem; }
.kv b { display: block; font-size: 1.2rem; color: #3a3f57; }
pre { background: #f6f6fb; padding: .8rem; border-radius: 6px; overflow-x: auto; font-size: .82rem; }
@media print { body { padding: 0; } .note { break-inside: avoid; } }
"""


def _esc(s: str) -> str:
    return _html.escape(s, quote=True)


def render_html(d: ExportData) -> str:
    chart = mood_svg(d.mood_series)
    spark = _text_spark(d.mood_series)

    risk_detail = ""
    if d.redaction == "full" and d.risk_events:
        items = "".join(f"<li>{_esc(ts)} — {_esc(tier)}</li>" for ts, tier in d.risk_events)
        risk_detail = f"<ul>{items}</ul>"

    hw_detail = ""
    if d.redaction == "full" and d.homework_titles_open:
        items = "".join(f"<li>{_esc(t)}</li>" for t in d.homework_titles_open)
        hw_detail = f"<p>Open:</p><ul>{items}</ul>"

    patterns = _esc(", ".join(d.pattern_names)) if d.pattern_names else "(none named yet)"

    session_detail = ""
    if d.redaction == "full" and d.session_log_detail:
        session_detail = (
            "<h2>Session log (window)</h2>"
            f"<pre>{_esc(d.session_log_detail)}</pre>"
        )

    mood_kv = (
        f'<div><b>{d.mood_points}</b>mood chips</div>'
        f'<div><b>{d.mood_mean if d.mood_mean is not None else "—"}</b>mean</div>'
        f'<div><b>{d.mood_delta if d.mood_delta is not None else "—"}</b>net change</div>'
    )
    late = (f"{d.late_night_count}" + (" (flagged)" if d.late_night_flagged else ""))

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dr. Alex export {_esc(d.from_date)} to {_esc(d.to_date)}</title>
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <h1>Dr. Alex — export</h1>
  <p class="meta">{_esc(d.from_date)} → {_esc(d.to_date)} · generated {_esc(d.generated_at)} ·
     redaction <b>{_esc(d.redaction)}</b> · IST-labeled</p>
  <div class="note">Local export for print-to-PDF. Reflects Prax's self-report and observed
     agent interaction, not a diagnosis. This file is generated locally and never auto-sent.</div>

  <h2>Mood</h2>
  <div class="kv">{mood_kv}</div>
  <div class="chart">{chart}</div>
  <p class="meta">{_esc(spark)} &nbsp;(1–10 per day; · = no chip)</p>

  <h2>Risk events</h2>
  <div class="kv">
    <div><b>{d.green}</b>GREEN</div><div><b>{d.amber}</b>AMBER</div><div><b>{d.red}</b>RED</div>
  </div>
  {risk_detail}

  <h2>Sessions &amp; dependency signal</h2>
  <div class="kv"><div><b>{d.sessions}</b>sessions</div><div><b>{late}</b>late-night IST</div></div>

  <h2>Homework</h2>
  <div class="kv"><div><b>{d.homework_open}</b>open</div><div><b>{d.homework_done}</b>done</div></div>
  {hw_detail}

  <h2>Named patterns</h2>
  <p>{patterns}</p>

  {session_detail}
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Orchestration + write-out
# ---------------------------------------------------------------------------


@dataclass
class ExportResult:
    ok: bool
    redaction: str
    from_date: str
    to_date: str
    markdown_path: str | None = None
    html_path: str | None = None
    markdown: str | None = None
    html: str | None = None
    error: str | None = None


def _validate_date(s: str) -> str:
    _dt.date.fromisoformat(s)  # raises ValueError on a bad date
    return s


def export_range(
    from_date: str,
    to_date: str,
    *,
    redaction: str = "summary",
    now: _dt.datetime | None = None,
    write: bool = True,
    state_path: Path | None = None,
    active_path: Path | None = None,
) -> ExportResult:
    """Build (and optionally write) the date-ranged markdown + self-contained HTML export."""
    now = now or _dt.datetime.now(_dt.UTC)
    redaction = _coerce_redaction(redaction)
    try:
        _validate_date(from_date)
        _validate_date(to_date)
    except ValueError as exc:
        return ExportResult(ok=False, redaction=redaction, from_date=from_date, to_date=to_date,
                            error=f"bad date: {exc}")

    data = collect(from_date, to_date, redaction=redaction, now=now,
                   state_path=state_path, active_path=active_path)
    md = render_markdown(data)
    doc = render_html(data)

    md_path = html_path = None
    if write:
        d = config.exports_dir()
        d.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(d, 0o700)
        except OSError:
            pass
        # Filenames carry the date range ONLY — never clinical content (council D6 rider 2).
        base = f"dr-alex-{from_date}_{to_date}-{redaction}"
        mp = d / f"{base}.md"
        hp = d / f"{base}.html"
        mp.write_text(md, encoding="utf-8")
        hp.write_text(doc, encoding="utf-8")
        for f in (mp, hp):
            try:
                os.chmod(f, 0o600)
            except OSError:
                pass
        md_path, html_path = str(mp), str(hp)

    return ExportResult(
        ok=True, redaction=redaction, from_date=from_date, to_date=to_date,
        markdown_path=md_path, html_path=html_path, markdown=md, html=doc,
    )


def review(
    *, days: int = 30, redaction: str = "summary", now: _dt.datetime | None = None,
    write: bool = True,
) -> ExportResult:
    """``dr-alex review`` — a default last-``days`` export ready for print-to-PDF."""
    now = now or _dt.datetime.now(_dt.UTC)
    to_date = now.astimezone(_dt.UTC).strftime("%Y-%m-%d")
    from_date = (now.astimezone(_dt.UTC) - _dt.timedelta(days=days)).strftime("%Y-%m-%d")
    return export_range(from_date, to_date, redaction=redaction, now=now, write=write)
