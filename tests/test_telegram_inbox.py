import json
from typing import Any

import httpx
import pytest

from instaautomation.ports import Message, MessageRef
from instaautomation.telegram import TelegramError, TelegramInbox

OWNER_ID = 1001
STRANGER_ID = 666
CHAT_ID = OWNER_ID  # a private chat's ID is the user's ID


class FakeTelegram:
    """Answers Bot API calls from canned updates and records every request."""

    def __init__(self, updates: list[dict[str, Any]] | None = None) -> None:
        self.updates = updates or []
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.reject_reactions = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content) if request.content else {}
        self.calls.append((method, body))
        if method == "getUpdates":
            offset = body.get("offset", 0)
            return httpx.Response(200, json={"ok": True, "result": [u for u in self.updates if u["update_id"] >= offset]})
        if method == "setMessageReaction" and self.reject_reactions:
            return httpx.Response(400, json={"ok": False, "description": "Bad Request: REACTION_INVALID"})
        return httpx.Response(200, json={"ok": True, "result": True})

    def calls_to(self, method: str) -> list[dict[str, Any]]:
        return [body for name, body in self.calls if name == method]


def inbox_for(telegram: FakeTelegram) -> TelegramInbox:
    return TelegramInbox(
        token="123:abc",
        owner_id=OWNER_ID,
        client=httpx.Client(transport=httpx.MockTransport(telegram.handle)),
    )


def text_update(update_id: int, text: str, sender: int = OWNER_ID, message_id: int | None = None) -> dict[str, Any]:
    return {
        "update_id": update_id,
        "message": {
            "message_id": message_id or update_id * 10,
            "from": {"id": sender, "is_bot": False, "first_name": "x"},
            "chat": {"id": sender, "type": "private"},
            "date": 0,
            "text": text,
        },
    }


def test_owner_messages_come_back_in_the_cores_shape() -> None:
    telegram = FakeTelegram([text_update(5, "https://www.instagram.com/reel/DAbc123XyZ/")])

    messages = inbox_for(telegram).fetch_messages(0)

    assert messages == [
        Message(update_id=5, message_id=50, chat_id=OWNER_ID, sender_id=OWNER_ID, text="https://www.instagram.com/reel/DAbc123XyZ/")
    ]


def test_fetches_from_the_persisted_offset_in_one_call() -> None:
    telegram = FakeTelegram([text_update(5, "old"), text_update(6, "new")])

    messages = inbox_for(telegram).fetch_messages(6)

    assert [m.update_id for m in messages] == [6]
    # Each getUpdates call with a higher offset confirms (deletes) older updates on Telegram's side,
    # so the adapter must never page ahead of what the core has saved.
    assert len(telegram.calls_to("getUpdates")) == 1
    assert telegram.calls_to("getUpdates")[0]["offset"] == 6


def test_every_update_since_the_offset_comes_back_oldest_first() -> None:
    telegram = FakeTelegram([text_update(5, "seen"), text_update(6, "reel one"), text_update(7, "chat"), text_update(8, "reel two")])

    messages = inbox_for(telegram).fetch_messages(6)

    assert [m.text for m in messages] == ["reel one", "chat", "reel two"]


def test_stranger_text_never_reaches_the_core_but_still_advances_the_offset() -> None:
    telegram = FakeTelegram([text_update(7, "https://www.instagram.com/reel/SPAM/", sender=STRANGER_ID)])

    messages = inbox_for(telegram).fetch_messages(0)

    assert [m.text for m in messages] == [""]
    assert max(m.update_id for m in messages) == 7


def test_updates_without_a_text_message_still_advance_the_offset() -> None:
    telegram = FakeTelegram([{"update_id": 8, "edited_message": {"message_id": 1}}])

    messages = inbox_for(telegram).fetch_messages(0)

    assert [(m.update_id, m.text) for m in messages] == [(8, "")]


def test_a_link_shared_with_media_is_read_from_the_caption() -> None:
    update = text_update(9, "")
    del update["message"]["text"]
    update["message"]["caption"] = "look https://www.instagram.com/reel/DAbc123XyZ/"
    telegram = FakeTelegram([update])

    messages = inbox_for(telegram).fetch_messages(0)

    assert messages[0].text == "look https://www.instagram.com/reel/DAbc123XyZ/"


def test_added_is_shown_as_a_thumbs_up_reaction() -> None:
    telegram = FakeTelegram()

    inbox_for(telegram).react(MessageRef(chat_id=CHAT_ID, message_id=50), "✅")

    assert telegram.calls_to("setMessageReaction") == [
        {"chat_id": CHAT_ID, "message_id": 50, "reaction": [{"type": "emoji", "emoji": "👍"}]}
    ]
    assert telegram.calls_to("sendMessage") == []


def test_failure_is_a_thumbs_down_plus_a_one_line_reply_with_the_reason() -> None:
    telegram = FakeTelegram()

    inbox_for(telegram).react(MessageRef(chat_id=CHAT_ID, message_id=50), "❌", "ReelSourceError: not found")

    assert telegram.calls_to("setMessageReaction")[0]["reaction"] == [{"type": "emoji", "emoji": "👎"}]
    assert telegram.calls_to("sendMessage") == [
        {"chat_id": CHAT_ID, "text": "ReelSourceError: not found", "reply_parameters": {"message_id": 50}}
    ]


def test_a_rejected_reaction_raises() -> None:
    telegram = FakeTelegram()
    telegram.reject_reactions = True

    with pytest.raises(TelegramError, match="REACTION_INVALID"):
        inbox_for(telegram).react(MessageRef(chat_id=CHAT_ID, message_id=50), "✅")


def test_the_failure_reason_is_still_sent_when_the_reaction_is_rejected() -> None:
    telegram = FakeTelegram()
    telegram.reject_reactions = True

    with pytest.raises(TelegramError):
        inbox_for(telegram).react(MessageRef(chat_id=CHAT_ID, message_id=50), "❌", "ReelSourceError: not found")

    assert [body["text"] for body in telegram.calls_to("sendMessage")] == ["ReelSourceError: not found"]
