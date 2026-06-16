"""Shared utilities for news agents: config, Claude API, email, usage logging."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

import requests
import yaml
from anthropic import Anthropic

ROOT = Path(__file__).parent
RESULTS_DIR = ROOT / "results"
USAGE_LOG = RESULTS_DIR / "usage.log"

# USD per million tokens (input, output) — Anthropic API list prices.
MODEL_RATES: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-sonnet-4-6": (3.0, 15.0),
    "claude-sonnet-4-5": (3.0, 15.0),
}
WEB_SEARCH_COST_USD = 0.01


@dataclass
class Usage:
    input_tokens: int
    output_tokens: int
    web_fetch_requests: int
    web_search_requests: int

    @classmethod
    def from_response(cls, response) -> Usage:
        usage = response.usage
        tool_use = getattr(usage, "server_tool_use", None) or {}
        if hasattr(tool_use, "model_dump"):
            tool_use = tool_use.model_dump()
        elif not isinstance(tool_use, dict):
            tool_use = {}
        return cls(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            web_fetch_requests=tool_use.get("web_fetch_requests", 0) or 0,
            web_search_requests=tool_use.get("web_search_requests", 0) or 0,
        )


def load_config(config_path: Path | None = None) -> dict:
    path = config_path or ROOT / "config.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if cfg.get("context_file"):
        cfg["context"] = (ROOT / cfg["context_file"]).read_text()
    return cfg


def build_tools(cfg: dict) -> list[dict]:
    tools: list[dict] = []
    fetch_max = cfg.get("web_fetch_max_uses", 0)
    if fetch_max:
        tool: dict = {
            "type": "web_fetch_20260209",
            "name": "web_fetch",
            "max_uses": fetch_max,
        }
        if cfg.get("web_fetch_max_content_tokens"):
            tool["max_content_tokens"] = cfg["web_fetch_max_content_tokens"]
        tools.append(tool)
    search_max = cfg.get("web_search_max_uses", 0)
    if search_max:
        tools.append({
            "type": "web_search_20260209",
            "name": "web_search",
            "max_uses": search_max,
        })
    return tools


def run_claude(cfg: dict, prompt: str) -> tuple[str, Usage]:
    timeout = cfg.get("api_timeout_seconds", 480)
    client = Anthropic(timeout=timeout)
    tools = build_tools(cfg)
    if not tools:
        raise ValueError("At least one tool (web_fetch or web_search) must be configured")

    response = client.messages.create(
        model=cfg["model"],
        max_tokens=cfg["max_tokens"],
        tools=tools,
        messages=[{"role": "user", "content": prompt}],
    )
    text = "\n".join(b.text for b in response.content if b.type == "text")
    return text, Usage.from_response(response)


def estimate_cost(usage: Usage, model: str) -> float:
    input_rate, output_rate = MODEL_RATES.get(model, (3.0, 15.0))
    token_cost = (
        usage.input_tokens / 1_000_000 * input_rate
        + usage.output_tokens / 1_000_000 * output_rate
    )
    search_cost = usage.web_search_requests * WEB_SEARCH_COST_USD
    return token_cost + search_cost


def log_usage(usage: Usage, elapsed_seconds: float, cfg: dict) -> float:
    cost = estimate_cost(usage, cfg["model"])
    line = (
        f"{date.today().isoformat()} | "
        f"in={usage.input_tokens} out={usage.output_tokens} "
        f"fetch={usage.web_fetch_requests} search={usage.web_search_requests} | "
        f"est=${cost:.2f} | model={cfg['model']} | elapsed={elapsed_seconds:.0f}s"
    )
    print(f"USAGE {line.split(' | ', 1)[1]}")

    RESULTS_DIR.mkdir(exist_ok=True)
    with open(USAGE_LOG, "a") as f:
        f.write(line + "\n")

    max_cost = cfg.get("max_cost_usd")
    if max_cost is not None and cost > max_cost:
        print(f"WARNING: estimated cost ${cost:.2f} exceeds budget ${max_cost:.2f}")

    return cost


def save_result(digest: str) -> Path:
    RESULTS_DIR.mkdir(exist_ok=True)
    path = RESULTS_DIR / f"{date.today().isoformat()}.md"
    path.write_text(digest)
    return path


def format_usage_footer(usage: Usage, cost: float, elapsed_seconds: float) -> str:
    return (
        f"\n\n---\n*Run stats: {usage.input_tokens:,} input tokens, "
        f"{usage.output_tokens:,} output tokens, "
        f"{usage.web_fetch_requests} fetches, {usage.web_search_requests} searches, "
        f"est. ${cost:.2f}, {elapsed_seconds:.0f}s*"
    )


def send_email(cfg: dict, digest: str, footer: str = "") -> None:
    import markdown

    to = cfg["email"]["to"]
    if isinstance(to, str):
        to = [to]

    body = digest + footer
    resp = requests.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {os.environ['RESEND_API_KEY']}"},
        json={
            "from": cfg["email"]["from"],
            "to": to,
            "subject": f"{cfg['email']['subject_prefix']} — {date.today().isoformat()}",
            "html": markdown.markdown(body),
        },
        timeout=30,
    )
    resp.raise_for_status()
    print(f"Email sent: {resp.json().get('id')}")
