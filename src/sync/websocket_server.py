"""
WebSocket server for the ICC multi-device sync system.

Accepts incoming WebSocket connections from Android and other desktop devices,
handles authentication, and relays clipboard sync messages between
connected devices.

Binary frame protocol:
    [2 bytes: header length (big-endian uint16)]
    [N bytes: header JSON (UTF-8)]
    [M bytes: binary payload (optional)]
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional, Set

import websockets
from websockets.server import WebSocketServerProtocol

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


class WebSocketServer:
    """WebSocket server that accepts connections from sync peers.

    Manages:
    - Incoming connection handling
    - HMAC-SHA256 authentication handshake
    - Pairing request processing
    - Message routing between connected devices
    - Device online/offline notifications
    - Heartbeat (ping/pong) responses
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        device_manager: Optional[DeviceManager] = None,
        on_pairing_request: Optional[Callable] = None,
        on_clipboard_sync: Optional[Callable] = None,
    ) -> None:
        """Initialize the WebSocket server.

        Args:
            host: Bind address for the server.
            port: Bind port for the server.
            device_manager: DeviceManager for looking up paired devices and secrets.
            on_pairing_request: Callback when a pairing_request is received.
                Signature: (device_id, device_name, device_type, platform, token) -> bool
            on_clipboard_sync: Callback when a clipboard_sync message is received.
                Signature: (device_id, item_type, item_data, binary_payload) -> None
        """
        self.host = host
        self.port = port
        self.device_manager = device_manager or DeviceManager()
        self.on_pairing_request = on_pairing_request
        self.on_clipboard_sync = on_clipboard_sync

        # Active connections: device_id -> WebSocket
        self._connections: Dict[str, WebSocketServerProtocol] = {}

        # Authenticated device IDs
        self._authenticated: Set[str] = set()

        # Pending auth challenges: device_id -> nonce
        self._pending_challenges: Dict[str, str] = {}

        # Server instance
        self._server: Optional[websockets.WebSocketServer] = None

        # Stop event
        self._stop_event = asyncio.Event()

        # Shared secret store: device_id -> shared_secret
        # Populated by PairingServer during pairing
        self._secret_store: Dict[str, str] = {}

    async def start(self) -> None:
        """Start the WebSocket server."""
        self.device_manager.load()
        self._server = await websockets.serve(
            self._handler,
            self.host,
            self.port,
            ping_interval=30.0,
            ping_timeout=10.0,
            max_size=64 * 1024 * 1024,  # 64 MB max message size
        )
        logger.info("WebSocket server started on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the WebSocket server and close all connections."""
        self._stop_event.set()

        # Close all active connections
        for device_id, ws in list(self._connections.items()):
            try:
                await ws.close(1000, "Server shutting down")
            except Exception:
                pass

        self._connections.clear()
        self._authenticated.clear()
        self._pending_challenges.clear()

        if self._server:
            self._server.close()
            await self._server.wait_closed()
            logger.info("WebSocket server stopped")

    async def broadcast(
        self,
        msg: SyncMessage,
        binary_payload: Optional[bytes] = None,
        exclude: Optional[Set[str]] = None,
    ) -> None:
        """Broadcast a message to all connected and authenticated devices.

        Args:
            msg: The SyncMessage to broadcast.
            binary_payload: Optional binary payload.
            exclude: Set of device IDs to exclude from the broadcast.
        """
        exclude = exclude or set()
        encoded = ProtocolCodec.encode_message(msg, binary_payload)

        for device_id, ws in list(self._connections.items()):
            if device_id in exclude or device_id not in self._authenticated:
                continue
            try:
                await ws.send(encoded)
            except Exception as e:
                logger.warning("Failed to broadcast to %s: %s", device_id, e)

    async def send(
        self,
        device_id: str,
        msg: SyncMessage,
        binary_payload: Optional[bytes] = None,
    ) -> bool:
        """Send a message to a specific connected device.

        Args:
            device_id: The target device ID.
            msg: The SyncMessage to send.
            binary_payload: Optional binary payload.

        Returns:
            True if the message was sent successfully.
        """
        ws = self._connections.get(device_id)
        if ws is None or device_id not in self._authenticated:
            return False

        try:
            encoded = ProtocolCodec.encode_message(msg, binary_payload)
            await ws.send(encoded)
            return True
        except Exception as e:
            logger.warning("Failed to send to %s: %s", device_id, e)
            return False

    def get_connected_device_ids(self) -> Set[str]:
        """Get the set of currently connected and authenticated device IDs."""
        return set(self._authenticated)

    # ------------------------------------------------------------------
    # WebSocket handler
    # ------------------------------------------------------------------

    async def _handler(self, ws: WebSocketServerProtocol) -> None:
        """Handle a single WebSocket connection lifecycle.

        Args:
            ws: The WebSocket connection.
        """
        device_id = ""
        try:
            # Wait for the first message to identify the device
            # The first message should be hello, pairing_request, or auth-related
            async for raw_message in ws:
                if isinstance(raw_message, str):
                    # We only handle binary frames
                    logger.warning("Received text frame, ignoring")
                    continue

                data = bytes(raw_message)
                try:
                    msg, binary_payload = ProtocolCodec.decode_message(data)
                except Exception as e:
                    logger.warning("Failed to decode message: %s", e)
                    continue

                # If device is not yet identified, handle initial handshake
                if not device_id:
                    device_id = await self._handle_initial_message(ws, msg, binary_payload)
                    if not device_id:
                        # Connection rejected
                        break
                    continue

                # Handle authenticated messages
                if device_id not in self._authenticated:
                    # Still in auth phase
                    device_id = await self._handle_auth_message(ws, device_id, msg)
                    if not device_id:
                        break
                    continue

                # Process authenticated messages
                await self._handle_authenticated_message(device_id, msg, binary_payload)

        except websockets.exceptions.ConnectionClosed:
            logger.info("Connection closed for device: %s", device_id)
        except Exception as e:
            logger.error("Error handling connection for %s: %s", device_id, e)
        finally:
            if device_id:
                await self._on_device_disconnected(device_id)

    async def _handle_initial_message(
        self,
        ws: WebSocketServerProtocol,
        msg: SyncMessage,
        binary_payload: Optional[bytes],
    ) -> str:
        """Handle the first message from a new connection.

        Returns the device_id if the connection is accepted, empty string otherwise.
        """
        if msg.type == MSG_TYPE_PAIRING_REQUEST:
            return await self._handle_pairing_request(ws, msg)

        if msg.type == MSG_TYPE_HELLO:
            # Treat hello as a request to authenticate
            sender_id = msg.origin
            if not sender_id:
                return ""

            self._connections[sender_id] = ws
            return await self._send_auth_challenge(sender_id, ws)

        # Unknown initial message — close connection
        await ws.close(1008, "Expected hello or pairing_request")
        return ""

    async def _handle_pairing_request(
        self,
        ws: WebSocketServerProtocol,
        msg: SyncMessage,
    ) -> str:
        """Handle a pairing_request message.

        Returns empty string as pairing uses a temporary connection.
        """
        token = msg.payload.get("token", "")
        device_name = msg.payload.get("device_name", "Unknown")
        device_type = msg.payload.get("device_type", "android")
        platform = msg.payload.get("platform", "")
        sender_id = msg.origin

        logger.info("Pairing request from %s (%s)", device_name, sender_id)

        # Notify the callback
        if self.on_pairing_request:
            approved = self.on_pairing_request(
                sender_id, device_name, device_type, platform, token
            )
            if not approved:
                fail_msg = SyncMessage(type=MSG_TYPE_AUTH_FAIL, origin="", timestamp="", payload={})
                await ws.send(ProtocolCodec.encode_message(fail_msg))
                await ws.close(1008, "Pairing rejected")
                return ""

        # Generate shared secret and send pairing_confirm
        from .auth import generate_shared_secret

        shared_secret = generate_shared_secret()
        confirm_msg = SyncMessage(
            type=MSG_TYPE_PAIRING_CONFIRM,
            origin="",
            timestamp="",
            payload={
                "shared_secret": shared_secret,
                "device_name": "",  # Filled by caller
                "device_type": "desktop",
                "platform": "",
            },
        )
        await ws.send(ProtocolCodec.encode_message(confirm_msg))
        logger.info("Pairing confirmed for %s, secret sent", device_name)
        return ""

    async def _send_auth_challenge(
        self,
        device_id: str,
        ws: WebSocketServerProtocol,
    ) -> str:
        """Send an auth_challenge to a device and return the device_id.

        Returns the device_id if the challenge was sent, empty string on error.
        """
        if not self.device_manager.is_paired(device_id):
            fail_msg = SyncMessage(type=MSG_TYPE_AUTH_FAIL, origin="", timestamp="", payload={})
            await ws.send(ProtocolCodec.encode_message(fail_msg))
            await ws.close(1008, "Device not paired")
            return ""

        nonce = generate_challenge()
        self._pending_challenges[device_id] = nonce

        challenge_msg = SyncMessage(
            type=MSG_TYPE_AUTH_CHALLENGE,
            origin="",
            timestamp="",
            payload={"nonce": nonce},
        )
        try:
            await ws.send(ProtocolCodec.encode_message(challenge_msg))
            return device_id
        except Exception as e:
            logger.error("Failed to send auth challenge to %s: %s", device_id, e)
            self._connections.pop(device_id, None)
            self._pending_challenges.pop(device_id, None)
            return ""

    async def _handle_auth_message(
        self,
        ws: WebSocketServerProtocol,
        device_id: str,
        msg: SyncMessage,
    ) -> str:
        """Handle auth_response message using the secret store."""
        if msg.type == MSG_TYPE_AUTH_RESPONSE:
            nonce = self._pending_challenges.pop(device_id, "")
            if not nonce:
                fail_msg = SyncMessage(type=MSG_TYPE_AUTH_FAIL, origin="", timestamp="", payload={})
                await ws.send(ProtocolCodec.encode_message(fail_msg))
                await ws.close(1008, "No pending challenge")
                return ""

            # Look up shared secret from secret store
            secret = self._secret_store.get(device_id, "")
            if not secret:
                fail_msg = SyncMessage(type=MSG_TYPE_AUTH_FAIL, origin="", timestamp="", payload={})
                await ws.send(ProtocolCodec.encode_message(fail_msg))
                await ws.close(1008, "No shared secret found")
                return ""

            response_hmac = msg.payload.get("hmac", "")
            if verify_hmac(secret, nonce, response_hmac):
                self._authenticated.add(device_id)
                ok_msg = SyncMessage(type=MSG_TYPE_AUTH_OK, origin="", timestamp="", payload={})
                await ws.send(ProtocolCodec.encode_message(ok_msg))
                logger.info("Device authenticated: %s", device_id)

                self.device_manager.update_last_seen(device_id)
                await self._notify_device_online(device_id)
                return device_id
            else:
                fail_msg = SyncMessage(type=MSG_TYPE_AUTH_FAIL, origin="", timestamp="", payload={})
                await ws.send(ProtocolCodec.encode_message(fail_msg))
                await ws.close(1008, "Authentication failed")
                logger.warning("Authentication failed for device: %s", device_id)
                return ""

        await ws.close(1008, "Expected auth_response")
        return ""

    def set_shared_secret_store(self, secret_store: Dict[str, str]) -> None:
        """Set a shared secret store for device authentication.

        The secret store maps device_id -> shared_secret.
        This is used by PairingServer to store secrets during pairing.

        Args:
            secret_store: Dictionary mapping device IDs to shared secrets.
        """
        self._secret_store = secret_store

    async def _handle_authenticated_message(
        self,
        device_id: str,
        msg: SyncMessage,
        binary_payload: Optional[bytes],
    ) -> None:
        """Handle a message from an authenticated device."""
        if msg.type == MSG_TYPE_PING:
            pong_msg = SyncMessage(
                type=MSG_TYPE_PONG,
                origin="",
                timestamp="",
                payload={},
            )
            ws = self._connections.get(device_id)
            if ws:
                await ws.send(ProtocolCodec.encode_message(pong_msg))
            return

        if msg.type == MSG_TYPE_HELLO:
            # Update device info from hello
            device_name = msg.payload.get("device_name", "")
            logger.info("Hello from %s: %s", device_id, device_name)
            # Send device list
            await self._send_device_list(device_id)
            return

        if msg.type in (MSG_TYPE_CLIPBOARD_SYNC, MSG_TYPE_CLIPBOARD_SYNC_BINARY):
            # Relay to other connected devices
            await self.broadcast(msg, binary_payload, exclude={device_id})

            # Notify callback
            if self.on_clipboard_sync:
                item_type = msg.payload.get("item_type", "")
                item_data = msg.payload.get("item", {})
                self.on_clipboard_sync(device_id, item_type, item_data, binary_payload)
            return

        logger.debug("Unhandled message type from %s: %s", device_id, msg.type)

    async def _notify_device_online(self, device_id: str) -> None:
        """Notify all other connected devices that a device has come online."""
        device = self.device_manager.get_device(device_id)
        if not device:
            return

        online_msg = SyncMessage(
            type=MSG_TYPE_DEVICE_ONLINE,
            origin="",
            timestamp="",
            payload={
                "device_id": device_id,
                "device_name": device.device_name,
                "device_type": device.device_type,
            },
        )
        await self.broadcast(online_msg, exclude={device_id})

    async def _on_device_disconnected(self, device_id: str) -> None:
        """Handle a device disconnection."""
        self._connections.pop(device_id, None)
        self._authenticated.discard(device_id)
        self._pending_challenges.pop(device_id, None)

        logger.info("Device disconnected: %s", device_id)

        # Notify other devices
        offline_msg = SyncMessage(
            type=MSG_TYPE_DEVICE_OFFLINE,
            origin="",
            timestamp="",
            payload={"device_id": device_id},
        )
        await self.broadcast(offline_msg, exclude={device_id})

    async def _send_device_list(self, target_device_id: str) -> None:
        """Send the list of connected devices to a specific device."""
        devices = []
        for did in self._authenticated:
            if did == target_device_id:
                continue
            device = self.device_manager.get_device(did)
            if device:
                devices.append({
                    "device_id": device.device_id,
                    "device_name": device.device_name,
                    "device_type": device.device_type,
                    "platform": device.platform,
                })

        list_msg = SyncMessage(
            type=MSG_TYPE_DEVICE_LIST,
            origin="",
            timestamp="",
            payload={"devices": devices},
        )
        await self.send(target_device_id, list_msg)
