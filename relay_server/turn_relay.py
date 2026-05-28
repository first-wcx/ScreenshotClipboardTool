"""
TURN relay for the ICC relay server.

Handles relay of binary data (images, files) between paired devices.
For the MVP phase (P2), this uses direct WebSocket forwarding rather than
standard TURN protocol. Future iterations may introduce WebRTC DataChannel.

Binary relay strategy:
- clipboard_sync_binary messages are forwarded as-is to paired devices
- file_stream_header + file_stream_data chunks are forwarded in order
- Maximum binary payload size is enforced (default: 32MB)
- Streaming data is forwarded chunk-by-chunk to minimize memory usage
"""

from __future__ import annotations

import json
import logging
import struct
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .config import RelayConfig
from .device_registry import DeviceRegistry

logger = logging.getLogger(__name__)

# Message type constants
MSG_TYPE_CLIPBOARD_SYNC_BINARY = "clipboard_sync_binary"
MSG_TYPE_FILE_STREAM_HEADER = "file_stream_header"
MSG_TYPE_FILE_STREAM_DATA = "file_stream_data"

# Stream state constants
STREAM_STATE_ACTIVE = "active"
STREAM_STATE_COMPLETED = "completed"
STREAM_STATE_ERROR = "error"

# Default chunk size (64KB, consistent with SYNC_STREAM_BUFFER)
DEFAULT_CHUNK_SIZE = 65536


@dataclass
class StreamState:
    """Tracks the state of an active file stream relay.

    Attributes:
        stream_id: Unique stream identifier from the file_stream_header.
        sender_device_id: Device ID that initiated the stream.
        total_size: Total size of all files in the stream.
        bytes_relayed: Number of bytes relayed so far.
        started_at: Epoch timestamp when the stream started.
        last_activity: Epoch timestamp of last chunk relayed.
        state: Current stream state (active/completed/error).
        target_devices: Set of device IDs to relay to.
        file_count: Number of files in the stream.
    """

    stream_id: str
    sender_device_id: str
    total_size: int = 0
    bytes_relayed: int = 0
    started_at: float = 0.0
    last_activity: float = 0.0
    state: str = STREAM_STATE_ACTIVE
    target_devices: Set[str] = field(default_factory=set)
    file_count: int = 0


class TurnRelay:
    """TURN-style relay for binary data forwarding between paired devices.

    Handles:
    - clipboard_sync_binary message relay (large image data)
    - file_stream_header / file_stream_data chunked relay
    - Stream state tracking and cleanup
    - Size limit enforcement
    - Bandwidth tracking
    """

    def __init__(
        self,
        registry: DeviceRegistry,
        config: RelayConfig,
    ) -> None:
        """Initialize the TurnRelay.

        Args:
            registry: Device registry for looking up paired devices.
            config: Relay server configuration.
        """
        self.registry = registry
        self.config = config

        # Active streams: stream_id -> StreamState
        self._active_streams: Dict[str, StreamState] = {}

        # Bandwidth tracking: device_id -> bytes relayed in current window
        self._bandwidth_usage: Dict[str, int] = {}

        # Bandwidth tracking window start time
        self._bandwidth_window_start: float = time.time()

    async def relay_binary_message(
        self,
        sender_device_id: str,
        raw_data: bytes,
    ) -> int:
        """Relay a clipboard_sync_binary message to all paired devices.

        Args:
            sender_device_id: The device that sent the binary message.
            raw_data: The raw binary frame data.

        Returns:
            Number of devices the message was relayed to.
        """
        # Check size limit
        if len(raw_data) > self.config.max_message_size:
            logger.warning(
                "Binary message too large from %s: %d > %d",
                sender_device_id, len(raw_data), self.config.max_message_size,
            )
            return 0

        # Decode header to check binary_length
        try:
            header_len = struct.unpack("!H", raw_data[:2])[0]
            header = json.loads(raw_data[2:2 + header_len].decode("utf-8"))
            binary_length = header.get("binary_length", 0)

            if binary_length > self.config.max_binary_size:
                logger.warning(
                    "Binary payload too large from %s: %d > %d",
                    sender_device_id, binary_length, self.config.max_binary_size,
                )
                return 0
        except Exception as e:
            logger.warning("Failed to decode binary message from %s: %s", sender_device_id, e)
            return 0

        # Relay to paired devices
        relayed_count = 0
        paired_devices = self.registry.get_paired_devices(sender_device_id)
        for paired in paired_devices:
            if paired.is_online:
                ws = self.registry.get_websocket(paired.device_id)
                if ws:
                    try:
                        await ws.send_bytes(raw_data)
                        relayed_count += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to relay binary to %s: %s",
                            paired.device_id, e,
                        )

        # Track bandwidth
        self._track_bandwidth(sender_device_id, len(raw_data))

        logger.debug(
            "Relayed binary message from %s to %d devices (%d bytes)",
            sender_device_id, relayed_count, len(raw_data),
        )
        return relayed_count

    async def handle_stream_header(
        self,
        sender_device_id: str,
        raw_data: bytes,
    ) -> bool:
        """Handle a file_stream_header message.

        Creates a new StreamState and relays the header to paired devices.

        Args:
            sender_device_id: The device that sent the stream header.
            raw_data: The raw binary frame data.

        Returns:
            True if the stream was accepted and relayed.
        """
        # Decode the header
        try:
            header_len = struct.unpack("!H", raw_data[:2])[0]
            header = json.loads(raw_data[2:2 + header_len].decode("utf-8"))
            payload = header.get("payload", {})
            stream_id = payload.get("stream_id", "")
            total_size = payload.get("total_size", 0)
            files = payload.get("files", [])
        except Exception as e:
            logger.warning("Failed to decode stream header from %s: %s", sender_device_id, e)
            return False

        if not stream_id:
            logger.warning("Missing stream_id from %s", sender_device_id)
            return False

        # Check total size limit
        if total_size > self.config.max_binary_size * 2:  # Allow 2x for file streams
            logger.warning(
                "Stream total size too large from %s: %d",
                sender_device_id, total_size,
            )
            return False

        # Create stream state
        target_devices = set()
        paired_devices = self.registry.get_paired_devices(sender_device_id)
        for paired in paired_devices:
            if paired.is_online:
                target_devices.add(paired.device_id)

        if not target_devices:
            logger.warning("No online paired devices for stream from %s", sender_device_id)
            return False

        stream_state = StreamState(
            stream_id=stream_id,
            sender_device_id=sender_device_id,
            total_size=total_size,
            started_at=time.time(),
            last_activity=time.time(),
            target_devices=target_devices,
            file_count=len(files),
        )
        self._active_streams[stream_id] = stream_state

        # Relay the header to target devices
        for device_id in target_devices:
            ws = self.registry.get_websocket(device_id)
            if ws:
                try:
                    await ws.send_bytes(raw_data)
                except Exception as e:
                    logger.warning(
                        "Failed to relay stream header to %s: %s",
                        device_id, e,
                    )

        logger.info(
            "Stream started: %s from %s, %d files, %d bytes, %d targets",
            stream_id, sender_device_id, len(files), total_size, len(target_devices),
        )
        return True

    async def handle_stream_data(
        self,
        sender_device_id: str,
        raw_data: bytes,
    ) -> bool:
        """Handle a file_stream_data chunk.

        Validates the chunk belongs to an active stream and relays it.

        Args:
            sender_device_id: The device that sent the stream chunk.
            raw_data: The raw binary frame data.

        Returns:
            True if the chunk was accepted and relayed.
        """
        # Decode the header
        try:
            header_len = struct.unpack("!H", raw_data[:2])[0]
            header = json.loads(raw_data[2:2 + header_len].decode("utf-8"))
            payload = header.get("payload", {})
            stream_id = payload.get("stream_id", "")
            is_last_chunk = payload.get("is_last_chunk", False)
        except Exception as e:
            logger.warning("Failed to decode stream data from %s: %s", sender_device_id, e)
            return False

        # Look up stream state
        stream = self._active_streams.get(stream_id)
        if not stream:
            logger.warning("Unknown stream %s from %s", stream_id, sender_device_id)
            return False

        if stream.sender_device_id != sender_device_id:
            logger.warning("Stream %s sender mismatch: %s vs %s", stream_id, stream.sender_device_id, sender_device_id)
            return False

        if stream.state != STREAM_STATE_ACTIVE:
            logger.warning("Stream %s is not active: %s", stream_id, stream.state)
            return False

        # Update stream state
        chunk_size = len(raw_data) - 2 - header_len
        stream.bytes_relayed += max(0, chunk_size)
        stream.last_activity = time.time()

        # Relay to target devices
        for device_id in stream.target_devices:
            ws = self.registry.get_websocket(device_id)
            if ws:
                try:
                    await ws.send_bytes(raw_data)
                except Exception as e:
                    logger.warning(
                        "Failed to relay stream data to %s: %s",
                        device_id, e,
                    )

        # Check if stream is complete
        if is_last_chunk and stream.bytes_relayed >= stream.total_size:
            stream.state = STREAM_STATE_COMPLETED
            logger.info(
                "Stream completed: %s, %d bytes relayed",
                stream_id, stream.bytes_relayed,
            )
            # Clean up completed stream after a delay
            self._schedule_cleanup(stream_id)

        # Track bandwidth
        self._track_bandwidth(sender_device_id, len(raw_data))

        return True

    def get_active_streams(self) -> List[StreamState]:
        """Get the list of active streams.

        Returns:
            List of active StreamState objects.
        """
        return list(self._active_streams.values())

    def get_stream_state(self, stream_id: str) -> Optional[StreamState]:
        """Get the state of a specific stream.

        Args:
            stream_id: The stream ID to look up.

        Returns:
            The StreamState if found, None otherwise.
        """
        return self._active_streams.get(stream_id)

    def get_bandwidth_usage(self, device_id: str) -> int:
        """Get the bandwidth usage for a device in the current window.

        Args:
            device_id: The device ID to query.

        Returns:
            Number of bytes relayed in the current window.
        """
        return self._bandwidth_usage.get(device_id, 0)

    def cleanup_stale_streams(self, max_idle_seconds: int = 300) -> None:
        """Remove stale streams that have been idle for too long.

        Args:
            max_idle_seconds: Maximum idle time in seconds before cleanup.
        """
        now = time.time()
        stale_ids = [
            sid for sid, stream in self._active_streams.items()
            if now - stream.last_activity > max_idle_seconds
        ]
        for sid in stale_ids:
            stream = self._active_streams.pop(sid)
            stream.state = STREAM_STATE_ERROR
            logger.warning("Cleaned up stale stream: %s", sid)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _track_bandwidth(self, device_id: str, bytes_count: int) -> None:
        """Track bandwidth usage for a device.

        Args:
            device_id: The device ID.
            bytes_count: Number of bytes relayed.
        """
        # Reset bandwidth window every 60 seconds
        now = time.time()
        if now - self._bandwidth_window_start > 60:
            self._bandwidth_usage.clear()
            self._bandwidth_window_start = now

        self._bandwidth_usage[device_id] = (
            self._bandwidth_usage.get(device_id, 0) + bytes_count
        )

    def _schedule_cleanup(self, stream_id: str) -> None:
        """Schedule cleanup of a completed stream.

        In a production system, this would use an async task with a delay.
        For simplicity, we just mark it for cleanup.

        Args:
            stream_id: The stream ID to clean up.
        """
        # Remove immediately for MVP; in production, delay removal
        self._active_streams.pop(stream_id, None)
