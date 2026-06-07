"""Daily news scanner: reads news sites with Claude + web search,
summarizes what's relevant to your context, emails the digest,
and stores the result in results/YYYY-MM-DD.md."""

import os
import sys
from datetime import date
from pathlib import Path

import requests
import yaml
from anthropic import Anthropic

ROOT = Path(__file__).parent
RESULTS_DIR = ROOT / "results"


def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f)


def build_prompt(cfg: dict) -> str:
    sites = "\n".join(f"- {s}" for s in cfg["sites"])
    return f"""You are a news analyst. Today is {date.today().isoformat()}.

Visit and read the following news sites:
{sites}

My context — only report what is relevant to this:
{cfg["context"]}

Instructions:
- Fetch each site and look at articles from the last 24-48 hours.
- Summarize ONLY items relevant to my context. Skip everything else.
- For each relevant item: a bold one-line headline, a 2-3 sentence summary, and a link.
- If nothing relevant was published, say so explicitly in one line.
- End with a one-paragraph "Big picture" takeaway if there are 2+ items.
- Output clean Markdown."""


def run_claude(cfg: dict, prompt: str) -> str:
    client = Anthropic()  # uses ANTHROPIC_API_KEY env var
    response = client.messages.create(
        model=cfg["model"],
        max_tokens=cfg["max_tokens"],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
        messages=[{"role": "user", "content": prompt}],
    )
    # Concatenate all text blocks (web search responses interleave tool blocks)
    return "\n".join(b.text for b in response.content if b.type == "text")


def save_result(digest: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{date.today().isoformat()}.md"
    path.write_text(digest)
    return path


def send_email(cfg: dict, digest: str) -> None:
    import markdown  # lazy import; converts digest to HTML

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": cfg["email"]["from"],
            "to": [cfg["email"]["to"]],
            "subject": f"{cfg['email']['subject_prefix']} — {date.today().isoformat()}",
            "html": markdown.markdown(digest),
        },
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Email sent: {resp.json().get('id')}")


def main() -> None:
    cfg = load_config()
    print("Running Claude with web search...")
    digest = run_claude(cfg, build_prompt(cfg))
    if not digest.strip():
        sys.exit("Claude returned an empty digest; aborting.")
    path = save_result(digest)
    print(f"Saved {path}")
    send_email(cfg, digest)


if __name__ == "__main__":
    main()
