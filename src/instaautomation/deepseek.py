"""Summarizer adapter over DeepSeek's OpenAI-compatible chat API."""

import json
import os
from typing import Any

import httpx

from instaautomation.ports import EntryDraft, SummaryRequest

CHAT_COMPLETIONS = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-flash"
MAX_TOKENS = 8_000

SYSTEM_PROMPT = """\
You turn a short Instagram reel about AI tools into an entry for a personal knowledge base, \
filed under one of the owner's categories.

Reply with a single json object, exactly in this shape:

{
  "summary": "2-4 sentences: what the reel teaches",
  "problem": "the problem the reel solves, not the solution, in at most 12 words",
  "approach": "how the reel solves it, in at most 15 words",
  "technique": "the technique itself, explained so it can be applied without watching the reel",
  "steps": ["one concrete action per step"],
  "prerequisites": ["what must be installed, configured or known first"],
  "when_useful": "the situations where this technique pays off",
  "caveats": ["limits, risks, or claims that look doubtful"],
  "tools": ["named tools, products and models, e.g. Claude Code"],
  "tags": ["short lowercase keywords"],
  "category": "one category slug from the list, exactly"
}

Rules:
- Work only from the reel's transcript, caption and on-screen text. Never invent commands, flags, settings or steps.
- Keep steps concrete. Copy exact commands, prompts, file paths and config from the on-screen text verbatim, in backticks.
- On-screen text comes from OCR, so fix obvious OCR typos, but don't otherwise reword commands.
- An empty transcript means the reel has no speech: rely on the caption and on-screen text.
- Pick the category whose description fits the reel best. Use "other" only if none fits.
- Write problem and approach as single lines without line breaks.
- Write in English, even if the reel is in another language.
"""


class SummaryError(RuntimeError):
    """DeepSeek's reply couldn't be turned into an entry draft."""


class DeepSeekSummarizer:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=180)

    @classmethod
    def from_env(cls) -> "DeepSeekSummarizer":
        return cls(api_key=os.environ["DEEPSEEK_API_KEY"])

    def summarize(self, request: SummaryRequest) -> EntryDraft:
        response = self._client.post(
            CHAT_COMPLETIONS,
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": _user_prompt(request)},
                ],
                "response_format": {"type": "json_object"},
                # Thinking is on by default and costs output tokens; this is extraction, not reasoning.
                "thinking": {"type": "disabled"},
                "temperature": 0.3,
                # Set explicitly: a reply cut off at the limit is broken JSON.
                "max_tokens": MAX_TOKENS,
            },
        )
        if response.status_code != 200:
            raise SummaryError(f"DeepSeek {response.status_code}: {_error_message(response)}")
        choice = response.json()["choices"][0]
        if choice["finish_reason"] != "stop":
            raise SummaryError(f"DeepSeek reply incomplete: finish_reason {choice['finish_reason']}")
        content = choice["message"]["content"]
        # JSON mode blanks out a reply it couldn't make valid JSON, so a blank reply is a failed one.
        if not isinstance(content, str) or not content.strip():
            raise SummaryError("DeepSeek reply is empty")
        try:
            reply = json.loads(content)
        except ValueError as error:
            raise SummaryError(f"DeepSeek reply is not JSON: {error}") from None
        return _draft(reply)


def _user_prompt(request: SummaryRequest) -> str:
    categories = "\n".join(f"- {slug}: {description}" for slug, description in request.categories.items())
    return (
        f"# Reel by @{request.creator}\n\n"
        f"## Caption\n\n{request.caption or '(none)'}\n\n"
        f"## Transcript\n\n{request.transcript or '(empty: no speech)'}\n\n"
        f"## On-screen text\n\n{request.on_screen_text or '(none)'}\n\n"
        f"# Categories\n\n{categories}\n"
    )


def _draft(reply: object) -> EntryDraft:
    """Checks only the shape; whether the content makes sense for the knowledge base is the core's call."""
    entry = _object(reply, "reply")
    return EntryDraft(
        summary=_text(entry, "summary"),
        problem=_text(entry, "problem"),
        approach=_text(entry, "approach"),
        technique=_text(entry, "technique"),
        steps=_texts(entry, "steps"),
        prerequisites=_texts(entry, "prerequisites"),
        when_useful=_text(entry, "when_useful"),
        caveats=_texts(entry, "caveats"),
        tools=_texts(entry, "tools"),
        tags=_texts(entry, "tags"),
        category=_text(entry, "category"),
    )


def _object(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SummaryError(f"DeepSeek reply: {name} is not an object")
    return value


def _text(fields: dict[str, Any], name: str) -> str:
    value = fields.get(name)
    if not isinstance(value, str):
        raise SummaryError(f"DeepSeek reply: {name} is not text")
    return value


def _texts(fields: dict[str, Any], name: str) -> list[str]:
    value = fields.get(name)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SummaryError(f"DeepSeek reply: {name} is not a list of text")
    return value


def _error_message(response: httpx.Response) -> str:
    try:
        body: Any = response.json()
        message = body["error"]["message"]
    except (ValueError, KeyError, TypeError):
        message = response.text
    return str(message)[:120]
