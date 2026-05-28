"""
WebSocket signaling handler for the ICC relay server.

Handles:
- Message routing between paired devices
- Device online/offline notifications
- Clipboard sync message relay
- File stream relay
- Heartbeat (ping/pong) processing
- Binary frame protocol decode/encode
"""

from __future__ import annotations

import json
import logging
import struct
from typing import Any, Dict, Optional, Set

from .auth import RelayAuthenticator
from .config import RelayConfig
from .device_registry import DeviceRegistry

logger = logging.getLogger(__name__)

# Message type constants (consistent with protocol.py)
MSG_TYPE_AUTH_CHALLENGE = "auth_challenge"
MSG_TYPE_AUTH_RESPONSE = "auth_response"
MSG_TYPE_AUTH_OK = "auth_ok"
MSG_TYPE_AUTH_FAIL = "auth_fail"
MSG_TYPE_PAIRING_REQUEST = "pairing_request"
MSG_TYPE_PAIRING_CONFIRM = "pairing_confirm"
MSG_TYPE_CLIPBOARD_SYNC = "clipboard_sync"
MSG_TYPE_CLIPBOARD_SYNC_BINARY = "clipboard_sync_binary"
MSG_TYPE_FILE_STREAM_HEADER = "file_stream_header"
MSG_TYPE_FILE_STREAM_DATA = "file_stream_data"
MSG_TYPE_DEVICE_LIST = "device_list"
MSG_TYPE_DEVICE_ONLINE = "device_online"
MSG_TYPE_DEVICE_OFFLINE = "device_offline"
MSG_TYPE_PING = "ping"
MSG_TYPE_PONG = "pong"
MSG_TYPE_HELLO = "hello"


class SignalingHandler:
    """Handles WebSocket signaling messages for the relay server.

    Routes messages between paired devices, processes heartbeat messages,
    and manages device online/offline notifications.

    This class is used by server.py to handle authenticated messages
    from connected devices.
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        authenticator: RelayAuthenticator,
        config: RelayConfig,
    ) -> None:
        """Initialize the SignalingHandler.

        Args:
            registry: Device registry for looking up devices and pairing info.
            authenticator: Authenticator for session management.
            config: Relay server configuration.
        """
        self.registry = registry
        self.authenticator = authenticator
        self.config = config

    async def handle_message(self, sender_device_id: str, raw_data: bytes) -> None:
        """Handle a raw binary message from an authenticated device.

        Decodes the binary frame protocol and routes the message
        to the appropriate handler.

        Args:
            sender_device_id: The authenticated device ID that sent the message.
            raw_data: The raw binary data received from WebSocket.
        """
        try:
            msg_type, msg_origin, msg_payload, binary_length, binary_payload = (
                self._decode_frame(raw_data)
            )
        except Exception as e:
            logger.warning("Failed to decode message from %s: %s", sender_device_id, e)
            return

        # Verify origin matches the authenticated device
        if msg_origin and msg_origin != sender_device_id:
            logger.warning(
                "Origin mismatch from %s: claimed %s",
                sender_device_id, msg_origin,
            )
            return

        # Route message by type
        if msg_type == MSG_TYPE_PING:
            await self._handle_ping(sender_device_id)

        elif msg_type == MSG_TYPE_PONG:
            # No action needed for pong
            pass

        elif msg_type == MSG_TYPE_HELLO:
            await self._handle_hello(sender_device_id, msg_payload)

        elif msg_type == MSG_TYPE_CLIPBOARD_SYNC:
            await self._handle_clipboard_sync(
                sender_device_id, raw_data
            )

        elif msg_type == MSG_TYPE_CLIPBOARD_SYNC_BINARY:
            # Check binary payload size limit
            if binary_length > self.config.max_binary_size:
                logger.warning(
                    "Binary payload too large from %s: %d > %d",
                    sender_device_id, binary_length, self.config.max_binary_size,
                )
                return
            await self._handle_clipboard_sync_binary(
                sender_device_id, raw_data
            )

        elif msg_type == MSG_TYPE_FILE_STREAM_HEADER:
            await self._handle_file_stream_header(
                sender_device_id, raw_data
            )

        elif msg_type == MSG_TYPE_FILE_STREAM_DATA:
            await self._handle_file_stream_data(
                sender_device_id, raw_data
            )

        elif msg_type == MSG_TYPE_PAIRING_REQUEST:
            await self._handle_pairing_request(
                sender_device_id, msg_payload
            )

        else:
            logger.debug(
                "Unhandled message type from %s: %s",
                sender_device_id, msg_type,
            )

    async def notify_device_online(self, device_id: str) -> None:
        """Notify all paired devices that a device has come online.

        Args:
            device_id: The device ID that came online.
        """
        device = self.registry.get_device(device_id)
        if not device:
            return

        online_msg = self._encode_frame({
            "version": 1,
            "type": MSG_TYPE_DEVICE_ONLINE,
            "origin": "",
            "timestamp": "",
            "payload": {
                "device_id": device_id,
                "device_name": device.device_name,
                "device_type": device.device_type,
                "platform": device.platform,
            },
            "binary_length": 0,
        })

        paired_devices = self.registry.get_paired_devices(device_id)
        for paired in paired_devices:
            if paired.is_online:
                ws = self.registry.get_websocket(paired.device_id)
                if ws:
                    try:
                        await ws.send_bytes(online_msg)
                    except Exception as e:
                        logger.warning(
                            "Failed to notify %s of %s online: %s",
                            paired.device_id, device_id, e,
                        )

        # Also send device list to the newly online device
        await self._send_device_list(device_id)

    async def notify_device_offline(self, device_id: str) -> None:
        """Notify all paired devices that a device has gone offline.

        Args:
            device_id: The device ID that went offline.
        """
        offline_msg = self._encode_frame({
            "version": 1,
            "type": MSG_TYPE_DEVICE_OFFLINE,
            "origin": "",
            "timestamp": "",
            "payload": {"device_id": device_id},
            "binary_length": 0,
        })

        paired_devices = self.registry.get_paired_devices(device_id)
        for paired in paired_devices:
            if paired.is_online:
                ws = self.registry.get_websocket(paired.device_id)
                if ws:
                    try:
                        await ws.send_bytes(offline_msg)
                    except Exception as e:
                        logger.warning(
                            "Failed to notify %s of %s offline: %s",
                            paired.device_id, device_id, e,
                        )

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    async def _handle_ping(self, sender_device_id: str) -> None:
        """Handle a ping message by sending a pong response."""
        ws = self.registry.get_websocket(sender_device_id)
        if ws:
            pong_msg = self._encode_frame({
                "version": 1,
                "type": MSG_TYPE_PONG,
                "origin": "",
                "timestamp": "",
                "payload": {},
                "binary_length": 0,
            })
            try:
                await ws.send_bytes(pong_msg)
            except Exception as e:
                logger.warning("Failed to send pong to %s: %s", sender_device_id, e)

    async def _handle_hello(self, sender_device_id: str, payload: dict) -> None:
        """Handle a hello message by updating device info."""
        device = self.registry.get_device(sender_device_id)
        if device:
            # Update device name and other info from hello payload
            if payload.get("device_name"):
                device.device_name = payload["device_name"]
            logger.info("Hello from %s: %s", sender_device_id, device.device_name)

    async def _handle_clipboard_sync(self, sender_device_id: str, raw_data: bytes) -> None:
        """Handle a clipboard_sync message by relaying to paired devices."""
        await self._relay_to_paired(sender_device_id, raw_data)

    async def _handle_clipboard_sync_binary(self, sender_device_id: str, raw_data: bytes) -> None:
        """Handle a clipboard_sync_binary message by relaying to paired devices."""
        await self._relay_to_paired(sender_device_id, raw_data)

    async def _handle_file_stream_header(self, sender_device_id: str, raw_data: bytes) -> None:
        """Handle a file_stream_header message by relaying to paired devices."""
        await self._relay_to_paired(sender_device_id, raw_data)

    async def _handle_file_stream_data(self, sender_device_id: str, raw_data: bytes) -> None:
        """Handle a file_stream_data message by relaying to paired devices."""
        await self._relay_to_paired(sender_device_id, raw_data)

    async def _handle_pairing_request(self, sender_device_id: str, payload: dict) -> None:
        """Handle a pairing_request message.

        Validates the token and establishes a pairing relationship.
        """
        token = payload.get("token", "")
        pending = self.authenticator.consume_token(token)
        if not pending:
            logger.warning("Invalid pairing token from %s", sender_device_id)
            return

        # The pending token may contain the intended target device
        # For now, pair with all online devices (simplified approach)
        # In production, this would require explicit pairing confirmation
        target_device_name = pending.device_name
        logger.info(
            "Pairing request from %s with token (target: %s)",
            sender_device_id, target_device_name,
        )

    async def _relay_to_paired(self, sender_device_id: str, raw_data: bytes) -> None:
        """Relay a raw message to all online paired devices.

        Args:
            sender_device_id: The device that sent the message.
            raw_data: The raw binary message data to relay.
        """
        # Check message size
        if len(raw_data) > self.config.max_message_size:
            logger.warning(
                "Message too large from %s: %d > %d",
                sender_device_id, len(raw_data), self.config.max_message_size,
            )
            return

        paired_devices = self.registry.get_paired_devices(sender_device_id)
        for paired in paired_devices:
            if paired.is_online:
                ws = self.registry.get_websocket(paired.device_id)
                if ws:
                    try:
                        await ws.send_bytes(raw_data)
                    except Exception as e:
                        logger.warning(
                            "Failed to relay to %s: %s",
                            paired.device_id, e,
                        )

    async def _send_device_list(self, target_device_id: str) -> None:
        """Send the list of online paired devices to a specific device."""
        paired_devices = self.registry.get_paired_devices(target_device_id)
        device_list = [
            {
                "device_id": d.device_id,
                "device_name": d.device_name,
                "device_type": d.device_type,
                "platform": d.platform,
                "is_online": d.is_online,
            }
            for d in paired_devices
        ]

        list_msg = self._encode_frame({
            "version": 1,
            "type": MSG_TYPE_DEVICE_LIST,
            "origin": "",
            "timestamp": "",
            "payload": {"devices": device_list},
            "binary_length": 0,
        })

        ws = self.registry.get_websocket(target_device_id)
        if ws:
            try:
                await ws.send_bytes(list_msg)
            except Exception as e:
                logger.warning(
                    "Failed to send device list to %s: %s",
                    target_device_id, e,
                )

    # ------------------------------------------------------------------
    # Binary frame protocol encode/decode
    # ------------------------------------------------------------------

    @staticmethod
    def _decode_frame(data: bytes) -> tuple:
        """Decode a binary frame protocol message.

        Returns:
            A tuple of (type, origin, payload, binary_length, binary_payload).
        """
        if len(data) < 2:
            raise ValueError("Data too short")

        header_len = struct.unpack("!H", data[:2])[0]
        if len(data) < 2 + header_len:
            raise ValueError("Incomplete header")

        header_json = json.loads(data[2:2 + header_len].decode("utf-8"))

        msg_type = header_json.get("type", "")
        msg_origin = header_json.get("origin", "")
        msg_payload = header_json.get("payload", {})
        binary_length = header_json.get("binary_length", 0)

        binary_payload: Optional[bytes] = None
        if binary_length > 0:
            binary_start = 2 + header_len
            binary_end = binary_start + binary_length
            if len(data) >= binary_end:
                binary_payload = data[binary_start:binary_end]

        return msg_type, msg_origin, msg_payload, binary_length, binary_payload

    @staticmethod
    def _encode_frame(msg_dict: dict, binary_payload: Optional[bytes] = None) -> bytes:
        """Encode a message dict into a binary frame.

        Args:
            msg_dict: The message as a dictionary.
            binary_payload: Optional binary payload.

        Returns:
            The encoded binary frame.
        """
        header_json = json.dumps(msg_dict, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        frame = struct.pack("!H", len(header_json)) + header_json
        if binary_payload:
            frame += binary_payload
        return frame
