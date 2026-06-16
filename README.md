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

## Cost and runtime

Typical run: **$0.08–0.20** on Haiku 4.5, **4–7 minutes**. Hard caps in `config.yaml`:

| Setting | Default | Purpose |
|---------|---------|---------|
| `web_fetch_max_uses` | 17 | One fetch per source + buffer |
| `web_fetch_max_content_tokens` | 4000 | Top-of-page only; prevents token bloat |
| `web_search_max_uses` | 1 | Minimize $0.01/search fees |
| `max_tokens` | 800 | Cap output length |
| `max_cost_usd` | 1.00 | Warn if estimate exceeds budget |

After each run, check stdout or `results/usage.log` for a line like:

```
2026-06-16 | in=45000 out=400 fetch=16 search=0 | est=$0.09 | model=claude-haiku-4-5 | elapsed=312s
```

Set a monthly spend alert at [console.anthropic.com](https://console.anthropic.com).

## Notes

- GitHub may delay scheduled runs by 5–15 minutes.
- Scheduled workflows pause after 60 days without repo activity; the daily result commits prevent this.
- The workflow has a 10-minute hard timeout.
- Switch `model` to `claude-sonnet-4-6` in config if Haiku misses headlines — still under $1 with the caps above.
