"""Render the status dict (``voltcast.status``) as one self-contained HTML page.

No external assets: inline CSS, inline SVG plots, and a short script that only
adds hover and keyboard read-outs. Every value a read-out shows is also in a
table, so the page reads fine without JavaScript.

The plots stretch to their box (``preserveAspectRatio="none"``) with
non-scaling strokes, and all text sits in HTML around them, so labels stay
legible at phone width instead of shrinking with the SVG.
"""

from __future__ import annotations

import html
import json
import math
from datetime import date
from pathlib import Path

from voltcast.calendar import BERLIN, parse_iso
from voltcast.models import MODELS

REPO_URL = "https://github.com/dhamsey3/voltcast"

# Colour follows the entity across the whole page: the cleared price is always
# slot 1 and each model keeps its slot whatever its role. Give a new model the
# next free slot here; never renumber, or readers' colour memory breaks.
SLOTS = {"actual": 1, "naive_1d": 2, "seasonal_naive_7d": 3}
MAX_SLOT = 8


def _slot(key: str) -> int:
    if key in SLOTS:
        return SLOTS[key]
    extra = [name for name in MODELS if name not in SLOTS]
    return min(max(SLOTS.values()) + 1 + (extra.index(key) if key in extra else len(extra)), MAX_SLOT)


# --- formatting -----------------------------------------------------------


def _e(text: object) -> str:
    return html.escape(str(text), quote=True)


def _num(value: float | None, digits: int = 2) -> str:
    return "–" if value is None else f"{value:,.{digits}f}".replace("-", "−")


def _money(value: float | None) -> str:
    return "–" if value is None else f"${value:,.2f}"


def _day(iso_day: str, *, weekday: bool = True) -> str:
    d = date.fromisoformat(iso_day)
    return f"{d:%a} {d.day} {d:%b %Y}" if weekday else f"{d.day} {d:%b %Y}"


def _short_day(iso_day: str) -> str:
    d = date.fromisoformat(iso_day)
    return f"{d:%a} {d.day} {d:%b}"


def _when(ts: str) -> str:
    local = parse_iso(ts).astimezone(BERLIN)
    return f"{local.day} {local:%b}, {local:%H:%M %Z}"


def _clock(ts: str) -> str:
    return f"{parse_iso(ts).astimezone(BERLIN):%H:%M}"


def _month(ym: str) -> str:
    return f"{date.fromisoformat(ym + '-01'):%B %Y}"


# --- charts ---------------------------------------------------------------


def _nice_ticks(lo: float, hi: float, max_ticks: int = 7) -> list[float]:
    """Round-numbered ticks covering lo..hi: the finest 1/2/2.5/5 step that
    needs no more than ``max_ticks``, so the plot wastes little range."""
    if math.isclose(lo, hi):
        lo, hi = lo - 1, hi + 1
    magnitude = 10 ** math.floor(math.log10((hi - lo) / max_ticks))
    for step in (m * magnitude * scale for scale in (1, 10, 100) for m in (1, 2, 2.5, 5)):
        start, end = math.floor(lo / step) * step, math.ceil(hi / step) * step
        if round((end - start) / step) + 1 <= max_ticks:
            return [round(start + i * step, 6) for i in range(round((end - start) / step) + 1)]
    raise AssertionError("unreachable: a 100x step always fits")


def _chart(
    chart_id: str,
    *,
    title: str,
    note: str,
    x_labels: list[str],
    x_ticks: list[tuple[int, str]],
    x_header: str,
    series: list[dict],
    step: bool,
    from_zero: bool = False,
    unit: str = "EUR/MWh",
) -> str:
    """A line chart: ``step`` holds each value across its slot (quarter-hour
    prices); otherwise values are points at slot centres (daily errors)."""
    n = len(x_labels)
    values = [v for s in series for v in s["values"] if v is not None]
    lo, hi = min(values), max(values)
    ticks = _nice_ticks(min(lo, 0) if from_zero else lo, hi)
    t0, t1 = ticks[0], ticks[-1]

    def y(v: float) -> float:
        return round(1000 - (v - t0) / (t1 - t0) * 1000, 2)

    def x(i: int) -> float:
        return i if step else i + 0.5

    def top(v: float) -> str:
        return f"{y(v) / 10:.2f}%"

    def left(i: float) -> str:
        return f"{i / n * 100:.3f}%"

    svg = []
    for t in ticks:
        cls = "axis" if t == t0 else ("zero" if t == 0 else "grid")
        svg.append(f'<line class="{cls}" x1="0" x2="{n}" y1="{y(t)}" y2="{y(t)}"/>')
    for s in series:
        path, pen_down = [], False
        for i, v in enumerate(s["values"]):
            if v is None:
                pen_down = False
                continue
            if step:
                path.append(f"{'V' if pen_down else f'M{i}'} {y(v)} H{i + 1}")
            else:
                path.append(f"{'L' if pen_down else 'M'}{x(i)} {y(v)}")
            pen_down = True
        svg.append(f'<path class="line s{s["slot"]}" d="{" ".join(path)}"/>')
        if not step:
            for i, v in enumerate(s["values"]):
                if v is not None:
                    dot = f"M{x(i)} {y(v)}h0"
                    svg.append(f'<path class="ring" d="{dot}"/><path class="dot s{s["slot"]}" d="{dot}"/>')

    y_labels = "".join(f'<span class="ylab" style="top:{top(t)}">{_num(t, 0)}</span>' for t in ticks)
    # Every other inner tick is "minor": a narrow chart hides those (CSS) so
    # the remaining labels never overlap.
    x_labels_html = "".join(
        f'<span class="xlab{" minor" if 0 < k < len(x_ticks) - 1 and k % 2 else ""}"'
        f' style="left:{left(x(i) if not step else i)}">{_e(label)}</span>'
        for k, (i, label) in enumerate(x_ticks)
    )

    # Direct labels at the line ends, unless two would collide: then the
    # legend and the read-out carry identity instead of nudged labels.
    ends, taken = [], []
    for s in series:
        last = next((v for v in reversed(s["values"]) if v is not None), None)
        if last is None or any(abs(y(last) - other) < 90 for other in taken):
            continue
        taken.append(y(last))
        ends.append(f'<span class="end" style="top:{top(last)}">{_e(s["short"])} {_num(last)}</span>')

    legend = ""
    if len(series) > 1:
        legend = '<ul class="legend">' + "".join(
            f'<li><span class="key s{s["slot"]}"></span>{_e(s["name"])}</li>' for s in series
        )
        legend += "</ul>"

    head = "".join(f"<th>{_e(s['name'])}</th>" for s in series)
    rows = "".join(
        f"<tr><th>{_e(label)}</th>" + "".join(f"<td>{_num(s['values'][i])}</td>" for s in series) + "</tr>"
        for i, label in enumerate(x_labels)
    )
    data = {"x": x_labels, "unit": unit, "series": [{k: s[k] for k in ("name", "slot", "values")} for s in series]}

    return f"""
<figure class="chart" id="{chart_id}">
  <figcaption><h3>{_e(title)}</h3><p class="note">{note}</p></figcaption>
  {legend}
  <div class="frame">
    <div class="plot" tabindex="0" role="img"
         aria-label="{_e(title)}. The table below lists every value; arrow keys step through them here.">
      <svg viewBox="0 0 {n} 1000" preserveAspectRatio="none" aria-hidden="true">{"".join(svg)}</svg>
      {y_labels}{x_labels_html}{"".join(ends)}
      <div class="crosshair" hidden></div>
      <div class="tip" hidden></div>
    </div>
  </div>
  <details class="table-view">
    <summary>Show the numbers</summary>
    <div class="scroll"><table><thead><tr><th>{_e(x_header)}</th>{head}</tr></thead><tbody>{rows}</tbody></table></div>
  </details>
  <script type="application/json" class="chart-data">{json.dumps(data).replace("</", "<\\/")}</script>
</figure>"""


def _price_chart(chart_id: str, title: str, note: str, slots: list[dict], series: list[dict]) -> str:
    times = [parse_iso(s["start"]).astimezone(BERLIN) for s in slots]
    labels = [f"{t:%H:%M}" for t in times]
    ticks = [(i, f"{t:%H:%M}") for i, t in enumerate(times) if t.minute == 0 and t.hour % 6 == 0]
    ticks.append((len(times), "24:00"))
    return _chart(
        chart_id,
        title=title,
        note=note,
        x_labels=labels,
        x_ticks=ticks,
        x_header="Berlin time",
        series=series,
        step=True,
    )


# --- page sections --------------------------------------------------------

ICONS = {
    "good": '<path d="M4.5 8.2 7 10.5l4.5-5"/>',
    "critical": '<path d="M8 4.5v4.2M8 11.2v.3"/>',
    "pending": '<path d="M8 4.8V8l2.2 1.4"/>',
}


def _status(kind: str, label: str) -> str:
    icon = f'<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="7"/>{ICONS[kind]}</svg>'
    return f'<span class="status status-{kind}">{icon}{_e(label)}</span>'


def _tile(label: str, value: str, sub: str, extra: str = "") -> str:
    return (
        f'<div class="tile"><p class="label">{label}</p><p class="value">{value}</p>'
        f'<p class="sub">{sub}</p>{extra}</div>'
    )


def _tiles(status: dict) -> str:
    promise = status["promise"]
    day = _short_day(promise["delivery_date"])
    if promise["state"] == "published":
        first = _tile(
            f"Forecast for {day}",
            _status("good", "Published"),
            f"at {_when(promise['published_at'])}, before the auction",
        )
    elif promise["state"] == "due":
        first = _tile(
            f"Forecast for {day}", _status("pending", "Due"), f"by {_clock(promise['deadline'])} Berlin today"
        )
    else:
        first = _tile(
            f"Forecast for {day}",
            _status("critical", "Missing"),
            f"deadline was {_clock(promise['deadline'])}; on-call has been alerted",
        )

    scored = status["scored"]
    if scored and scored["model"] in scored["scores"]:
        error = scored["scores"][scored["model"]]
        second = _tile(
            f"Error on {_short_day(scored['delivery_date'])}",
            f'{_num(error["mae"])} <span class="unit">EUR/MWh</span>',
            f"mean absolute error of the published forecast ({_e(scored['model'])})",
        )
    else:
        second = _tile("Latest error", "–", "no live day has been scored yet")

    record = status["rolling"]["all_live_days"].get(status["champion"] or "", {})
    if record:
        month = status["rolling"]["last_30_days"].get(status["champion"], {})
        third = _tile(
            "Live record",
            f"{record['days']} {'day' if record['days'] == 1 else 'days'}",
            f"since {_day(status['live_since'], weekday=False)} · 30-day MAE {_num(month.get('mae'))}",
        )
    else:
        third = _tile("Live record", "0 days", "the first live forecast hasn't been scored yet")

    cost = status["cost"]
    if cost:
        share = min(cost["month_to_date"] / cost["limit"], 1) if cost["limit"] else 0
        meter = (
            f'<div class="meter" role="meter" aria-valuemin="0" aria-valuemax="{cost["limit"]}"'
            f' aria-valuenow="{cost["month_to_date"]}" aria-label="Spend against budget">'
            f'<span style="width:{share * 100:.1f}%"></span></div>'
        )
        forecast = f" · forecast {_money(cost['forecast'])}" if cost["forecast"] is not None else ""
        fourth = _tile(
            f"AWS bill, {_month(cost['month']).split()[0]}",
            _money(cost["month_to_date"]),
            f"of a {_money(cost['limit'])} monthly budget{forecast}",
            meter,
        )
    else:
        fourth = _tile("AWS bill", "–", "budget figures appear after AWS's next daily billing update")

    return f'<section class="tiles" aria-label="Service promises">{first}{second}{third}{fourth}</section>'


def _scores_table(scores: dict[str, dict]) -> str:
    rows = "".join(
        f'<tr><th><span class="key s{_slot(model)}"></span><code>{_e(model)}</code></th><td class="text">'
        f"{_e(s['role'])}</td><td>{_num(s['mae'])}</td><td>{_num(s['rmse'])}</td><td>{_num(s['bias'])}</td></tr>"
        for model, s in scores.items()
    )
    return (
        '<div class="scroll"><table class="scores"><thead><tr><th>Model</th><th class="text">Role</th>'
        f"<th>MAE</th><th>RMSE</th><th>Bias</th></tr></thead><tbody>{rows}</tbody></table></div>"
    )


def _scored_section(status: dict) -> str:
    scored = status["scored"]
    if not scored:
        return (
            '<section><h2>How the last forecast did</h2><p class="empty">No live day has been scored yet.</p></section>'
        )
    model = scored["model"]
    series = [
        {
            "name": "Cleared price",
            "short": "Cleared",
            "slot": 1,
            "values": [s["actual"] for s in scored["slots"]],
        }
    ]
    if model:
        series.append(
            {
                "name": f"Forecast ({model})",
                "short": "Forecast",
                "slot": _slot(model),
                "values": [s["forecast"] for s in scored["slots"]],
            }
        )
    day = _day(scored["delivery_date"])
    chart = _price_chart(
        "scored",
        f"{day}: published forecast against the cleared price",
        "Quarter-hour prices in EUR/MWh, Berlin time. Challengers ran in shadow; their errors are in the table.",
        scored["slots"],
        series,
    )
    return (
        f"<section><h2>How the last forecast did</h2>{chart}"
        f'<h3 class="table-title">Errors on {_e(day)} (EUR/MWh)</h3>{_scores_table(scored["scores"])}</section>'
    )


def _upcoming_section(status: dict) -> str:
    upcoming = status["upcoming"]
    if not upcoming:
        return ""
    series = [
        {
            "name": f"Forecast ({upcoming['model']})",
            "short": "Forecast",
            "slot": _slot(upcoming["model"]),
            "values": [s["price"] for s in upcoming["slots"]],
        }
    ]
    day = _day(upcoming["delivery_date"])
    chart = _price_chart(
        "upcoming",
        f"{day}: forecast from {upcoming['model']}",
        f"Published {_e(_when(upcoming['as_of']))}. Scored against the cleared prices the afternoon before delivery.",
        upcoming["slots"],
        series,
    )
    return f"<section><h2>The next forecast</h2>{chart}</section>"


def _record_section(status: dict) -> str:
    rolling = status["rolling"]
    if not rolling["all_live_days"]:
        return ""
    names = {"last_7_days": "Last 7 days", "last_30_days": "Last 30 days", "all_live_days": "Since going live"}

    def days(by_model: dict) -> dict:
        return {model: r["days"] for model, r in by_model.items()}

    # A window that covers the same days as the next longer one only repeats
    # it (early on, all three do), so show the longer one alone.
    windows = list(rolling.items())
    shown = [(w, m) for i, (w, m) in enumerate(windows) if i == len(windows) - 1 or days(m) != days(windows[i + 1][1])]
    rows = []
    for window, by_model in shown:
        for i, (model, r) in enumerate(by_model.items()):
            first = f'<th rowspan="{len(by_model)}" class="text">{names[window]}</th>' if i == 0 else ""
            rows.append(
                f'<tr>{first}<td class="text"><span class="key s{_slot(model)}"></span><code>{_e(model)}</code></td>'
                f"<td>{r['days']}</td><td>{_num(r['mae'])}</td><td>{_num(r['rmse'])}</td><td>{_num(r['bias'])}</td></tr>"
            )
    table = (
        '<div class="scroll"><table class="record"><thead><tr><th class="text">Window</th><th class="text">Model</th>'
        f"<th>Days</th><th>MAE</th><th>RMSE</th><th>Bias</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
    )

    trend = status["trend"]
    chart = ""
    if len(trend) >= 2:
        models = sorted({m for t in trend for m in t["mae"]}, key=_slot)
        chart = _chart(
            "trend",
            title=f"Daily mean absolute error, last {len(trend)} live days",
            note="EUR/MWh; lower is better. Every model is scored every day, published or not.",
            x_labels=[_short_day(t["delivery_date"]) for t in trend],
            x_ticks=[
                (i, _short_day(t["delivery_date"]))
                for i, t in enumerate(trend)
                if i in (0, len(trend) - 1) or (len(trend) > 6 and i == len(trend) // 2)
            ],
            x_header="Delivery day",
            series=[
                {"name": m, "short": m, "slot": _slot(m), "values": [t["mae"].get(m) for t in trend]} for m in models
            ],
            step=False,
            from_zero=True,
        )
    note = (
        '<p class="note">Averages of daily errors over live forecasts only. The year-long replay that set the bar'
        f' is in the <a href="{REPO_URL}#models-champion-and-challengers">README</a>.</p>'
    )
    return f"<section><h2>Track record</h2>{chart}{table}{note}</section>"


def _model_section(status: dict) -> str:
    model = status["model"]
    if not model:
        return ""
    challengers = sorted(m for m in (status["scored"] or {}).get("scores", {}) if m != model["model"])
    desc = MODELS[model["model"]].description if model["model"] in MODELS else ""
    inputs = "".join(
        f'<li><code>{_e(i["key"])}</code> <span class="hash">sha256 {_e(i["sha256"][:12])}…</span></li>'
        for i in model["inputs"]
    )
    code = _e(model["code_version"])
    chall = ", ".join(f"<code>{_e(c)}</code>" for c in challengers) or "none"
    return f"""
<section><h2>What's running</h2>
<dl class="facts">
  <div><dt>Published model</dt>
    <dd><code>{_e(model["model"])}</code> v{_e(model["model_version"])} · {_e(desc)}</dd></div>
  <div><dt>In shadow</dt><dd>{chall}</dd></div>
  <div><dt>Code</dt><dd><a href="{REPO_URL}/commit/{code}"><code>{code}</code></a></dd></div>
  <div><dt>Latest forecast made</dt><dd>{_e(_when(model["as_of"]))} for {_e(_day(model["delivery_date"]))}</dd></div>
</dl>
<details class="lineage"><summary>Inputs it read ({len(model["inputs"])})</summary><ul>{inputs}</ul></details>
</section>"""


def _cost_section(status: dict) -> str:
    cost = status["cost"]
    if not cost:
        return ""
    rows = "".join(
        f'<tr><th class="text">{_month(m["month"])}{" (so far)" if m["month"] == cost["month"] else ""}</th>'
        f"<td>{_money(m['actual'])}</td></tr>"
        for m in reversed(cost["months"])
    )
    return f"""
<section><h2>What it costs</h2>
<div class="scroll"><table class="bill"><thead><tr><th class="text">Month</th><th>AWS bill (USD)</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<p class="note">The whole AWS account, which runs only voltcast, against a {_money(cost["limit"])} monthly budget.
The <code>{_e(cost["budget"])}</code> budget in AWS Budgets also emails on-call if actual or forecast spend
passes the limit. Figures update once a day.</p>
</section>"""


def write_site(status: dict, out: Path) -> list[Path]:
    """The deployable site: the page plus the data it was built from."""
    out.mkdir(parents=True, exist_ok=True)
    files = {out / "index.html": render(status), out / "status.json": json.dumps(status, indent=1) + "\n"}
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    return list(files)


def render(status: dict) -> str:
    body = "".join(
        [
            _tiles(status),
            _scored_section(status),
            _upcoming_section(status),
            _record_section(status),
            _model_section(status),
            _cost_section(status),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>voltcast status</title>
<meta name="description" content="Live day-ahead electricity price forecasts for Germany/Luxembourg, graded every day.">
<style>{CSS}</style>
</head>
<body>
<main>
<header class="top">
  <p class="eyebrow">voltcast · service status</p>
  <h1>Tomorrow's German power prices, forecast and graded every day</h1>
  <p class="lede">Each morning voltcast publishes a price for every quarter-hour of tomorrow's {_e(status["region"])}
  day-ahead auction, before bidding closes at 12:00. That afternoon it scores itself against the prices that cleared.
  This page is rebuilt from the service's own records whenever a run finishes.</p>
  <p class="meta">Updated {_e(_when(status["generated_at"]))} · <a href="status.json">status.json</a> ·
  <a href="{REPO_URL}">Source and design</a></p>
</header>
{body}
<footer>
  <p>Prices: {_e(status["source"])}. Forecasts are an experiment, not trading advice.</p>
  <p><a href="{REPO_URL}/blob/main/docs/runbook.md">Runbook</a> ·
  <a href="{REPO_URL}/tree/main/docs/adr">Design decisions</a> · <a href="{REPO_URL}">GitHub</a></p>
</footer>
</main>
<script>{SCRIPT}</script>
</body>
</html>
"""


CSS = """
:root {
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e; --muted: #6f6d68;
  --grid: #e1e0d9; --axis: #c3c2b7; --border: rgba(11,11,11,0.10); --link: #1c5cab;
  --s1: #2a78d6; --s2: #eb6834; --s3: #1baf7a; --s4: #eda100;
  --s5: #e87ba4; --s6: #008300; --s7: #6250d6; --s8: #e34948;
  --good: #0ca30c; --critical: #d03b3b; --pending: #898781; --meter: #2a78d6; --meter-track: #cde2fb;
}
@media (prefers-color-scheme: dark) {
  :root {
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #f0efec; --ink-2: #c3c2b7; --muted: #a3a29b;
    --grid: #2c2c2a; --axis: #383835; --border: rgba(255,255,255,0.10); --link: #86b6ef;
    --s1: #3987e5; --s2: #d95926; --s3: #199e70; --s4: #c98500;
    --s5: #d55181; --s6: #008300; --s7: #9085e9; --s8: #e66767;
    --meter: #3987e5; --meter-track: #184f95;
  }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--ink);
  font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 960px; margin: 0 auto; padding: 32px 16px 48px; }
a { color: var(--link); }
code { font: 0.9em ui-monospace, SFMono-Regular, Menlo, monospace; }
h1 { font-size: clamp(1.6rem, 4vw, 2.2rem); line-height: 1.2; margin: 4px 0 12px; letter-spacing: -0.01em; }
h2 { font-size: 1.25rem; margin: 0 0 16px; }
h3 { font-size: 1rem; margin: 0; }
.eyebrow { margin: 0; color: var(--ink-2); font-size: 0.875rem; letter-spacing: 0.02em; }
.lede { max-width: 68ch; color: var(--ink-2); margin: 0 0 8px; }
.meta, .note, .empty { color: var(--ink-2); font-size: 0.875rem; }
.note { margin: 4px 0 0; }
section { background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 20px; margin-top: 16px; }
.tiles { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  background: none; border: 0; padding: 0; }
.tile { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; }
.tile .label { margin: 0; color: var(--ink-2); font-size: 0.875rem; }
.tile .value { margin: 4px 0 2px; font-size: 1.6rem; font-weight: 600; line-height: 1.25; }
.tile .unit { font-size: 0.875rem; font-weight: 400; color: var(--ink-2); }
.tile .sub { margin: 0; color: var(--ink-2); font-size: 0.8125rem; }
.status { display: inline-flex; align-items: center; gap: 8px; }
.status svg { width: 22px; height: 22px; fill: none; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
.status circle { stroke: none; }
.status-good circle { fill: var(--good); } .status-critical circle { fill: var(--critical); }
.status-pending circle { fill: none; stroke: var(--pending); stroke-width: 1.4; }
.status-good path, .status-critical path { stroke: #fff; } .status-pending path { stroke: var(--pending); }
.meter { margin-top: 10px; height: 6px; border-radius: 3px; background: var(--meter-track); overflow: hidden; }
.meter span { display: block; height: 100%; min-width: 3px; border-radius: 3px; background: var(--meter); }
.chart { margin: 0; container-type: inline-size; }
.chart figcaption { margin-bottom: 8px; }
.legend { list-style: none; display: flex; flex-wrap: wrap; gap: 4px 16px; margin: 0 0 8px; padding: 0;
  font-size: 0.875rem; color: var(--ink-2); }
.legend li { display: inline-flex; align-items: center; gap: 6px; }
.key { display: inline-block; width: 14px; height: 2px; border-radius: 1px; vertical-align: middle; margin-right: 6px; }
.legend .key { margin: 0; }
.frame { padding: 8px 88px 30px 44px; }
.plot { position: relative; height: 220px; outline: none; }
.plot:focus-visible { box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--link); border-radius: 2px; }
.plot svg { position: absolute; inset: 0; width: 100%; height: 100%; overflow: visible; }
.plot line, .plot path { vector-effect: non-scaling-stroke; fill: none; }
.plot .grid { stroke: var(--grid); stroke-width: 1; }
.plot .axis, .plot .zero { stroke: var(--axis); stroke-width: 1; }
.plot .line { stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.plot .ring { stroke: var(--surface); stroke-width: 12; stroke-linecap: round; }
.plot .dot { stroke-width: 8; stroke-linecap: round; }
.ylab, .xlab, .end { position: absolute; font-size: 0.75rem; color: var(--muted); white-space: nowrap;
  font-variant-numeric: tabular-nums; }
.ylab { right: 100%; margin-right: 8px; transform: translateY(-50%); }
.xlab { top: 100%; margin-top: 8px; transform: translateX(-50%); }
.end { left: 100%; margin-left: 8px; transform: translateY(-50%); color: var(--ink-2); }
.crosshair { position: absolute; top: 0; bottom: 0; width: 1px; background: var(--axis); pointer-events: none; }
.tip { position: absolute; top: 0; z-index: 2; min-width: 150px; padding: 8px 10px; border-radius: 8px;
  background: var(--surface); border: 1px solid var(--border); box-shadow: 0 4px 16px rgba(0,0,0,0.12);
  font-size: 0.8125rem; pointer-events: none; max-width: 100cqw; }
.tip-head { color: var(--ink-2); margin-bottom: 4px; }
.tip-row { display: flex; align-items: center; gap: 8px; white-space: nowrap; }
.tip-row strong { font-variant-numeric: tabular-nums; }
.tip-name { color: var(--ink-2); min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.s1 { stroke: var(--s1); } .s2 { stroke: var(--s2); } .s3 { stroke: var(--s3); } .s4 { stroke: var(--s4); }
.s5 { stroke: var(--s5); } .s6 { stroke: var(--s6); } .s7 { stroke: var(--s7); } .s8 { stroke: var(--s8); }
.key.s1 { background: var(--s1); } .key.s2 { background: var(--s2); } .key.s3 { background: var(--s3); }
.key.s4 { background: var(--s4); } .key.s5 { background: var(--s5); } .key.s6 { background: var(--s6); }
.key.s7 { background: var(--s7); } .key.s8 { background: var(--s8); }
.table-view { margin-top: 8px; font-size: 0.875rem; }
.table-view summary, .lineage summary { cursor: pointer; color: var(--link); }
.table-view .scroll { max-height: 320px; overflow: auto; margin-top: 8px; }
.scroll { overflow-x: auto; }
.table-title { margin: 20px 0 8px; }
table { border-collapse: collapse; width: 100%; font-size: 0.875rem; font-variant-numeric: tabular-nums; }
th, td { padding: 6px 10px; text-align: right; border-bottom: 1px solid var(--grid); white-space: nowrap; }
thead th { color: var(--ink-2); font-weight: 500; position: sticky; top: 0; background: var(--surface); }
tbody th { font-weight: 400; text-align: left; }
th:first-child { text-align: left; }
.text { text-align: left; }
.record tbody th { vertical-align: top; }
.facts { display: grid; gap: 12px; margin: 0; }
.facts div { display: grid; grid-template-columns: minmax(120px, 180px) 1fr; gap: 12px; }
.facts dt { color: var(--ink-2); }
.facts dd { margin: 0; }
.lineage { margin-top: 12px; font-size: 0.875rem; }
.lineage ul { padding-left: 18px; }
.hash { color: var(--muted); }
footer { margin-top: 24px; color: var(--ink-2); font-size: 0.8125rem; }
footer p { margin: 4px 0; }
@media (max-width: 560px) {
  section { padding: 16px; }
  .facts div { grid-template-columns: 1fr; gap: 0; }
}
/* Sized by each chart's own width, not the screen's. On phones the end
   labels go (the legend and read-out still name every line) and the plot
   takes their room; on very narrow charts every other x label goes too. */
@container (max-width: 480px) {
  .frame { padding-right: 12px; }
  .end { display: none; }
}
@container (max-width: 300px) {
  .xlab.minor { display: none; }
}
@media (forced-colors: active) {
  .plot .line, .plot .dot { stroke: CanvasText; }
}
"""

SCRIPT = """
(() => {
  const fmt = new Intl.NumberFormat("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  document.querySelectorAll("figure.chart").forEach((fig) => {
    const data = JSON.parse(fig.querySelector(".chart-data").textContent);
    const plot = fig.querySelector(".plot");
    const frame = fig.querySelector(".frame");
    const line = fig.querySelector(".crosshair");
    const tip = fig.querySelector(".tip");
    const n = data.x.length;
    let current = -1;
    const pos = (i) => ((i + 0.5) / n) * 100;

    function show(i) {
      current = Math.max(0, Math.min(n - 1, i));
      const x = pos(current);
      line.hidden = false;
      tip.hidden = false;
      line.style.left = x + "%";
      const head = document.createElement("div");
      head.className = "tip-head";
      head.textContent = data.x[current];
      const rows = data.series.map((s) => {
        const row = document.createElement("div");
        row.className = "tip-row";
        const key = document.createElement("span");
        key.className = "key s" + s.slot;
        const value = document.createElement("strong");
        const v = s.values[current];
        value.textContent = v == null ? "–" : fmt.format(v).replace("-", "\\u2212") + " " + data.unit;
        const name = document.createElement("span");
        name.className = "tip-name";
        name.textContent = s.name;
        row.append(key, value, name);
        return row;
      });
      tip.replaceChildren(head, ...rows);
      // Beside the crosshair, on whichever side fits, and never past the
      // chart's frame: on a phone the read-out can be wider than the plot.
      const pr = plot.getBoundingClientRect();
      const fr = frame.getBoundingClientRect();
      const at = (x / 100) * pr.width;
      const w = tip.offsetWidth;
      let left = at + 12 + w <= fr.right - pr.left ? at + 12 : at - 12 - w;
      left = Math.max(fr.left - pr.left, Math.min(left, fr.right - pr.left - w));
      tip.style.left = left + "px";
    }
    function hide() {
      line.hidden = true;
      tip.hidden = true;
    }
    plot.addEventListener("pointermove", (e) => {
      const r = plot.getBoundingClientRect();
      show(Math.floor(((e.clientX - r.left) / r.width) * n));
    });
    plot.addEventListener("pointerleave", () => {
      if (document.activeElement !== plot) hide();
    });
    plot.addEventListener("focus", () => show(current < 0 ? n - 1 : current));
    plot.addEventListener("blur", hide);
    plot.addEventListener("keydown", (e) => {
      if (e.key === "ArrowLeft" || e.key === "ArrowRight") {
        e.preventDefault();
        show(current + (e.key === "ArrowLeft" ? -1 : 1));
      } else if (e.key === "Escape") {
        hide();
      }
    });
  });
})();
"""
