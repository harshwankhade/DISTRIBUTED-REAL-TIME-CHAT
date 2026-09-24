from __future__ import annotations

import unittest

from proto.chat.v1 import (
    admin_pb2,
    auth_pb2,
    channel_pb2,
    chat_pb2,
    file_pb2,
    health_pb2,
    llm_pb2,
    presence_pb2,
)


class ProtoContractTests(unittest.TestCase):
    def test_required_services_are_present(self) -> None:
        expected = {
            auth_pb2.DESCRIPTOR: {"AuthService"},
            channel_pb2.DESCRIPTOR: {"ChannelService"},
            chat_pb2.DESCRIPTOR: {"ChatService"},
            presence_pb2.DESCRIPTOR: {"PresenceService"},
            file_pb2.DESCRIPTOR: {"FileService"},
            admin_pb2.DESCRIPTOR: {"AdminService"},
            llm_pb2.DESCRIPTOR: {"LLMService"},
            health_pb2.DESCRIPTOR: {"HealthService"},
        }
        for descriptor, service_names in expected.items():
            with self.subTest(file=descriptor.name):
                self.assertEqual(set(descriptor.services_by_name), service_names)

    def test_chat_subscription_is_server_streaming(self) -> None:
        method = chat_pb2.DESCRIPTOR.services_by_name["ChatService"].methods_by_name[
            "SubscribeEvents"
        ]
        self.assertFalse(method.client_streaming)
        self.assertTrue(method.server_streaming)

    def test_file_contract_uses_chunked_streams(self) -> None:
        service = file_pb2.DESCRIPTOR.services_by_name["FileService"]
        self.assertTrue(service.methods_by_name["UploadFile"].client_streaming)
        self.assertTrue(service.methods_by_name["DownloadFile"].server_streaming)


if __name__ == "__main__":
    unittest.main()
