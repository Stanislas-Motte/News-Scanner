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
        cfg = yaml.safe_load(f)
    # Instructions live in a separate plain-text file for easy editing.
    if cfg.get("context_file"):
        cfg["context"] = (ROOT / cfg["context_file"]).read_text()
    return cfg

def build_prompt(cfg: dict) -> str:
    sites = "\n".join(f"- {s}" for s in cfg["sites"])
    return f"""You are a carbon market hedge fund news analyst. Today is {date.today().isoformat()}.

My context — only report what is relevant to this:
{cfg["context"]}

Visit and read the following news sites:
{sites}

Instructions:
- Fetch each site and focus on articles from the last 24-48 hours.
- Summarize ONLY items relevant to my context. Skip everything else.
- Follow the output format and guidance in my context exactly; it is the single source of truth for structure.
- Cite a source and publishing time for every item, as shown in my context.
- If nothing relevant was published, say so explicitly in one line.
- Use a professional, formal, informative, and concise tone. Do not use emojis, colors, or decorative indicators.
- Output clean, readable Markdown."""

def run_claude(cfg: dict, prompt: str) -> str:
    client = Anthropic()  # uses ANTHROPIC_API_KEY env var
    response = client.messages.create(
        model=cfg["model"],
        max_tokens=cfg["max_tokens"],
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 20}],
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

    # "to" may be a single address (string) or a list of addresses.
    to = cfg["email"]["to"]
    if isinstance(to, str):
        to = [to]

    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": cfg["email"]["from"],
            "to": to,
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
