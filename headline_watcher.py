"""Headline Watcher: scan major financial outlets for ETS-relevant headlines."""

import re
import sys
import time
from datetime import datetime, timezone

from core import (
    Usage,
    format_usage_footer,
    load_config,
    log_usage,
    merge_usage,
    run_claude,
    save_result,
    send_email,
)

_META_PATTERNS = re.compile(
    r"code_execution|rate.?limit|web_fetch tool|I'll (?:fetch|try|switch|use)",
    re.IGNORECASE,
)


def _chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_prompt(cfg: dict, sources: list[str]) -> str:
    source_list = "\n".join(f"- {s}" for s in sources)
    now = datetime.now(timezone.utc)
    return f"""You are a carbon market hedge fund headline analyst.
The current time is {now:%Y-%m-%d %H:%M} UTC.

My context — only report what is relevant to this:
{cfg["context"]}

Headline sources for this batch — fetch each URL below exactly once using direct web_fetch calls only:
{source_list}

Critical rules:
- Call web_fetch directly one URL at a time. Do NOT use code execution, scripts, parallel requests, or batch fetching.
- Do NOT use web_search unless explicitly told this is the final batch and a major story is missing.
- If a fetch fails, skip that source and continue. Do not retry the same URL.
- Do not follow article links or fetch individual articles.
- Scan visible headlines only from the section page returned.
- Only consider headlines from the last 48 hours.
- Report ONLY headlines relevant to my context.
- Follow the output format in my context exactly.
- Your entire response must be ONLY the Highlights section (or the one-line empty message). No preamble, no process narration, no mention of tools or errors.

Output clean, readable Markdown."""


def extract_highlights(text: str) -> str:
    """Strip tool-debug narration; keep Highlights section only."""
    text = text.strip()
    if not text:
        return text

    match = re.search(r"(^|\n)(##\s*Highlights\b.*)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(2).strip()

    if text.lower().startswith("no relevant headlines"):
        return text.split("\n")[0].strip()

    return text


def validate_digest(digest: str) -> None:
    if not digest.strip():
        raise RuntimeError("Empty digest after extraction.")
    if digest.lower().startswith("no relevant headlines"):
        return
    if digest.strip().lower().startswith("## highlights"):
        return
    if _META_PATTERNS.search(digest):
        raise RuntimeError(
            "Digest contains tool-debug narration instead of headlines. "
            "Check GitHub Actions logs for rate-limit errors."
        )


def run_batched(cfg: dict) -> tuple[str, Usage]:
    sources: list[str] = cfg["headline_sources"]
    batch_size = cfg.get("source_batch_size", 6)
    batches = _chunked(sources, batch_size)
    total = Usage(0, 0, 0, 0)
    sections: list[str] = []

    for i, batch in enumerate(batches, 1):
        print(f"Batch {i}/{len(batches)}: {len(batch)} sources")
        raw, usage = run_claude(cfg, build_prompt(cfg, batch), fetch_max=len(batch))
        total = merge_usage(total, usage)
        section = extract_highlights(raw)
        if section and "no relevant headlines" not in section.lower():
            sections.append(section)

    if not sections:
        return "No relevant headlines in the last 48 hours.", total

    if len(sections) == 1:
        return sections[0], total

    merged = "## Highlights\n\n" + "\n".join(
        line for s in sections for line in s.splitlines()
        if line.strip() and not line.strip().lower().startswith("## highlights")
    )
    return merged.strip(), total


def main() -> None:
    cfg = load_config()
    max_runtime = cfg.get("max_runtime_seconds", 540)
    start = time.monotonic()

    print("Running Headline Watcher...")
    digest, usage = run_batched(cfg)

    elapsed = time.monotonic() - start
    if elapsed > max_runtime:
        print(f"WARNING: run took {elapsed:.0f}s, exceeding soft cap of {max_runtime}s")

    digest = extract_highlights(digest)
    validate_digest(digest)

    cost = log_usage(usage, elapsed, cfg)
    footer = format_usage_footer(usage, cost, elapsed)

    path = save_result(digest)
    print(f"Saved {path}")
    send_email(cfg, digest, footer)


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as e:
        sys.exit(str(e))
