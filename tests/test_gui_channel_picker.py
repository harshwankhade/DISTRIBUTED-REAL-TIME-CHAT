"""Headless checks for the owner-channel add-member flow."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from client.api import ChatApi
from client.gui import ChatWindow, _owned_channels
from proto.chat.v1 import channel_pb2, common_pb2


class OwnerChannelPickerTests(unittest.TestCase):
    def test_only_signed_in_users_channels_are_offered(self) -> None:
        other = SimpleNamespace(channel_id="other", name="A", owner_id="someone-else")
        second = SimpleNamespace(channel_id="second", name="Zeta", owner_id="me")
        first = SimpleNamespace(channel_id="first", name="alpha", owner_id="me")
        self.assertEqual(
            [channel.channel_id for channel in _owned_channels([other, second, first], "me")],
            ["first", "second"],
        )

        window = ChatWindow.__new__(ChatWindow)
        window.root = object()
        window.current_user_id = "me"
        window.selected_channel_id = "other"  # selection must not control the add
        window.user_list = SimpleNamespace(curselection=lambda: (0,))
        window.users = [SimpleNamespace(user_id="friend", username="bob")]
        window.api = Mock()
        window.api.list_channels.return_value = [other, second, first]
        window.api.list_members.return_value = []
        window._set_status = Mock()
        window._refresh_members = Mock()

        def choose(_parent, username, channels):
            self.assertEqual(username, "bob")
            self.assertEqual([channel.channel_id for channel in channels], ["first", "second"])
            return SimpleNamespace(result=second)

        with patch("client.gui._ChannelPicker", side_effect=choose):
            window._add_selected_user()
        window.api.manage_member.assert_called_once_with("second", "friend", True)
        window._refresh_members.assert_not_called()  # another channel is selected

    def test_no_owned_channel_does_not_add_user(self) -> None:
        window = ChatWindow.__new__(ChatWindow)
        window.user_list = SimpleNamespace(curselection=lambda: (0,))
        window.users = [SimpleNamespace(user_id="friend", username="bob")]
        window.current_user_id = "me"
        window.api = Mock()
        window.api.list_channels.return_value = [
            SimpleNamespace(channel_id="other", name="Other", owner_id="someone-else")
        ]
        with patch("client.gui.messagebox.showinfo") as notice, patch("client.gui._ChannelPicker") as picker:
            window._add_selected_user()
        notice.assert_called_once()
        picker.assert_not_called()
        window.api.manage_member.assert_not_called()

    def test_channel_api_collects_every_page(self) -> None:
        api = ChatApi("127.0.0.1:1", timeout_seconds=1, chunk_size=1024)
        try:
            first = channel_pb2.ListChannelsResponse(
                channels=[common_pb2.ChannelSummary(channel_id="one", name="One")],
                next_page_token="next",
            )
            second = channel_pb2.ListChannelsResponse(
                channels=[common_pb2.ChannelSummary(channel_id="two", name="Two")],
            )
            with patch("client.api.channel_pb2_grpc.ChannelServiceStub") as stub_type:
                stub_type.return_value.ListChannels.side_effect = [first, second]
                result = api.list_channels()
                requests = [call.args[0] for call in stub_type.return_value.ListChannels.call_args_list]
            self.assertEqual([channel.channel_id for channel in result], ["one", "two"])
            self.assertEqual([request.page_token for request in requests], ["", "next"])
        finally:
            api.close()


if __name__ == "__main__":
    unittest.main()
