"""Inbox adapter over the Telegram Bot API."""

import os
from typing import Any

import httpx

from instaautomation.ports import Message, MessageRef

# Bots may only react with Telegram's fixed emoji set, which has neither ✅ nor ❌.
REACTIONS = {"✅": "👍", "❌": "👎"}


class TelegramError(RuntimeError):
    """The Bot API refused a call."""


class TelegramInbox:
    def __init__(self, token: str, owner_id: int, client: httpx.Client | None = None) -> None:
        self._base = f"https://api.telegram.org/bot{token}"
        self._owner_id = owner_id
        self._client = client or httpx.Client(timeout=30)

    @classmethod
    def from_env(cls) -> "TelegramInbox":
        return cls(token=os.environ["TELEGRAM_BOT_TOKEN"], owner_id=int(os.environ["TELEGRAM_OWNER_ID"]))

    def fetch_messages(self, offset: int) -> list[Message]:
        # One call only: asking again with a higher offset would confirm, and so delete,
        # updates on Telegram's side before the core has saved them to the queue.
        updates = self._call("getUpdates", {"offset": offset, "limit": 100, "timeout": 0, "allowed_updates": ["message"]})
        return [self._message(update) for update in updates]

    def _message(self, update: dict[str, Any]) -> Message:
        """Every update becomes a Message, so the core's offset moves past updates the adapter drops."""
        message = update.get("message") or {}
        sender_id = (message.get("from") or {}).get("id", 0)
        text = message.get("text") or message.get("caption") or ""
        return Message(
            update_id=update["update_id"],
            message_id=message.get("message_id", 0),
            chat_id=(message.get("chat") or {}).get("id", 0),
            sender_id=sender_id,
            # Defence in depth: nobody but the owner can get a link in front of the core.
            text=text if sender_id == self._owner_id else "",
        )

    def react(self, ref: MessageRef, emoji: str, reason: str | None = None) -> None:
        reaction = [{"type": "emoji", "emoji": REACTIONS.get(emoji, emoji)}]
        self._call("setMessageReaction", {"chat_id": ref.chat_id, "message_id": ref.message_id, "reaction": reaction})
        if reason:
            # A reaction can't carry text, so the reason goes in a reply to the shared message.
            self._call("sendMessage", {"chat_id": ref.chat_id, "text": reason, "reply_parameters": {"message_id": ref.message_id}})

    def _call(self, method: str, payload: dict[str, Any]) -> Any:
        response = self._client.post(f"{self._base}/{method}", json=payload)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if not body.get("ok"):
            # The URL holds the bot token, so only the method name goes in the error.
            raise TelegramError(f"{method} failed ({response.status_code}): {body.get('description', 'no description')}")
        return body["result"]
