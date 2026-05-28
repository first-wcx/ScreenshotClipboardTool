"""
WebSocket client for the ICC multi-device sync system (desktop side).

Connects to other desktop peers or relay servers via WebSocket,
handles authentication, and relays clipboard sync messages.

Binary frame protocol (consistent with ProtocolCodec):
    [2 bytes: header length (big-endian uint16)]
    [N bytes: header JSON (UTF-8)]
    [M bytes: binary payload (optional)]
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional, Set, Tuple

import websockets
from websockets.client import WebSocketClientProtocol

from .protocol import (
    MSG_TYPE_AUTH_CHALLENGE,
    MSG_TYPE_AUTH_FAIL,
    MSG_TYPE_AUTH_OK,
    MSG_TYPE_CLIPBOARD_SYNC,
    MSG_TYPE_CLIPBOARD_SYNC_BINARY,
    MSG_TYPE_DEVICE_LIST,
    MSG_TYPE_DEVICE_OFFLINE,
    MSG_TYPE_DEVICE_ONLINE,
    MSG_TYPE_HELLO,
    MSG_TYPE_PAIRING_CONFIRM,
    MSG_TYPE_PAIRING_REQUEST,
    MSG_TYPE_PING,
    MSG_TYPE_PONG,
    ProtocolCodec,
    SyncMessage,
)
from .auth import compute_hmac, generate_challenge, verify_hmac
from .device_manager import DeviceInfo, DeviceManager

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client for connecting to sync peers or relay servers.

    Manages:
    - Outgoing WebSocket connections with automatic reconnection
    - HMAC-SHA256 authentication handshake (client side)
    - Message sending and receiving
    - Heartbeat (ping/pong) responses
    """

    def __init__(
        self,
        device_manager: Optional[DeviceManager] = None,
        secret_store: Optional[Dict[str, str]] = None,
        on_clipboard_sync: Optional[Callable] = None,
        on_device_online: Optional[Callable] = None,
        on_device_offline: Optional[Callable] = None,
        reconnect_interval: float = 5.0,
    ) -> None:
        """Initialize the WebSocket client.

        Args:
            device_manager: DeviceManager for looking up paired devices.
            secret_store: Dictionary mapping device IDs to shared secrets.
            on_clipboard_sync: Callback for clipboard sync messages.
            on_device_online: Callback when a remote device comes online.
            on_device_offline: Callback when a remote device goes offline.
            reconnect_interval: Base interval in seconds between reconnection attempts.
        """
        self.device_manager = device_manager or DeviceManager()
        self._secret_store = secret_store or {}
        self.on_clipboard_sync = on_clipboard_sync
        self.on_device_online = on_device_online
        self.on_device_offline = on_device_offline
        self.reconnect_interval = reconnect_interval

        # Active connections: device_id -> WebSocket
        self._connections: Dict[str, WebSocketClientProtocol] = {}

        # Connection state: device_id -> is_connected
        self._connected: Dict[str, bool] = {}

        # Authenticated device IDs
        self._authenticated: Set[str] = set()

        # Receive tasks: device_id -> asyncio.Task
        self._recv_tasks: Dict[str, asyncio.Task] = {}

        # Reconnect tasks: device_id -> asyncio.Task
        self._reconnect_tasks: Dict[str, asyncio.Task] = {}

        # Stop event
        self._stop_event = asyncio.Event()

        # This device's node ID
        self._node_id: str = ""

    def set_node_id(self, node_id: str) -> None:
        """Set this device's node ID for message origin field."""
        self._node_id = node_id

    async def connect(self, device_id: str, url: str) -> bool:
        """Connect to a WebSocket peer.

        Args:
            device_id: The device ID to associate with this connection.
            url: The WebSocket URL (e.g. "ws://192.168.1.100:8765").

        Returns:
            True if the connection was established (auth may still be pending).
        """
        # Cancel any existing reconnect task
        task = self._reconnect_tasks.pop(device_id, None)
        if task:
            task.cancel()

        try:
            ws = await websockets.connect(
                url,
                ping_interval=30.0,
                ping_timeout=10.0,
                max_size=64 * 1024 * 1024,
            )
            self._connections[device_id] = ws
            self._connected[device_id] = True
            logger.info("Connected to device: %s at %s", device_id, url)

            # Start receive loop
            self._recv_tasks[device_id] = asyncio.create_task(
                self._recv_loop(device_id, ws)
            )

            # Send hello to initiate authentication
            hello_msg = SyncMessage(
                type=MSG_TYPE_HELLO,
                origin=self._node_id,
                timestamp=self._now_iso(),
                payload={},
            )
            await ws.send(ProtocolCodec.encode_message(hello_msg))

            return True

        except Exception as e:
            logger.error("Failed to connect to %s at %s: %s", device_id, url, e)
            self._connected[device_id] = False
            return False

    async def disconnect(self, device_id: str) -> None:
        """Disconnect from a specific device.

        Args:
            device_id: The device ID to disconnect from.
        """
        # Cancel reconnect task
        task = self._reconnect_tasks.pop(device_id, None)
        if task:
            task.cancel()

        # Cancel receive task
        task = self._recv_tasks.pop(device_id, None)
        if task:
            task.cancel()

        # Close connection
        ws = self._connections.pop(device_id, None)
        if ws:
            try:
                await ws.close(1000, "Client disconnecting")
            except Exception:
                pass

        self._connected.pop(device_id, None)
        self._authenticated.discard(device_id)
        logger.info("Disconnected from device: %s", device_id)

    async def disconnect_all(self) -> None:
        """Disconnect from all devices."""
        device_ids = list(self._connections.keys())
        for device_id in device_ids:
            await self.disconnect(device_id)

    async def send(
        self,
        device_id: str,
        msg: SyncMessage,
        binary_payload: Optional[bytes] = None,
    ) -> bool:
        """Send a message to a specific device.

        Args:
            device_id: The target device ID.
            msg: The SyncMessage to send.
            binary_payload: Optional binary payload.

        Returns:
            True if the message was sent successfully.
        """
        ws = self._connections.get(device_id)
        if ws is None:
            return False

        try:
            encoded = ProtocolCodec.encode_message(msg, binary_payload)
            await ws.send(encoded)
            return True
        except Exception as e:
            logger.warning("Failed to send to %s: %s", device_id, e)
            return False

    def is_connected(self, device_id: str) -> bool:
        """Check if connected and authenticated with a device."""
        return device_id in self._authenticated

    def get_connected_device_ids(self) -> Set[str]:
        """Get the set of currently connected device IDs."""
        return set(self._authenticated)

    async def _recv_loop(self, device_id: str, ws: WebSocketClientProtocol) -> None:
        """Receive loop for a single WebSocket connection.

        Args:
            device_id: The device ID for this connection.
            ws: The WebSocket connection.
        """
        try:
            async for raw_message in ws:
                if isinstance(raw_message, str):
                    logger.warning("Received text frame from %s, ignoring", device_id)
                    continue

                data = bytes(raw_message)
                try:
                    msg, binary_payload = ProtocolCodec.decode_message(data)
                except Exception as e:
                    logger.warning("Failed to decode message from %s: %s", device_id, e)
                    continue

                await self._handle_message(device_id, msg, binary_payload)

        except websockets.exceptions.ConnectionClosed as e:
            logger.info("Connection closed for %s: code=%s", device_id, e.code)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in recv loop for %s: %s", device_id, e)
        finally:
            self._connected[device_id] = False
            self._authenticated.discard(device_id)
            self._connections.pop(device_id, None)
            logger.info("Receive loop ended for device: %s", device_id)

    async def _handle_message(
        self,
        device_id: str,
        msg: SyncMessage,
        binary_payload: Optional[bytes],
    ) -> None:
        """Handle a received message from a connected device.

        Args:
            device_id: The sender device ID.
            msg: The decoded SyncMessage.
            binary_payload: Optional binary payload.
        """
        if msg.type == MSG_TYPE_AUTH_CHALLENGE:
            await self._handle_auth_challenge(device_id, msg)

        elif msg.type == MSG_TYPE_AUTH_OK:
            self._authenticated.add(device_id)
            logger.info("Authenticated with device: %s", device_id)

        elif msg.type == MSG_TYPE_AUTH_FAIL:
            logger.warning("Authentication failed with device: %s", device_id)
            await self.disconnect(device_id)

        elif msg.type == MSG_TYPE_PONG:
            # Heartbeat response, no action needed
            pass

        elif msg.type == MSG_TYPE_DEVICE_ONLINE:
            if self.on_device_online:
                self.on_device_online(msg.payload)

        elif msg.type == MSG_TYPE_DEVICE_OFFLINE:
            if self.on_device_offline:
                self.on_device_offline(msg.payload)

        elif msg.type in (MSG_TYPE_CLIPBOARD_SYNC, MSG_TYPE_CLIPBOARD_SYNC_BINARY):
            if self.on_clipboard_sync:
                item_type = msg.payload.get("item_type", "")
                item_data = msg.payload.get("item", {})
                self.on_clipboard_sync(device_id, item_type, item_data, binary_payload)

        else:
            logger.debug("Unhandled message type from %s: %s", device_id, msg.type)

    async def _handle_auth_challenge(self, device_id: str, msg: SyncMessage) -> None:
        """Handle an auth_challenge by computing HMAC and sending auth_response.

        Args:
            device_id: The device that sent the challenge.
            msg: The auth_challenge message.
        """
        nonce = msg.payload.get("nonce", "")
        if not nonce:
            return

        secret = self._secret_store.get(device_id, "")
        if not secret:
            logger.warning("No shared secret for device: %s", device_id)
            return

        hmac_value = compute_hmac(secret, nonce)
        response_msg = SyncMessage(
            type=MSG_TYPE_AUTH_RESPONSE,
            origin=self._node_id,
            timestamp=self._now_iso(),
            payload={"hmac": hmac_value},
        )
        await self.send(device_id, response_msg)
        logger.debug("Auth response sent for device: %s", device_id)

    async def _reconnect_loop(self, device_id: str, url: str) -> None:
        """Attempt to reconnect to a device with exponential backoff.

        Args:
            device_id: The device ID to reconnect to.
            url: The WebSocket URL.
        """
        max_attempts = 10
        for attempt in range(1, max_attempts + 1):
            if self._stop_event.is_set():
                break

            delay = self.reconnect_interval * (2 ** min(attempt - 1, 4))
            logger.info(
                "Reconnect attempt %d for %s in %.1fs",
                attempt, device_id, delay,
            )
            await asyncio.sleep(delay)

            if self._stop_event.is_set():
                break

            success = await self.connect(device_id, url)
            if success:
                logger.info("Reconnected to device: %s", device_id)
                break

        self._reconnect_tasks.pop(device_id, None)

    @staticmethod
    def _now_iso() -> str:
        """Return the current UTC time in ISO 8601 format."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
