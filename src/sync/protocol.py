"""
Sync protocol definition and codec for the ICC multi-device sync system.

Defines the binary frame protocol for WebSocket messages:
  2-byte header length (big-endian uint16) + header JSON bytes + optional binary payload

Also provides compatibility with the existing serialize_item_for_sync /
deserialize_synced_item format from clipboard_viewer.py.
"""

from __future__ import annotations

import base64
import json
import struct
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

VERSION: int = 1

# Message type constants
MSG_TYPE_HELLO = "hello"
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

# Sync thresholds (consistent with clipboard_viewer.py)
SYNC_MAX_IMAGE_BYTES = 32 * 1024 * 1024
SYNC_BINARY_THRESHOLD = 1 * 1024 * 1024  # 1 MB


# ---------------------------------------------------------------------------
# SyncMessage dataclass
# ---------------------------------------------------------------------------

@dataclass
class SyncMessage:
    """Represents a sync message exchanged between devices via WebSocket.

    Attributes:
        version: Protocol version (currently 1).
        type: Message type string.
        origin: Device ID of the sender.
        timestamp: ISO 8601 UTC timestamp string.
        payload: Message payload dictionary.
        binary_length: Length of trailing binary payload in bytes (0 if none).
    """

    version: int = VERSION
    type: str = ""
    origin: str = ""
    timestamp: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    binary_length: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert this message to a dict suitable for JSON serialization."""
        return {
            "version": self.version,
            "type": self.type,
            "origin": self.origin,
            "timestamp": self.timestamp,
            "payload": self.payload,
            "binary_length": self.binary_length,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SyncMessage":
        """Create a SyncMessage from a dict (typically parsed from JSON)."""
        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}
        return cls(
            version=int(data.get("version", VERSION)),
            type=str(data.get("type", "")),
            origin=str(data.get("origin", "")),
            timestamp=str(data.get("timestamp", "")),
            payload=payload,
            binary_length=int(data.get("binary_length", 0)),
        )


# ---------------------------------------------------------------------------
# ProtocolCodec — static encode / decode methods
# ---------------------------------------------------------------------------

class ProtocolCodec:
    """Static utility class for encoding/decoding sync messages.

    Binary frame protocol:
        [2 bytes: header length (big-endian uint16)]
        [N bytes: header JSON (UTF-8)]
        [M bytes: binary payload (optional)]

    The header JSON must contain: version, type, origin, timestamp, payload, binary_length.
    """

    @staticmethod
    def encode_message(
        msg: SyncMessage,
        binary_payload: Optional[bytes] = None,
    ) -> bytes:
        """Encode a SyncMessage (with optional binary payload) into a byte array.

        Args:
            msg: The SyncMessage to encode.
            binary_payload: Optional binary data (e.g., raw image bytes).

        Returns:
            Encoded byte array ready to send over WebSocket.

        Raises:
            ValueError: If the header JSON exceeds 65535 bytes.
        """
        header_json = json.dumps(msg.to_dict(), ensure_ascii=False, separators=(",", ":"))
        header_bytes = header_json.encode("utf-8")

        if len(header_bytes) > 65535:
            raise ValueError(
                f"Header JSON exceeds 65535 bytes (was {len(header_bytes)})"
            )

        header_length = len(header_bytes)
        parts: list[bytes] = []

        # 2-byte header length (big-endian uint16)
        parts.append(struct.pack("!H", header_length))

        # Header JSON bytes
        parts.append(header_bytes)

        # Binary payload (if present)
        if binary_payload:
            parts.append(binary_payload)

        return b"".join(parts)

    @staticmethod
    def decode_message(data: bytes) -> Tuple[SyncMessage, Optional[bytes]]:
        """Decode a byte array from WebSocket into a SyncMessage and optional binary payload.

        Args:
            data: Raw byte array received from WebSocket.

        Returns:
            A tuple of (SyncMessage, binary_payload or None).

        Raises:
            ValueError: If the data is too short or header is invalid.
        """
        if len(data) < 2:
            raise ValueError("Data too short: expected at least 2 bytes for header length")

        # Read 2-byte header length (big-endian uint16)
        header_length = struct.unpack("!H", data[:2])[0]

        if len(data) < 2 + header_length:
            raise ValueError(
                f"Data too short: expected {2 + header_length} bytes, got {len(data)}"
            )

        # Read header JSON bytes
        header_bytes = data[2 : 2 + header_length]
        header_json = header_bytes.decode("utf-8")
        header_dict = json.loads(header_json)

        msg = SyncMessage.from_dict(header_dict)

        # Read binary payload (if indicated by binary_length)
        binary_payload: Optional[bytes] = None
        if msg.binary_length > 0:
            binary_start = 2 + header_length
            binary_end = binary_start + msg.binary_length
            if len(data) >= binary_end:
                binary_payload = data[binary_start:binary_end]
            elif len(data) > binary_start:
                # Incomplete binary payload — return what we have
                binary_payload = data[binary_start:]

        return msg, binary_payload

    @staticmethod
    def encode_clipboard_item(
        item_type: str,
        item_dict: Dict[str, Any],
        origin: str = "",
    ) -> Tuple[SyncMessage, Optional[bytes]]:
        """Encode a clipboard item into a SyncMessage, compatible with the
        existing serialize_item_for_sync format from clipboard_viewer.py.

        For text items: produces a "clipboard_sync" message with text in payload.
        For image items <= 1MB: produces a "clipboard_sync" message with base64 DIB in payload.
        For image items > 1MB: produces a "clipboard_sync_binary" message with binary payload.

        Args:
            item_type: The item type ("text", "image", or "files").
            item_dict: The item data dict (compatible with serialize_item_for_sync output).
            origin: This device's node ID.

        Returns:
            A tuple of (SyncMessage, optional binary payload bytes).
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        if item_type == "text":
            msg = SyncMessage(
                type=MSG_TYPE_CLIPBOARD_SYNC,
                origin=origin,
                timestamp=now,
                payload={
                    "item_type": "text",
                    "item": item_dict,
                },
                binary_length=0,
            )
            return msg, None

        if item_type == "image":
            size = item_dict.get("size", 0)
            # If item has raw_bytes key, use binary frame for large images
            raw_bytes = item_dict.get("_raw_bytes")
            if raw_bytes and size > SYNC_BINARY_THRESHOLD:
                # Large image: use binary frame
                item_for_payload = {k: v for k, v in item_dict.items() if k != "_raw_bytes"}
                msg = SyncMessage(
                    type=MSG_TYPE_CLIPBOARD_SYNC_BINARY,
                    origin=origin,
                    timestamp=now,
                    payload={
                        "item_type": "image",
                        "item": item_for_payload,
                    },
                    binary_length=len(raw_bytes),
                )
                return msg, raw_bytes

            # Small image or base64 embedded
            item_for_payload = {k: v for k, v in item_dict.items() if k != "_raw_bytes"}
            msg = SyncMessage(
                type=MSG_TYPE_CLIPBOARD_SYNC,
                origin=origin,
                timestamp=now,
                payload={
                    "item_type": "image",
                    "item": item_for_payload,
                },
                binary_length=0,
            )
            return msg, None

        # Default: files or other types
        msg = SyncMessage(
            type=MSG_TYPE_CLIPBOARD_SYNC,
            origin=origin,
            timestamp=now,
            payload={
                "item_type": item_type,
                "item": item_dict,
            },
            binary_length=0,
        )
        return msg, None

    @staticmethod
    def decode_clipboard_item(
        msg: SyncMessage,
        binary_payload: Optional[bytes] = None,
    ) -> Tuple[str, Dict[str, Any]]:
        """Decode a received sync message back into an item type and data dict,
        compatible with the existing deserialize_synced_item format.

        Args:
            msg: The received SyncMessage.
            binary_payload: Optional binary payload (for clipboard_sync_binary messages).

        Returns:
            A tuple of (item_type, item_data_dict).
        """
        item_type = msg.payload.get("item_type", "")
        item_data = msg.payload.get("item", {})

        if not isinstance(item_data, dict):
            item_data = {}

        # For binary image messages, reconstruct the image data
        if msg.type == MSG_TYPE_CLIPBOARD_SYNC_BINARY and binary_payload:
            if item_type == "image":
                # Convert raw binary to base64 DIB for compatibility with
                # the existing deserialize_synced_item format
                item_data["dib_b64"] = base64.b64encode(binary_payload).decode("ascii")
                item_data["size"] = len(binary_payload)

        return item_type, item_data
