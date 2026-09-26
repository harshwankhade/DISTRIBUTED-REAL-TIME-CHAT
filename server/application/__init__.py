"""Transport-independent application services through Phase 3."""

from server.application.admin import AdminApplication
from server.application.auth import AuthApplication
from server.application.channels import ChannelApplication

__all__ = ["AdminApplication", "AuthApplication", "ChannelApplication"]
