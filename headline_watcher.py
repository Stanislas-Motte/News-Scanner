"""Headline Watcher: scan major financial outlets for ETS-relevant headlines."""

import re
import sys
import time
from datetime import datetime, timedelta, timezone

from core import (
    Usage,
    format_usage_footer,
    load_config,
    log_usage,
    merge_usage,
    run_claude,
    save_result,
    send_email,
    severity_dot,
)

_META_PATTERNS = re.compile(
    r"code_execution|rate.?limit|web_fetch|web_search|"
    r"I'll (?:fetch|try|switch|use)|let me (?:try|fetch|use)",
    re.IGNORECASE,
)

_SEVERITY_RE = re.compile(
    r"^[^\S\n]*SEVERITY:[^\S\n]*(RED|ORANGE|YELLOW|GREEN)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)
_SEVERITY_RANK = {"GREEN": 0, "YELLOW": 1, "ORANGE": 2, "RED": 3}

_EMPTY_MESSAGE = "No relevant headlines in the last 24 hours."


def _chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def parse_severity(text: str) -> str | None:
    match = _SEVERITY_RE.search(text)
    return match.group(1).upper() if match else None


def strip_severity(text: str) -> str:
    return _SEVERITY_RE.sub("", text, count=1).strip()


def max_severity(severities: list[str | None]) -> str | None:
    rated = [s for s in severities if s]
    if not rated:
        return None
    return max(rated, key=lambda s: _SEVERITY_RANK.get(s, 1))


def build_prompt(cfg: dict, sources: list[str], now: datetime, cutoff: datetime) -> str:
    source_list = "\n".join(f"- {s}" for s in sources)
    lookback = cfg.get("lookback_hours", 24)
    strategy = cfg.get("strategy", "search")

    if strategy == "fetch":
        method = f"""Headline sources for this batch — fetch each URL below exactly once using direct web_fetch calls only:
{source_list}

Critical rules:
- Call web_fetch directly one URL at a time. Do NOT use code execution, scripts, parallel requests, or batch fetching.
- If a fetch fails, skip that source and continue. Do not retry the same URL.
- Do not follow article links or fetch individual articles.
- Scan visible headlines only from the section page returned."""
    else:
        method = f"""Use the web_search tool to find recent headlines. Strongly prefer these major financial and general outlets:
{source_list}

Critical rules:
- Run a small number of targeted web_search queries (you have a limited budget) covering both the carbon/ETS markets in my context and major second-order events (elections, energy or climate policy, geopolitical shocks) in the US, UK, and EU.
- Prefer the outlets above and other major outlets. Do NOT cite specialist carbon trade press (e.g. Carbon Pulse, Argus, ICIS, Montel, OPIS, Quantum Commodity Intelligence).
- Do not waste queries; combine related topics where sensible."""

    return f"""You are a carbon market hedge fund headline analyst.
The current time is {now:%Y-%m-%d %H:%M} UTC.
Only consider items published in the last {lookback} hours — that is, at or after {cutoff:%Y-%m-%d %H:%M} UTC. Ignore anything older.

My context — only report what is relevant to this:
{cfg["context"]}

{method}

General rules:
- Report ONLY headlines relevant to my context. Skip everything else.
- For every item, include the publishing time and a clickable Markdown link to the source article.
- Follow the output format in my context exactly.
- The FIRST line of your response must be exactly `SEVERITY: X` where X is RED, ORANGE, YELLOW, or GREEN, reflecting the highest potential carbon-price impact across all items (GREEN if there is no relevant news). Put nothing else on that line.
- After the SEVERITY line, output ONLY the Highlights section (or the one-line empty message). No preamble, no process narration, no mention of tools, fetches, searches, or errors.

Output clean, readable Markdown."""


def extract_highlights(text: str) -> str:
    """Strip tool-debug narration; keep the Highlights section only."""
    text = text.strip()
    if not text:
        return text

    match = re.search(r"(^|\n)(##\s*Highlights\b.*)", text, re.DOTALL | re.IGNORECASE)
    if match:
        return match.group(2).strip()

    if text.lower().startswith("no relevant headlines"):
        return _EMPTY_MESSAGE

    return text


def validate_digest(digest: str) -> None:
    """Always reject tool-debug narration, regardless of leading heading."""
    if not digest.strip():
        raise RuntimeError("Empty digest after extraction.")
    if digest.strip() == _EMPTY_MESSAGE:
        return
    if _META_PATTERNS.search(digest):
        raise RuntimeError(
            "Digest contains tool-debug narration instead of headlines. "
            "Check the run logs for fetch/search errors."
        )


def _is_usable_section(section: str) -> bool:
    if not section:
        return False
    low = section.lower()
    if "no relevant headlines" in low:
        return False
    if _META_PATTERNS.search(section):
        return False
    return True


def build_header(cfg: dict, now: datetime, cutoff: datetime, severity: str | None) -> str:
    lookback = cfg.get("lookback_hours", 24)
    dot = severity_dot(severity)
    return (
        f"**Run:** {now:%Y-%m-%d %H:%M} UTC  \n"
        f"**Lookback:** last {lookback}h (since {cutoff:%Y-%m-%d %H:%M} UTC)  \n"
        f"**Potential price impact:** {dot} {severity or 'N/A'}"
    )


def run_search(cfg: dict, now: datetime, cutoff: datetime) -> tuple[str, Usage, str | None]:
    sources: list[str] = cfg["headline_sources"]
    raw, usage = run_claude(cfg, build_prompt(cfg, sources, now, cutoff))
    severity = parse_severity(raw)
    body = extract_highlights(strip_severity(raw))
    return body, usage, severity


def run_batched(cfg: dict, now: datetime, cutoff: datetime) -> tuple[str, Usage, str | None]:
    sources: list[str] = cfg["headline_sources"]
    batch_size = cfg.get("source_batch_size", 6)
    batches = _chunked(sources, batch_size)
    total = Usage(0, 0, 0, 0)
    sections: list[str] = []
    severities: list[str | None] = []

    for i, batch in enumerate(batches, 1):
        print(f"Batch {i}/{len(batches)}: {len(batch)} sources")
        try:
            raw, usage = run_claude(
                cfg, build_prompt(cfg, batch, now, cutoff), fetch_max=len(batch)
            )
        except Exception as e:  # one bad batch must not kill the whole run
            print(f"WARNING: batch {i} failed, skipping: {e}")
            continue
        total = merge_usage(total, usage)
        severities.append(parse_severity(raw))
        section = extract_highlights(strip_severity(raw))
        if _is_usable_section(section):
            sections.append(section)
        else:
            print(f"Batch {i}: no usable headlines (empty or narration)")

    severity = max_severity(severities)
    if not sections:
        return _EMPTY_MESSAGE, total, severity

    merged_lines: list[str] = []
    for section in sections:
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower().startswith("## highlights"):
                continue
            if _META_PATTERNS.search(line):
                continue
            merged_lines.append(line)

    if not merged_lines:
        return _EMPTY_MESSAGE, total, severity
    return "## Highlights\n\n" + "\n".join(merged_lines), total, severity


def run_agent(cfg: dict, now: datetime, cutoff: datetime) -> tuple[str, Usage, str | None]:
    if cfg.get("strategy", "search") == "fetch":
        return run_batched(cfg, now, cutoff)
    return run_search(cfg, now, cutoff)


def main() -> None:
    cfg = load_config()
    lookback = cfg.get("lookback_hours", 24)
    max_runtime = cfg.get("max_runtime_seconds", 540)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=lookback)
    start = time.monotonic()

    print(
        f"Running Headline Watcher "
        f"(strategy={cfg.get('strategy', 'search')}, lookback={lookback}h)..."
    )
    digest, usage, severity = run_agent(cfg, now, cutoff)

    elapsed = time.monotonic() - start
    if elapsed > max_runtime:
        print(f"WARNING: run took {elapsed:.0f}s, exceeding soft cap of {max_runtime}s")

    digest = extract_highlights(digest)
    if not digest.strip():
        digest = _EMPTY_MESSAGE
        severity = severity or "GREEN"
    if not severity:
        severity = "YELLOW"  # headlines present but the model gave no rating

    cost = log_usage(usage, elapsed, cfg)
    footer = format_usage_footer(usage, cost, elapsed)
    header = build_header(cfg, now, cutoff, severity)

    # Archive includes the run header so the saved file is self-describing.
    path = save_result(f"{header}\n\n{digest}")
    print(f"Saved {path}")

    try:
        validate_digest(digest)
    except RuntimeError as e:
        sys.exit(f"Validation failed; email skipped (digest saved to {path}): {e}")

    try:
        send_email(cfg, digest, footer=footer, header=header, severity=severity)
    except Exception as e:  # email failure must not discard an already-saved digest
        print(f"WARNING: email failed, digest saved to {path}: {e}")


if __name__ == "__main__":
    main()
