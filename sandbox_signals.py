#!/usr/bin/env python3
"""
Sandbox intent signals.

Finds companies that look like they need fast, isolated sandboxes (for AI agents,
code execution or headless browsers) and scores them.

Signals, all from free public sources:
  1. Public GitHub code that imports the E2B or Daytona SDK. The repo owner (an
     organization, never a single person) already runs sandboxes with a competitor.
  2. Engineering job posts that talk about sandboxing, microVMs, Firecracker,
     gVisor, code execution or agent / browser infrastructure. Read from the
     Arbeitnow job API and from public Greenhouse, Lever and Ashby job boards.
  3. The company sells an AI-agent product.
  4. The company posted a job in the last N days.

Standard library only. Every row keeps an evidence URL so any score is one click
from proof. Companies already reported are remembered in state/seen.txt.

Usage:
  python3 sandbox_signals.py
  python3 sandbox_signals.py --arbeitnow-pages 3 --max-orgs 40 --no-dedupe
  GITHUB_TOKEN=... python3 sandbox_signals.py      # needed for GitHub code search
"""
import argparse, csv, html, json, os, re, sys, time, unicodedata, urllib.error, urllib.parse, urllib.request
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
SEEN = os.path.join(HERE, "state", "seen.txt")
SEEDS = os.path.join(HERE, "seeds", "ai_agent_companies.txt")
UA = "sandbox-intent-signals/1.0 (+https://github.com/kari-fakh12/sandbox-intent-signals)"

POINTS = {
    "competitor_sdk": 40,   # public code imports the E2B or Daytona SDK
    "competitor_sdk_example": 20,  # same, but only in an examples / integrations / docs folder
    "sandbox_job": 30,      # engineering job post talks about sandboxing / microVMs
    "ai_agent": 20,         # sells an AI-agent product
    "recent_hiring": 10,    # posted a job in the last --days days
}

# Never list these. Unikraft's public customers, the sandbox vendors themselves,
# and Unikraft. Keys are lowercase letters and digits only.
EXCLUDE = {
    "unikraft", "prisma", "browseruse", "flutterflow", "tinyfish", "tinyfishio",
    "e2b", "e2bdev", "daytona", "daytonaio", "modal", "modallabs", "flyio", "superfly",
    "vercel",
}

# What a sandbox need sounds like in a job post.
SANDBOX_TERMS = [
    (r"\bmicro-?vms?\b", "microVM"),
    (r"\bfirecracker\b", "Firecracker"),
    (r"\bgvisor\b", "gVisor"),
    (r"\bkata containers\b", "Kata Containers"),
    (r"\bcloud[- ]hypervisor\b", "Cloud Hypervisor"),
    (r"\bunikernels?\b", "unikernel"),
    (r"\be2b\b", "E2B"),
    (r"\bdaytona\b(?!\s+beach)", "Daytona"),
    (r"\bcode execution\b", "code execution"),
    (r"\bcode interpreters?\b", "code interpreter"),
    # A bare "sandbox" is too common (payment sandboxes, test sandboxes), so it
    # only counts next to code, agents, VMs or isolation.
    (r"\b(?:code|agents?|untrusted|isolat\w*|execution|browsers?|vms?|containers?|runtimes?)\W+(?:\w+\W+){0,4}?sandbox(?:es|ed|ing)?\b", "sandbox"),
    (r"\bsandbox(?:es|ed|ing)?\W+(?:\w+\W+){0,4}?(?:code|agents?|untrusted|isolat\w*|execution|browsers?|vms?|containers?|runtimes?)\b", "sandbox"),
    (r"\bagent infrastructure\b", "agent infrastructure"),
    (r"\bbrowser infrastructure\b", "browser infrastructure"),
    (r"\bheadless browsers?\b", "headless browser"),
    (r"\buntrusted code\b", "untrusted code"),
]
SANDBOX_RE = [(re.compile(p, re.I), label) for p, label in SANDBOX_TERMS]

# Only engineering roles count for the job signal. A sales rep who mentions
# "sandbox" is not the buyer.
ENG_TITLE = re.compile(
    r"engineer|developer|infrastructure|platform|sre\b|devops|backend|systems|runtime|"
    r"kernel|security|architect|research|member of (technical )?staff|cto|founding", re.I)

AI_AGENT = re.compile(
    r"\bai agents?\b|\bagentic\b|\bagents?\b.{0,60}\b(llm|ai)\b|\b(llm|ai)\b.{0,60}\bagents?\b|"
    r"\bcoding agent|\bbrowser agent|\bcopilot\b|\bautonomous agent", re.I)

# GitHub code search queries. Each one means "this repo calls a competitor's SDK".
GH_CODE_QUERIES = [
    ("E2B", '"from e2b_code_interpreter import" language:Python'),
    ("E2B", '"from e2b import" language:Python'),
    ("E2B", '"@e2b/code-interpreter" filename:package.json'),
    ("E2B", '"from \'e2b\'" language:TypeScript'),
    ("Daytona", '"from daytona import" language:Python'),
    ("Daytona", '"from daytona_sdk import" language:Python'),
    ("Daytona", '"@daytonaio/sdk" filename:package.json'),
]
# Without a token GitHub code search is closed, so fall back to repo search.
GH_REPO_QUERIES = [
    ("E2B", '"e2b_code_interpreter" in:readme'),
    ("E2B", '"@e2b/code-interpreter" in:readme'),
    ("Daytona", '"@daytonaio/sdk" in:readme'),
    ("Daytona", '"daytona_sdk" in:readme'),
]

EXAMPLE_PATH = re.compile(r"example|cookbook|sample|integration|demo|docs?/|tutorial|template|awesome", re.I)

STATUS = {}   # source -> {"ok": n, "fail": n, "notes": [..]}


def clean_name(name):
    """Drop emoji and other symbols from a public org name."""
    name = "".join(ch for ch in name if unicodedata.category(ch) not in ("So", "Sk", "Cs"))
    return re.sub(r"\s+", " ", name).strip(" -|")


def note(source, ok=True, msg=None):
    s = STATUS.setdefault(source, {"ok": 0, "fail": 0, "notes": []})
    s["ok" if ok else "fail"] += 1
    if msg and msg not in s["notes"] and len(s["notes"]) < 5:
        s["notes"].append(msg)


def key_of(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def get_json(url, headers=None, tries=3):
    """GET a URL and parse JSON. Returns (data, error_string)."""
    h = {"User-Agent": UA, "Accept": "application/json"}
    h.update(headers or {})
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=40) as r:
                return json.load(r), None
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}"
            if e.code in (403, 429) and "api.github.com" in url:
                reset = e.headers.get("X-RateLimit-Reset")
                remaining = e.headers.get("X-RateLimit-Remaining")
                if remaining == "0" and reset:
                    last = f"HTTP {e.code} rate limited until {datetime.fromtimestamp(int(reset), timezone.utc):%H:%M} UTC"
                    return None, last
                time.sleep(20 * (i + 1))   # secondary rate limit, wait and retry
                continue
            if e.code in (400, 401, 404, 410, 422):
                return None, last
        except Exception as e:
            last = type(e).__name__ + ": " + str(e)[:80]
        time.sleep(3 * (i + 1))
    return None, last


def plain(text):
    text = html.unescape(text or "")
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html.unescape(text))


def sandbox_hits(text):
    return sorted({label for rx, label in SANDBOX_RE if rx.search(text)})


def parse_when(v):
    if v is None or v == "":
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
        return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None


class Company:
    def __init__(self, name):
        self.name = name
        self.signals = {}      # signal -> (evidence text, url)
        self.extra = []        # more evidence urls
        self.sources = set()
        self.website = ""

    def add(self, signal, text, url, source):
        self.sources.add(source)
        if signal not in self.signals:
            self.signals[signal] = (text, url)
        elif url and url not in self.extra and url != self.signals[signal][1] and len(self.extra) < 4:
            self.extra.append(url)

    @property
    def score(self):
        if "competitor_sdk" in self.signals:
            self.signals.pop("competitor_sdk_example", None)
        return sum(POINTS[s] for s in self.signals)


def get_company(companies, name):
    k = key_of(name)
    if k not in companies:
        companies[k] = Company(name.strip())
    return companies[k]


# ---------------------------------------------------------------- job boards

def board_jobs(board, slug):
    """Return a list of (title, text, url, posted_datetime) for one public board."""
    if board == "greenhouse":
        data, err = get_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
        jobs = (data or {}).get("jobs", [])
        out = [(j.get("title", ""), plain(j.get("content")), j.get("absolute_url", ""),
                parse_when(j.get("first_published") or j.get("updated_at"))) for j in jobs]
    elif board == "lever":
        data, err = get_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
        jobs = data if isinstance(data, list) else []
        out = [(j.get("text", ""), " ".join([j.get("descriptionPlain", "") or "", j.get("additionalPlain", "") or "",
                " ".join(plain(l.get("content")) for l in j.get("lists", []))]),
                j.get("hostedUrl", ""), parse_when(j.get("createdAt"))) for j in jobs]
    elif board == "ashby":
        data, err = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
        jobs = (data or {}).get("jobs", [])
        out = [(j.get("title", ""), j.get("descriptionPlain") or plain(j.get("descriptionHtml")),
                j.get("jobUrl", ""), parse_when(j.get("publishedAt"))) for j in jobs]
    else:
        return None, f"unknown board {board}"
    return (out if data is not None else None), err


def score_jobs(company, jobs, source, cutoff, force_ai=False):
    """Apply the job-based signals to one company from its list of jobs."""
    best = None
    ai_hit = None
    recent = None
    for title, text, url, posted in jobs:
        blob = f"{title} {text}"
        if ENG_TITLE.search(title or ""):
            hits = sandbox_hits(blob)
            if hits:
                # prefer posts that name a strong term over a bare "sandbox"
                strength = len([h for h in hits if h != "sandbox"])
                if best is None or strength > best[0]:
                    best = (strength, title, hits, url)
        if ai_hit is None and AI_AGENT.search(f"{title} {(text or '')[:1000]}"):
            ai_hit = (title, url)
        if posted and posted >= cutoff and (recent is None or posted > recent[0]):
            recent = (posted, title, url)
    if best:
        company.add("sandbox_job", f'job "{best[1]}" mentions {", ".join(best[2])}', best[3], source)
    if force_ai:
        company.add("ai_agent", "on the AI-agent seed list", jobs[0][2] if jobs else "", source)
    elif ai_hit:
        company.add("ai_agent", f'job "{ai_hit[0]}" describes an AI-agent product', ai_hit[1], source)
    if recent:
        company.add("recent_hiring", f'posted "{recent[1]}" on {recent[0]:%Y-%m-%d}', recent[2], source)


def run_seeds(companies, seeds_path, cutoff):
    if not os.path.exists(seeds_path):
        note("seed boards", False, f"missing {seeds_path}")
        return
    for line in open(seeds_path, encoding="utf-8"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        board, slug, name = line.split(None, 2)
        jobs, err = board_jobs(board, slug)
        src = f"{board} board"
        if jobs is None:
            note(src, False, f"{slug}: {err}")
            continue
        note(src, True)
        c = get_company(companies, name)
        score_jobs(c, jobs, src, cutoff, force_ai=True)
        time.sleep(0.5)


def run_arbeitnow(companies, pages, cutoff):
    per_company = {}
    for page in range(1, pages + 1):
        data, err = get_json(f"https://www.arbeitnow.com/api/job-board-api?page={page}")
        if data is None:
            note("arbeitnow", False, f"page {page}: {err}")
            time.sleep(6)
            continue
        note("arbeitnow", True)
        jobs = data.get("data", [])
        if not jobs:
            break
        for j in jobs:
            name = (j.get("company_name") or "").strip()
            if name:
                per_company.setdefault(name, []).append(
                    (j.get("title", ""), plain(j.get("description")), j.get("url", ""), parse_when(j.get("created_at"))))
        time.sleep(2)
    # Only companies with a real sandbox signal get in from this source. A random
    # company that is hiring is not a lead.
    for name, jobs in per_company.items():
        if any(ENG_TITLE.search(t or "") and sandbox_hits(f"{t} {x}") for t, x, _, _ in jobs):
            score_jobs(get_company(companies, name), jobs, "arbeitnow", cutoff)


# ---------------------------------------------------------------- GitHub

def gh_headers():
    tok = os.environ.get("GITHUB_TOKEN", "").strip()
    h = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    if tok:
        h["Authorization"] = f"Bearer {tok}"
    return h, bool(tok)


def run_github(companies, max_orgs, per_page):
    headers, authed = gh_headers()
    orgs = {}   # login -> (vendor, evidence url, repo full name, repo description)
    if authed:
        queries, kind, pause = GH_CODE_QUERIES, "code", 7     # code search: 10 requests/min
    else:
        queries, kind, pause = GH_REPO_QUERIES, "repositories", 7   # unauth search: 10/min
        note("github", True, "no GITHUB_TOKEN, used repo search instead of code search")
    for vendor, q in queries:
        url = f"https://api.github.com/search/{kind}?q={urllib.parse.quote(q)}&per_page={per_page}"
        data, err = get_json(url, headers)
        if data is None:
            note("github", False, f"{q}: {err}")
            if err and "rate limited" in err:
                break
            continue
        note("github", True)
        for item in data.get("items", []):
            repo = item.get("repository", item) if kind == "code" else item
            owner = repo.get("owner") or {}
            if owner.get("type") != "Organization":
                continue   # people are not companies, and we do not list people
            login = owner.get("login", "")
            if key_of(login) in EXCLUDE:
                continue
            ev = item.get("html_url") or repo.get("html_url", "")
            weak = bool(EXAMPLE_PATH.search(item.get("path", "") if kind == "code" else "")
                        or EXAMPLE_PATH.search(repo.get("name", "")))
            prev = orgs.get(login.lower())
            # keep the strongest evidence per org: real product code beats an example folder
            if prev is None or (prev[5] and not weak):
                orgs[login.lower()] = (vendor, ev, repo.get("full_name", ""), repo.get("description") or "", login, weak)
        time.sleep(pause)

    # Look up each org once to get its public name and website. An org with no
    # website is usually a hackathon team or a class project, so it is dropped.
    kept = 0
    for login_l, (vendor, ev, full, desc, login, weak) in orgs.items():
        if kept >= max_orgs:
            break
        info, err = get_json(f"https://api.github.com/orgs/{login}", headers)
        if info is None:
            note("github orgs", False, f"{login}: {err}")
            if err and "rate limited" in err:
                break
            continue
        note("github orgs", True)
        blog = (info.get("blog") or "").strip()
        if not blog:
            continue
        name = clean_name(info.get("name") or login)
        if key_of(name) in EXCLUDE:
            continue
        c = get_company(companies, name)
        c.website = c.website or blog
        c.gh_login = login
        if weak:
            c.add("competitor_sdk_example", f"{full} uses the {vendor} SDK in an example or integration", ev, "github")
        else:
            c.add("competitor_sdk", f"{full} imports the {vendor} SDK", ev, "github")
        about = f"{info.get('description') or ''} {desc}"
        if AI_AGENT.search(about):
            c.add("ai_agent", f"GitHub profile or repo describes AI agents", info.get("html_url", ""), "github")
        kept += 1
        time.sleep(0.3)


def probe_boards(companies, limit, cutoff):
    """For GitHub finds, try the org name as a job-board slug to pick up hiring signals."""
    tried = 0
    for c in sorted(companies.values(), key=lambda c: -c.score):
        if tried >= limit:
            break
        login = getattr(c, "gh_login", None)
        if not login or "sandbox_job" in c.signals:
            continue
        tried += 1
        for board in ("ashby", "greenhouse", "lever"):
            jobs, err = board_jobs(board, login.lower())
            if jobs:
                note("board probe", True, None)
                score_jobs(c, jobs, f"{board} board", cutoff)
                break
        time.sleep(0.5)


# ---------------------------------------------------------------- output

def load_seen():
    if not os.path.exists(SEEN):
        return set()
    return {l.strip() for l in open(SEEN, encoding="utf-8") if l.strip()}


def save_seen(seen):
    os.makedirs(os.path.dirname(SEEN), exist_ok=True)
    with open(SEEN, "w", encoding="utf-8") as f:
        f.write("\n".join(sorted(seen)) + "\n")


ORDER = ["competitor_sdk", "competitor_sdk_example", "sandbox_job", "ai_agent", "recent_hiring"]


def to_row(c, today):
    top = next(s for s in ORDER if s in c.signals)
    why = " | ".join(f"+{POINTS[s]} {c.signals[s][0]}" for s in ORDER if s in c.signals)
    more = [c.signals[s][1] for s in ORDER if s in c.signals and s != top and c.signals[s][1]]
    more = list(dict.fromkeys(more + c.extra))
    return {
        "found": today, "company": c.name, "score": c.score,
        "signals": ";".join(s for s in ORDER if s in c.signals),
        "why": why, "evidence_url": c.signals[top][1],
        "more_evidence": " ".join(u for u in more if u != c.signals[top][1])[:1500],
        "website": c.website, "sources": ";".join(sorted(c.sources)),
    }


def write_md(path, rows, args, skipped_seen, skipped_low):
    lines = [f"# Sandbox intent signals, {rows[0]['found'] if rows else date.today().isoformat()}", ""]
    lines.append(f"{len(rows)} companies scored {args.min_score} or more. "
                 f"{skipped_seen} skipped as already reported, {skipped_low} below the cutoff.")
    lines += ["", "## Sources", "", "| Source | OK calls | Failed calls | Notes |", "|---|---|---|---|"]
    for s, v in sorted(STATUS.items()):
        lines.append(f"| {s} | {v['ok']} | {v['fail']} | {'; '.join(v['notes']) or '-'} |")
    lines += ["", "## Points", "", "| Signal | Points |", "|---|---|"]
    lines += [f"| {s} | +{POINTS[s]} |" for s in ORDER]
    lines += ["", "## Top companies", "", "| # | Company | Score | Why | Evidence |", "|---|---|---|---|---|"]
    for i, r in enumerate(rows[:25], 1):
        lines.append(f"| {i} | {r['company']} | {r['score']} | {r['why'].replace('|', '/')} | {r['evidence_url']} |")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arbeitnow-pages", type=int, default=3)
    ap.add_argument("--github-per-page", type=int, default=50)
    ap.add_argument("--max-orgs", type=int, default=40, help="GitHub orgs to look up")
    ap.add_argument("--probe", type=int, default=15, help="GitHub orgs to check for a public job board")
    ap.add_argument("--days", type=int, default=30, help="window for recent hiring")
    ap.add_argument("--min-score", type=int, default=30)
    ap.add_argument("--seeds", default=SEEDS)
    ap.add_argument("--skip", default="", help="comma list: github,seeds,arbeitnow")
    ap.add_argument("--out", default=None)
    ap.add_argument("--no-dedupe", action="store_true", help="ignore memory, report everything")
    args = ap.parse_args()

    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    today = date.today().isoformat()
    companies = {}

    if "github" not in skip:
        print("github ...", file=sys.stderr)
        run_github(companies, args.max_orgs, args.github_per_page)
    if "seeds" not in skip:
        print("seed job boards ...", file=sys.stderr)
        run_seeds(companies, args.seeds, cutoff)
    if "arbeitnow" not in skip:
        print("arbeitnow ...", file=sys.stderr)
        run_arbeitnow(companies, args.arbeitnow_pages, cutoff)
    if "github" not in skip and args.probe:
        print("probing job boards for GitHub finds ...", file=sys.stderr)
        probe_boards(companies, args.probe, cutoff)

    seen = set() if args.no_dedupe else load_seen()
    rows, skipped_seen, skipped_low = [], 0, 0
    for k, c in companies.items():
        if k in EXCLUDE or not c.signals:
            continue
        if c.score < args.min_score:
            skipped_low += 1
            continue
        if k in seen:
            skipped_seen += 1
            continue
        rows.append(to_row(c, today))
    rows.sort(key=lambda r: (-r["score"], r["company"].lower()))

    out = args.out or os.path.join(HERE, "output", f"signals-{today}.csv")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    if not rows and os.path.exists(out) and sum(1 for _ in open(out, encoding="utf-8")) > 1:
        print("nothing net-new, keeping the existing file:", out)
        return
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["found", "company", "score", "signals", "why",
                                          "evidence_url", "more_evidence", "website", "sources"])
        w.writeheader()
        w.writerows(rows)
    md = os.path.splitext(out)[0] + ".md"
    write_md(md, rows, args, skipped_seen, skipped_low)

    if not args.no_dedupe:
        save_seen(seen | {key_of(r["company"]) for r in rows})

    for s, v in sorted(STATUS.items()):
        print(f"{s:14}: ok {v['ok']}, failed {v['fail']}  {'; '.join(v['notes'])}")
    print(f"companies      : {len(rows)} new, {skipped_seen} already seen, {skipped_low} below {args.min_score}")
    print(f"written        : {out}\n                 {md}")
    for r in rows[:15]:
        print(f"  {r['score']:>3}  {r['company']}  {r['evidence_url']}")


if __name__ == "__main__":
    main()
