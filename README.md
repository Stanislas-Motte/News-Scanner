# AI News Scanner

Daily agent that reads news sites through your context lens, emails you a digest, and stores every result in `results/` as git history.

**Architecture:** GitHub Actions (cron) → Python script → Claude API with web search → Resend email → result committed to repo.

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

4. **Test it** — Actions tab → "Daily News Scan" → Run workflow. Check your inbox and the `results/` folder.

Done. It runs daily at 07:00 UTC.

## Customizing

Everything lives in `config.yaml`: the context (what counts as relevant), the list of sites, recipient, and model. Edit, commit, push — next run picks it up.

To change the schedule, edit the `cron` line in `.github/workflows/daily-scan.yml` ([crontab.guru](https://crontab.guru) helps). Note: times are UTC.

## Running locally

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
export RESEND_API_KEY=re_...
python scanner.py
```

## Notes

- GitHub may delay scheduled runs by 5–15 minutes.
- Scheduled workflows pause after 60 days without repo activity; the daily result commits prevent this.
- Cost: one Claude call/day with ~10 web searches — typically a few cents per run.
