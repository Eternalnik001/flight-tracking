"""Render the HTML matrix email and send it via Resend.

Email HTML is deliberately old-school: tables + inline styles + web-safe fonts,
because mail clients ignore most modern CSS.
"""
from __future__ import annotations

import httpx
from jinja2 import Template

from . import config

RESEND_URL = "https://api.resend.com/emails"


def rupees(value: float | None) -> str:
    if value is None:
        return "&mdash;"
    return "&#8377;" + f"{round(value):,}"


def _arrow(delta: float | None, delta_pct: float | None) -> str:
    if delta is None or delta_pct is None or abs(delta_pct) < 0.005:
        return ""
    if delta < 0:
        return f'<span style="color:#0a7d2c;">&#9660; {abs(delta_pct)*100:.0f}%</span>'
    return f'<span style="color:#b00020;">&#9650; {delta_pct*100:.0f}%</span>'


_TEMPLATE = Template(
    """
<div style="font-family:Arial,Helvetica,sans-serif;color:#1a1a1a;max-width:880px;margin:0 auto;">
  <h2 style="margin:0 0 4px;">{{ origin }} &rarr; domestic &mdash; November price matrix</h2>
  <p style="margin:0 0 16px;color:#666;font-size:13px;">
    Generated {{ run_at }} &middot; {{ nights }}-night stays &middot; cached scan with
    {{ live_done }} live confirmation{{ '' if live_done == 1 else 's' }}
    ({{ candidate_count }} candidate{{ '' if candidate_count == 1 else 's' }} flagged)
  </p>

  <h3 style="margin:18px 0 6px;">Summary &mdash; cheapest option per route</h3>
  <table cellpadding="8" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:13px;">
    <tr style="background:#f2f4f7;text-align:left;">
      <th style="border:1px solid #dde1e6;">Route</th>
      <th style="border:1px solid #dde1e6;">Best dates</th>
      <th style="border:1px solid #dde1e6;">Strategy</th>
      <th style="border:1px solid #dde1e6;">Price</th>
      <th style="border:1px solid #dde1e6;">Change</th>
    </tr>
    {% for s in summary %}
    <tr>
      <td style="border:1px solid #dde1e6;font-weight:bold;">{{ origin }}&ndash;{{ s.dest }}</td>
      <td style="border:1px solid #dde1e6;">{{ s.dates or '&mdash;' }}</td>
      <td style="border:1px solid #dde1e6;">{{ s.strategy or '&mdash;' }}</td>
      <td style="border:1px solid #dde1e6;font-weight:bold;">{{ s.price }}</td>
      <td style="border:1px solid #dde1e6;">{{ s.arrow }}</td>
    </tr>
    {% endfor %}
  </table>

  {% for block in blocks %}
  <h3 style="margin:26px 0 6px;">{{ origin }} &rarr; {{ block.dest }}</h3>
  {% if block.rows_html %}
  <table cellpadding="6" cellspacing="0" style="border-collapse:collapse;width:100%;font-size:12px;">
    <tr style="background:#f2f4f7;text-align:left;">
      <th style="border:1px solid #dde1e6;">Depart</th>
      <th style="border:1px solid #dde1e6;">Return</th>
      <th style="border:1px solid #dde1e6;">Outbound</th>
      <th style="border:1px solid #dde1e6;">Return leg</th>
      <th style="border:1px solid #dde1e6;">2&times;one-way</th>
      <th style="border:1px solid #dde1e6;">Round-trip</th>
      <th style="border:1px solid #dde1e6;">Cheapest</th>
      <th style="border:1px solid #dde1e6;">Change</th>
      <th style="border:1px solid #dde1e6;">Live</th>
    </tr>
    {{ block.rows_html }}
  </table>
  {% else %}
  <p style="color:#999;font-size:12px;margin:0;">No cached prices returned for this route.</p>
  {% endif %}
  {% endfor %}

  <p style="color:#999;font-size:11px;margin-top:24px;">
    Cached figures are indicative (Aviasales cache). "Live" cells are confirmed against
    Google Flights at generation time.
  </p>
</div>
"""
)


def _row_html(r: dict, is_best: bool) -> str:
    bg = "background:#eafaf0;" if is_best else ""
    live = ""
    if r["live"] and r["live"].get("price") is not None:
        lvl = r["live"].get("price_level") or ""
        live = f'{rupees(r["live"]["price"])} <span style="color:#888;">{lvl}</span>'
    cheapest_cell = rupees(r["best_price"])
    if r["best_strategy"]:
        cheapest_cell += f' <span style="color:#888;">({r["best_strategy"]})</span>'
    cells = [
        r["depart"], r["return"], rupees(r["outbound"]), rupees(r["return_leg"]),
        rupees(r["split"]), rupees(r["roundtrip"]), cheapest_cell,
        _arrow(r["delta"], r["delta_pct"]), live or "&mdash;",
    ]
    tds = "".join(f'<td style="border:1px solid #dde1e6;{bg}">{c}</td>' for c in cells)
    return f"<tr>{tds}</tr>"


def render(matrices: dict[str, list[dict]], run_at: str, live_done: int, candidate_count: int) -> str:
    summary, blocks = [], []
    for dest, rows in matrices.items():
        priced = [r for r in rows if r["best_price"] is not None]
        best = min(priced, key=lambda r: r["best_price"]) if priced else None
        summary.append(
            {
                "dest": dest,
                "dates": f'{best["depart"]} &rarr; {best["return"]}' if best else "",
                "strategy": best["best_strategy"] if best else "",
                "price": rupees(best["best_price"]) if best else "&mdash;",
                "arrow": _arrow(best["delta"], best["delta_pct"]) if best else "",
            }
        )
        best_id = id(best) if best else None
        rows_html = "".join(_row_html(r, is_best=(id(r) == best_id)) for r in rows)
        blocks.append({"dest": dest, "rows_html": rows_html if priced else ""})

    return _TEMPLATE.render(
        origin=config.ORIGIN,
        nights=config.NIGHTS,
        run_at=run_at,
        live_done=live_done,
        candidate_count=candidate_count,
        summary=summary,
        blocks=blocks,
    )


def send(html: str, subject: str) -> None:
    if not (config.RESEND_API_KEY and config.EMAIL_TO):
        print("[email] RESEND_API_KEY or EMAIL_TO not set – skipping send.")
        return
    resp = httpx.post(
        RESEND_URL,
        headers={"Authorization": f"Bearer {config.RESEND_API_KEY}"},
        json={"from": config.EMAIL_FROM, "to": config.EMAIL_TO, "subject": subject, "html": html},
        timeout=30,
    )
    resp.raise_for_status()
    print(f"[email] sent to {', '.join(config.EMAIL_TO)}")
