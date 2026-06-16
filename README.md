# Headline Watcher

Daily agent that scans major financial and general news outlets for ETS-relevant headlines, emails you a Highlights digest, and stores every result in `results/` as git history.

**Architecture:** GitHub Actions (cron) → `headline_watcher.py` → Claude API with web fetch (+ optional web search) → Resend email → result committed to repo.

## Setup (one time, ~10 min)

1. **Get a Resend API key** — sign up at [resend.com](https://resend.com), create an API key. The free tier (100 emails/day) and the default `onboarding@resend.dev` sender are enough for emailing yourself.

2. **Create a GitHub repo and push this folder:**

   ```bash
   git init && git add -A && git commit -m "Initial scanner"
   gh repo create ai-news-scanner --private --source=. --push
   ```

3. **Add secrets** — in the repo: Settings → Secrets and variables → Actions → New repository secret:
   - `ANTHROPIC_API_KEY`
   - `RESEND_API_KEY`

4. **Test it** — Actions tab → "Daily Headline Watcher" → Run workflow. Check your inbox and the `results/` folder.

Done. It runs daily at 05:00 UTC.

## Customizing

- **`config.yaml`** — headline sources (major outlets only), model, tool budgets, email settings
- **`instructions.txt`** — ETS scope, relevance rules, output format

Edit, commit, push — next run picks it up.

To change the schedule, edit the `cron` line in `.github/workflows/daily-scan.yml` ([crontab.guru](https://crontab.guru) helps). Note: times are UTC.

## Running locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export RESEND_API_KEY=re_...
python headline_watcher.py
```

(`python scanner.py` also works — it delegates to Headline Watcher.)

## Email format

- **Subject** carries a colored severity dot reflecting the highest potential carbon-price impact: 🔴 high / immediate, 🟠 moderate, 🟡 minor / second-order, 🟢 none. The model assigns this on every run.
- **Body header** shows the exact run time (UTC) and the lookback window, e.g. `Lookback: last 24h (since ...)`.
- Lookback defaults to 24 hours (`lookback_hours` in `config.yaml`).

## How it gathers headlines

Two strategies, set by `strategy` in `config.yaml`:

- **`search`** (default) — uses Anthropic's `web_search`, scoped to the outlet domains. This survives paywalls and anti-bot walls (FT, WSJ, Bloomberg) because it reads indexed results rather than scraping pages.
- **`fetch`** — reads each section page directly in small batches. Often blocked by paywalled sites; use only for open outlets.

## Cost and runtime

Typical run: **$0.20–0.45** on Sonnet 4.6, **2–6 minutes**. Key caps in `config.yaml`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `web_search_max_uses` | 8 | Search budget ($0.01 each) |
| `max_tokens` | 1000 | Cap output length |
| `max_retries` | 1 | Stop runaway retry/backoff under the 10-min job limit |
| `api_timeout_seconds` | 240 | Per-request timeout |
| `max_cost_usd` | 1.00 | Warn (post-run) if estimate exceeds budget |

After each run, check stdout or `results/usage.log` for a line like:

```
2026-06-16 | in=45000 out=400 fetch=0 search=6 | est=$0.28 | model=claude-sonnet-4-6 | elapsed=190s
```

Set a monthly spend alert at [console.anthropic.com](https://console.anthropic.com).

## Notes

- GitHub may delay scheduled runs by 5–15 minutes.
- Scheduled workflows pause after 60 days without repo activity; the commit step runs even on failure (`if: always()`) to keep the repo active and preserve `usage.log`.
- The workflow has a 10-minute hard timeout.
- Uses Sonnet 4.6 (Haiku does not support these web tools without programmatic tool calling).
- `max_cost_usd` only warns after the fact; the real cost controls are `web_search_max_uses` and `max_tokens`.
