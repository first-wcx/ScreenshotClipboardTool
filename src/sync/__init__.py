"""
ICC Sync Module — Multi-device WebSocket synchronization.

This module provides the sync protocol, device management,
authentication, WebSocket server/client, mDNS advertising,
pairing server, and the SyncManagerV2 coordinator for the
Integrated Capture Clipboard multi-device synchronization system.
"""

from .protocol import SyncMessage, ProtocolCodec
from .device_manager import DeviceInfo, DeviceManager
from .auth import (
    generate_challenge,
    compute_hmac,
    verify_hmac,
    generate_pairing_token,
    generate_shared_secret,
)
from .websocket_server import WebSocketServer
from .websocket_client import WebSocketClient
from .sync_manager_v2 import SyncManagerV2, SyncConfig
from .mdns_advertiser import MdnsAdvertiser
from .pairing_server import PairingServer

__all__ = [
    "SyncMessage",
    "ProtocolCodec",
    "DeviceInfo",
    "DeviceManager",
    "generate_challenge",
    "compute_hmac",
    "verify_hmac",
    "generate_pairing_token",
    "generate_shared_secret",
    "WebSocketServer",
    "WebSocketClient",
    "SyncManagerV2",
    "SyncConfig",
    "MdnsAdvertiser",
    "PairingServer",
]
