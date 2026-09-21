#!/usr/bin/env python3
"""Build a one-page site from a sandbox_signals.py CSV.

Usage: python3 build_page.py [--csv examples/sample-run.csv] [--out site/index.html]
Standard library only. Every row links to the job post or line of code behind it.
"""
import argparse, csv, glob, html, json, os

HERE = os.path.dirname(os.path.abspath(__file__))

LABELS = {
    "competitor_sdk": ("Uses E2B / Daytona", "sdk"),
    "competitor_sdk_example": ("E2B / Daytona in examples", "sdk"),
    "sandbox_job": ("Hiring for sandboxes", "job"),
    "ai_agent": ("AI-agent product", "agent"),
    "recent_hiring": ("Hiring now", "hire"),
}


def latest_csv():
    runs = sorted(glob.glob(os.path.join(HERE, "output", "signals-*.csv")))
    return runs[-1] if runs else os.path.join(HERE, "examples", "sample-run.csv")


def host(url):
    u = url.split("//", 1)[-1]
    return u.split("/", 1)[0].replace("www.", "")


def row_html(i, r):
    tags = "".join(
        f'<span class="tag t-{LABELS[s][1]}">{LABELS[s][0]}</span>'
        for s in r["signals"].split(";") if s in LABELS)
    why = "".join(f"<li>{html.escape(w.strip())}</li>" for w in r["why"].split("|") if w.strip())
    ev = html.escape(r["evidence_url"])
    more = [u for u in r.get("more_evidence", "").split() if u.startswith("http")][:2]
    more_html = "".join(f' <a href="{html.escape(u)}" target="_blank" rel="noopener">more</a>' for u in more)
    site = r.get("website", "").strip()
    name = html.escape(r["company"])
    name_html = (f'<a href="{html.escape(site)}" target="_blank" rel="noopener">{name}</a>'
                 if site.startswith("http") else name)
    score = int(r["score"])
    return f"""
<article class="row" data-signals="{html.escape(r['signals'])}" data-name="{name.lower()}">
  <div class="rank">{i}</div>
  <div class="main">
    <h3>{name_html}</h3>
    <div class="tags">{tags}</div>
    <ul class="why">{why}</ul>
    <p class="ev">Evidence: <a href="{ev}" target="_blank" rel="noopener">{html.escape(host(r['evidence_url']))}</a>{more_html}</p>
  </div>
  <div class="score"><span>{score}</span><small>points</small></div>
</article>"""


def build(rows, run_date):
    n = len(rows)
    counts = {k: sum(1 for r in rows if k in r["signals"].split(";")) for k in ("competitor_sdk", "sandbox_job")}
    body = "".join(row_html(i + 1, r) for i, r in enumerate(rows))
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sandbox Intent Signals</title>
<meta name="description" content="Companies that likely need fast sandboxes for AI agents, found from public job posts and code.">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'><rect width='32' height='32' rx='7' fill='%232f5bd3'/><path d='M9 21l5-10 4 7 2-3 3 6' stroke='white' stroke-width='2.4' fill='none' stroke-linecap='round' stroke-linejoin='round'/></svg>">
<style>
:root {{
  --bg:#f7f7f5; --card:#fff; --ink:#1b1c1f; --muted:#62656d; --line:#e4e4e0;
  --accent:#2f5bd3; --sdk:#b4381f; --sdk-bg:#fbe9e4; --job:#1f6b45; --job-bg:#e3f3ea;
  --agent:#5a3fb0; --agent-bg:#eee9fb; --hire:#6b5a12; --hire-bg:#f6f0d6;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    --bg:#131417; --card:#1c1d21; --ink:#ececea; --muted:#a2a5ad; --line:#2d2f35;
    --accent:#7d9cff; --sdk:#ff9b84; --sdk-bg:#3a211b; --job:#7fd6a6; --job-bg:#17302a;
    --agent:#bba6ff; --agent-bg:#2a2340; --hire:#e6cf73; --hire-bg:#332c12;
  }}
}}
* {{ box-sizing:border-box }}
body {{ margin:0; background:var(--bg); color:var(--ink);
  font:16px/1.55 ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
a {{ color:var(--accent) }}
.wrap {{ max-width:880px; margin:0 auto; padding:40px 16px 64px }}
header h1 {{ font-size:30px; line-height:1.2; margin:0 0 12px; letter-spacing:-.01em }}
header p {{ color:var(--muted); margin:0 0 10px; max-width:680px }}
.stats {{ display:flex; gap:12px; flex-wrap:wrap; margin:24px 0 }}
.stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 16px; min-width:150px }}
.stat b {{ display:block; font-size:24px }}
.stat span {{ color:var(--muted); font-size:14px }}
.controls {{ display:flex; gap:8px; flex-wrap:wrap; margin:8px 0 16px; align-items:center }}
.controls input {{ flex:1 1 220px; padding:9px 12px; border:1px solid var(--line); border-radius:8px;
  background:var(--card); color:var(--ink); font:inherit }}
.controls button {{ padding:8px 12px; border:1px solid var(--line); border-radius:999px; background:var(--card);
  color:var(--ink); font:inherit; font-size:14px; cursor:pointer }}
.controls button[aria-pressed="true"] {{ background:var(--ink); color:var(--bg); border-color:var(--ink) }}
.row {{ display:grid; grid-template-columns:36px 1fr 70px; gap:12px; background:var(--card);
  border:1px solid var(--line); border-radius:12px; padding:16px; margin-bottom:10px }}
.rank {{ color:var(--muted); font-variant-numeric:tabular-nums; padding-top:2px }}
.row h3 {{ margin:0 0 6px; font-size:18px }}
.row h3 a {{ color:var(--ink); text-decoration:none }}
.row h3 a:hover {{ text-decoration:underline }}
.tags {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:8px }}
.tag {{ font-size:12.5px; padding:2px 8px; border-radius:999px }}
.t-sdk {{ color:var(--sdk); background:var(--sdk-bg) }}
.t-job {{ color:var(--job); background:var(--job-bg) }}
.t-agent {{ color:var(--agent); background:var(--agent-bg) }}
.t-hire {{ color:var(--hire); background:var(--hire-bg) }}
.why {{ margin:0 0 6px; padding-left:18px; color:var(--muted); font-size:14.5px }}
.ev {{ margin:0; font-size:14px; overflow-wrap:anywhere }}
.score {{ text-align:right }}
.score span {{ font-size:26px; font-weight:650; font-variant-numeric:tabular-nums }}
.score small {{ display:block; color:var(--muted); font-size:12px }}
section.how {{ margin-top:40px; border-top:1px solid var(--line); padding-top:24px }}
section.how h2 {{ font-size:20px; margin:0 0 10px }}
table {{ border-collapse:collapse; width:100%; max-width:520px; font-size:15px }}
td, th {{ text-align:left; padding:6px 8px; border-bottom:1px solid var(--line) }}
td:last-child {{ text-align:right; font-variant-numeric:tabular-nums }}
footer {{ margin-top:32px; color:var(--muted); font-size:14px }}
.empty {{ display:none; color:var(--muted); padding:16px 0 }}
@media (max-width:560px) {{
  .row {{ grid-template-columns:1fr 56px }}
  .rank {{ display:none }}
  header h1 {{ font-size:25px }}
}}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>Who needs fast sandboxes for AI agents?</h1>
  <p>I built this for my application to the GTM Engineer role at Unikraft. It's a list of companies that probably need an isolated machine for every agent run, found from public job posts and public code. Every company links to the job post or the line of code that put it here, so you don't have to trust the score.</p>
  <p>I have no relationship with Unikraft. This is my own work from public data. Run from {html.escape(run_date)}.</p>
</header>

<div class="stats">
  <div class="stat"><b>{n}</b><span>companies scored 30+</span></div>
  <div class="stat"><b>{counts['competitor_sdk']}</b><span>already use E2B in code</span></div>
  <div class="stat"><b>{counts['sandbox_job']}</b><span>hiring for sandbox work</span></div>
</div>

<div class="controls">
  <input id="q" type="search" placeholder="Search a company" aria-label="Search a company">
  <button data-f="" aria-pressed="true">All</button>
  <button data-f="competitor_sdk" aria-pressed="false">Uses E2B / Daytona</button>
  <button data-f="sandbox_job" aria-pressed="false">Hiring for sandboxes</button>
</div>

<main id="list">{body}
</main>
<p class="empty" id="empty">Nothing matches that.</p>

<section class="how">
  <h2>How the points work</h2>
  <table>
    <tr><td>Public code imports the E2B or Daytona SDK</td><td>+40</td></tr>
    <tr><td>Same, but only in an example or integration folder</td><td>+20</td></tr>
    <tr><td>Engineering job post talks about sandboxing or microVMs</td><td>+30</td></tr>
    <tr><td>Sells an AI-agent product</td><td>+20</td></tr>
    <tr><td>Posted a job in the last 30 days</td><td>+10</td></tr>
  </table>
  <p>A company whose code already calls a competitor's SDK has decided it needs sandboxes and is paying for them. A company hiring engineers to build sandbox infrastructure is about to build it or buy it. The points are my guess. With real deal data they should be tuned to what actually turned into meetings.</p>
</section>

<footer>
  Karim Fakhri · <a href="https://github.com/kari-fakh12/sandbox-intent-signals">Code on GitHub</a> ·
  <a href="https://www.linkedin.com/in/karim-fakhrii">LinkedIn</a>
</footer>
</div>
<script>
(function () {{
  var q = document.getElementById('q'), rows = [].slice.call(document.querySelectorAll('.row')),
      btns = [].slice.call(document.querySelectorAll('.controls button')), f = '';
  function apply() {{
    var t = q.value.trim().toLowerCase(), shown = 0;
    rows.forEach(function (r) {{
      var ok = (!t || r.dataset.name.indexOf(t) > -1) && (!f || r.dataset.signals.split(';').indexOf(f) > -1);
      r.style.display = ok ? '' : 'none'; if (ok) shown++;
    }});
    document.getElementById('empty').style.display = shown ? 'none' : 'block';
  }}
  q.addEventListener('input', apply);
  btns.forEach(function (b) {{ b.addEventListener('click', function () {{
    f = b.dataset.f; btns.forEach(function (x) {{ x.setAttribute('aria-pressed', x === b); }}); apply();
  }}); }});
}})();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--csv", default=None)
    ap.add_argument("--out", default=os.path.join(HERE, "site", "index.html"))
    a = ap.parse_args()
    path = a.csv or latest_csv()
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    rows.sort(key=lambda r: (-int(r["score"]), r["company"].lower()))
    run_date = rows[0]["found"] if rows else "-"
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(build(rows, run_date))
    print(f"wrote {a.out} from {os.path.relpath(path, HERE)} ({len(rows)} companies)")


if __name__ == "__main__":
    main()
