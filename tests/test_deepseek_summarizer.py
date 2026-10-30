import json
from typing import Any

import httpx
import pytest

from instaautomation.deepseek import DeepSeekSummarizer, SummaryError
from instaautomation.ports import EntryDraft, SummaryRequest

REQUEST = SummaryRequest(
    transcript="Stop clicking approve on every command. Open your settings file and add the allowlist.",
    caption="Claude Code tip #12 🔥",
    on_screen_text="Stop clicking approve\nclaude --permission-mode plan",
    creator="aitipsdaily",
    categories={
        "coding-agents": "Claude Code, Cursor and other coding agents",
        "prompting": "Writing better prompts",
        "other": "Anything that fits no other category",
    },
)


def reply_content(**overrides: Any) -> dict[str, Any]:
    content: dict[str, Any] = {
        "summary": "Skip repeated permission prompts with an allowlist.",
        "problem": "Claude Code asks permission for every command",
        "approach": "allowlist trusted commands in settings",
        "technique": "Allowlist trusted commands in settings.",
        "steps": ["Open ~/.claude/settings.json", "Run `claude --permission-mode plan`"],
        "prerequisites": ["Claude Code installed"],
        "when_useful": "When approving the same command over and over.",
        "caveats": ["Don't allowlist destructive commands."],
        "tools": ["Claude Code"],
        "tags": ["permissions"],
        "category": "coding-agents",
    }
    content.update(overrides)
    return content


class FakeDeepSeek:
    def __init__(self, content: object = None, status: int = 200, finish_reason: str = "stop") -> None:
        self.content = reply_content() if content is None else content
        self.status = status
        self.finish_reason = finish_reason
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "Insufficient Balance", "type": "unknown"}})
        text = self.content if isinstance(self.content, str) else json.dumps(self.content)
        choice = {"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": self.finish_reason}
        return httpx.Response(200, json={"id": "x", "choices": [choice]})

    def sent(self) -> dict[str, Any]:
        body: dict[str, Any] = json.loads(self.requests[0].content)
        return body


def summarizer_for(deepseek: FakeDeepSeek) -> DeepSeekSummarizer:
    return DeepSeekSummarizer(api_key="sk-secret", client=httpx.Client(transport=httpx.MockTransport(deepseek.handle)))


def test_a_reply_becomes_an_entry_draft() -> None:
    draft = summarizer_for(FakeDeepSeek()).summarize(REQUEST)

    assert draft == EntryDraft(
        summary="Skip repeated permission prompts with an allowlist.",
        problem="Claude Code asks permission for every command",
        approach="allowlist trusted commands in settings",
        technique="Allowlist trusted commands in settings.",
        steps=["Open ~/.claude/settings.json", "Run `claude --permission-mode plan`"],
        prerequisites=["Claude Code installed"],
        when_useful="When approving the same command over and over.",
        caveats=["Don't allowlist destructive commands."],
        tools=["Claude Code"],
        tags=["permissions"],
        category="coding-agents",
    )


def test_asks_deepseek_for_json_given_the_reel_and_the_categories() -> None:
    deepseek = FakeDeepSeek()

    summarizer_for(deepseek).summarize(REQUEST)

    request = deepseek.requests[0]
    assert str(request.url) == "https://api.deepseek.com/chat/completions"
    assert request.headers["authorization"] == "Bearer sk-secret"
    sent = deepseek.sent()
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["thinking"] == {"type": "disabled"}
    prompt = "\n".join(message["content"] for message in sent["messages"])
    for given in [
        REQUEST.transcript,
        REQUEST.caption,
        "claude --permission-mode plan",
        REQUEST.creator,
        "coding-agents",
        "Claude Code, Cursor and other coding agents",
        "prompting",
    ]:
        assert given in prompt


def test_a_deepseek_error_is_a_short_failure_without_the_key() -> None:
    with pytest.raises(SummaryError, match="402.*Insufficient Balance") as raised:
        summarizer_for(FakeDeepSeek(status=402)).summarize(REQUEST)

    assert "sk-secret" not in str(raised.value)


def without(content: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: value for name, value in content.items() if name != key}


@pytest.mark.parametrize(
    ("content", "finish_reason"),
    [
        pytest.param("   ", "stop", id="blanked-out json"),
        pytest.param('{"summary": "Skip repeated', "length", id="cut off at max tokens"),
        pytest.param(reply_content(), "content_filter", id="filtered"),
        pytest.param("Here is the entry: summary...", "stop", id="not json"),
        pytest.param([reply_content()], "stop", id="not an object"),
        pytest.param(without(reply_content(), "caveats"), "stop", id="missing field"),
        pytest.param(reply_content(steps="Open settings"), "stop", id="steps not a list"),
        pytest.param(reply_content(tags=["ok", 3]), "stop", id="non-text tag"),
        pytest.param(reply_content(summary=None), "stop", id="summary not text"),
        pytest.param(without(reply_content(), "category"), "stop", id="no category"),
        pytest.param(reply_content(problem=["Too many prompts"]), "stop", id="problem not text"),
    ],
)
def test_an_unusable_reply_is_a_summary_failure(content: object, finish_reason: str) -> None:
    with pytest.raises(SummaryError):
        summarizer_for(FakeDeepSeek(content, finish_reason=finish_reason)).summarize(REQUEST)


def test_a_null_content_is_a_summary_failure() -> None:
    class NullContent(FakeDeepSeek):
        def handle(self, request: httpx.Request) -> httpx.Response:
            choice = {"index": 0, "message": {"role": "assistant", "content": None}, "finish_reason": "stop"}
            return httpx.Response(200, json={"choices": [choice]})

    with pytest.raises(SummaryError):
        summarizer_for(NullContent()).summarize(REQUEST)
