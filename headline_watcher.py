"""Headline Watcher: scan major financial outlets for ETS-relevant headlines."""

import sys
import time
from datetime import datetime, timezone

from core import (
    format_usage_footer,
    load_config,
    log_usage,
    run_claude,
    save_result,
    send_email,
)


def build_prompt(cfg: dict) -> str:
    sources = "\n".join(f"- {s}" for s in cfg["headline_sources"])
    now = datetime.now(timezone.utc)
    return f"""You are a carbon market hedge fund headline analyst.
The current time is {now:%Y-%m-%d %H:%M} UTC.

My context — only report what is relevant to this:
{cfg["context"]}

Headline sources (fetch each URL exactly once with web_fetch; do not follow article links):
{sources}

Instructions:
- Use web_fetch to read each listed source page and scan visible headlines only.
- Use web_search at most once only if a major second-order story (e.g. election, geopolitical shock) may be missing from the listed pages.
- Only consider headlines from articles published within the last 48 hours. Ignore anything older.
- Report ONLY headlines relevant to my context. Skip everything else.
- Follow the output format and guidance in my context exactly.
- For every item, include the publishing time and a clickable Markdown link to the source article.
- Quote the headline as published; do not rewrite it as a full article summary.
- Do not write any preamble or introduction; start directly with the Highlights section.
- If nothing relevant was published, say so explicitly in one line.
- Use a professional, formal, informative, and concise tone. No emojis or decorative indicators.
- Output clean, readable Markdown."""


def main() -> None:
    cfg = load_config()
    max_runtime = cfg.get("max_runtime_seconds", 540)
    start = time.monotonic()

    print("Running Headline Watcher...")
    digest, usage = run_claude(cfg, build_prompt(cfg))

    elapsed = time.monotonic() - start
    if elapsed > max_runtime:
        print(f"WARNING: run took {elapsed:.0f}s, exceeding soft cap of {max_runtime}s")

    if not digest.strip():
        sys.exit("Claude returned an empty digest; aborting.")

    cost = log_usage(usage, elapsed, cfg)
    footer = format_usage_footer(usage, cost, elapsed)

    path = save_result(digest)
    print(f"Saved {path}")
    send_email(cfg, digest, footer)


if __name__ == "__main__":
    main()
