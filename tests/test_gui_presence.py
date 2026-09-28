"""Headless checks for presence labels and the member online count."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from client.api import ChatApi
from client.gui import ChatWindow, _online_member_count, _presence_text
from proto.chat.v1 import presence_pb2


class FakeListbox:
    def __init__(self) -> None:
        self.items: list[str] = []
        self.selected: tuple[int, ...] = ()
        self.scroll = 0.0

    def curselection(self):
        return self.selected

    def yview(self):
        return (self.scroll, 1.0)

    def delete(self, _start, _end):
        self.items.clear()
        self.selected = ()

    def insert(self, _index, value):
        self.items.append(value)

    def selection_set(self, index):
        self.selected = (index,)

    def yview_moveto(self, fraction):
        self.scroll = fraction


class FakeText:
    def __init__(self) -> None:
        self.value = ""

    def configure(self, **_kwargs):
        pass

    def delete(self, _start, _end):
        self.value = ""

    def insert(self, _index, value):
        self.value += value


class FakeLabel:
    def __init__(self) -> None:
        self.text = ""

    def configure(self, *, text):
        self.text = text


class GuiPresenceTests(unittest.TestCase):
    def test_registered_user_labels_preserve_selection(self) -> None:
        window = ChatWindow.__new__(ChatWindow)
        window.user_list = FakeListbox()
        window.users = [
            SimpleNamespace(user_id="alice", username="alice"),
            SimpleNamespace(user_id="bob", username="bob"),
        ]
        window.presence_by_user = {"alice": "online", "bob": "offline"}
        window.user_list.selected = (1,)
        window.user_list.scroll = 0.4
        window._render_users()
        self.assertEqual(window.user_list.items, ["alice (online)", "bob (offline)"])
        self.assertEqual(window.user_list.selected, (1,))
        self.assertEqual(window.user_list.scroll, 0.4)
        window.presence_by_user["bob"] = "unknown"
        window._render_users()
        self.assertEqual(window.user_list.items[1], "bob (unknown)")

    def test_member_labels_and_online_count_change_together(self) -> None:
        window = ChatWindow.__new__(ChatWindow)
        window.current_user_id = "viewer"
        window.visible_members = [
            SimpleNamespace(user_id="alice", username="alice"),
            SimpleNamespace(user_id="bob", username="bob"),
        ]
        window.presence_by_user = {"alice": "online", "bob": "offline"}
        window.members_header = FakeLabel()
        window.members_text = FakeText()
        channel = SimpleNamespace(owner_id="alice")
        window._render_members(channel)
        self.assertEqual(window.members_header.text, "Channel members (1 online)")
        self.assertEqual(window.members_text.value, "alice (online)\nbob (offline)\n")
        window.presence_by_user["bob"] = "online"
        window._render_members(channel)
        self.assertEqual(window.members_header.text, "Channel members (2 online)")

    def test_unknown_is_not_counted_as_offline_or_online(self) -> None:
        members = [
            SimpleNamespace(user_id="one", username="one"),
            SimpleNamespace(user_id="two", username="two"),
        ]
        self.assertEqual(_online_member_count(members, {"one": "online"}), 1)
        self.assertEqual(_presence_text(None), "unknown")
        self.assertEqual(_presence_text("network-error"), "unknown")
        window = ChatWindow.__new__(ChatWindow)
        window.current_user_id = "viewer"
        window.visible_members = members
        window.presence_by_user = {"one": "online"}
        window.members_header = FakeLabel()
        window.members_text = FakeText()
        window._render_members(SimpleNamespace(owner_id="one"))
        self.assertEqual(window.members_header.text, "Channel members (1 online, 1 unknown)")

    def test_client_uses_get_presence_rpc_for_requested_user(self) -> None:
        api = ChatApi("127.0.0.1:1", timeout_seconds=2, chunk_size=1024)
        try:
            with patch("client.api.presence_pb2_grpc.PresenceServiceStub") as stub_type:
                stub_type.return_value.GetPresence.return_value = presence_pb2.PresenceResponse(
                    user_id="bob", presence="online"
                )
                self.assertEqual(api.get_presence("bob"), "online")
                request = stub_type.return_value.GetPresence.call_args.args[0]
                self.assertEqual(request.user_id, "bob")
                self.assertEqual(stub_type.return_value.GetPresence.call_args.kwargs["timeout"], 2)
        finally:
            api.close()


if __name__ == "__main__":
    unittest.main()
