# sandbox-intent-signals

Live page with the results: https://sandbox-signals.vercel.app

I built this for my application to the GTM Engineer role at Unikraft. It is how I
would find companies that need fast sandboxes: teams running AI agents, code
execution or headless browsers, who need a clean, isolated machine per task and
need it to start right away.

It is one Python script. Standard library only, free public sources, no logins,
no paid APIs. Every row in the output has a link to the job post or the line of
code that earned the points, so nobody has to trust the score.

I have no relationship with Unikraft. This is my own work, built from public data.

## The signals

**Their code already uses E2B or Daytona.** GitHub code search for imports like
`from e2b_code_interpreter import` or `@daytonaio/sdk`. If a company's repo calls a
competitor's SDK, they have already decided they need sandboxes and they already
pay for them. That is the easiest conversation: you are not selling the idea,
only a faster or cheaper version of it. Only organizations are kept, never
personal accounts, and orgs with no website are dropped (mostly hackathon teams).
If the SDK only shows up in an examples or integrations folder it gets fewer
points, because a framework that supports E2B is not the same as a team running it.

**They are hiring engineers to build sandbox infrastructure.** Engineering job posts
that mention microVMs, Firecracker, gVisor, Kata Containers, code execution,
untrusted code, agent infrastructure, browser infrastructure, or "sandbox" next to
words like code, agent or VM. A company hiring someone to build this is either
about to build it in-house or about to buy it. Either way it is the right week to
talk. Sources: the Arbeitnow job API and the public Greenhouse, Lever and Ashby
job boards of the companies in `seeds/ai_agent_companies.txt`.

**They sell an AI-agent product.** Agents run code and open browsers. Each run
wants its own sandbox, and many of them at once. This is where Unikraft's fast
cold starts and scale-to-zero matter most.

**They posted a job in the last 30 days.** Money is coming in and the team is
growing. Not a reason to reach out on its own, it just moves a company up.

## Scoring

| Signal | Points |
|---|---|
| Public code imports the E2B or Daytona SDK | +40 |
| Same, but only in an example or integration folder | +20 |
| Engineering job post talks about sandboxing or microVMs | +30 |
| Sells an AI-agent product | +20 |
| Posted a job in the last 30 days | +10 |

Each signal counts once per company. Default cutoff is 30 points. Unikraft's
public customers and the sandbox vendors themselves are left out.

## Run it

```
python3 sandbox_signals.py
```

GitHub code search needs a token. Without one the script falls back to a weaker
repo search and says so in the summary.

```
GITHUB_TOKEN=your_token python3 sandbox_signals.py --arbeitnow-pages 3 --max-orgs 40
```

Output goes to `output/signals-<date>.csv` plus a short `.md` summary. Companies
already reported are saved in `state/seen.txt` and skipped next time, so each day
only shows new ones. Use `--no-dedupe` to see everything. `--help` lists the rest.

`examples/sample-run.csv` and `examples/sample-run.md` are one real run.

The workflow in `.github/workflows/daily.yml` runs it every morning and commits the
results. If code search fails with the built-in Actions token, add a read-only
personal token as a `SEARCH_TOKEN` secret.

## The page

`python3 build_page.py --csv examples/sample-run.csv` builds `site/index.html`, the page that's live on Vercel. Every company links to its evidence, and you can search or filter by signal.

## What I would add with access to Unikraft's data

- Match the list against signups and usage. A company that scores 70 and already
  has a free account is a very different call from one that has never heard of you.
- Route each company to the right AE by region and size, and create the account in
  the CRM with the evidence link attached, so the first email can point at the
  actual job post or repo.
- Check which scores turned into meetings and deals, and change the points to match.
  The numbers above are my guess, the data should set them.
- Find the right people at each company (the engineer on the job post's team, the
  head of infra) with an enrichment tool, after the company is qualified, not before.
