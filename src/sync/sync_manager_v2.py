"""
WebSocket-based multi-device sync manager for the ICC desktop app.

Replaces the existing ClipboardSyncManager (TCP+JSON, 1-to-1) with a
WebSocket-based multi-device sync system that supports:
- Multiple simultaneous device connections
- HMAC-SHA256 authenticated connections
- mDNS service discovery broadcasting
- QR code / PIN device pairing
- Clipboard content synchronization (text, images, files)
- Binary frame protocol for large images (>1MB)
- Automatic reconnection

Compatible with the existing serialize_item_for_sync /
deserialize_synced_item format from clipboard_viewer.py.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

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
    SYNC_BINARY_THRESHOLD,
    SYNC_MAX_IMAGE_BYTES,
)
from .auth import (
    compute_hmac,
    generate_challenge,
    generate_pairing_token,
    generate_shared_secret,
    verify_hmac,
)
from .device_manager import DeviceInfo, DeviceManager
from .websocket_server import WebSocketServer
from .websocket_client import WebSocketClient
from .mdns_advertiser import MdnsAdvertiser
from .pairing_server import PairingServer

logger = logging.getLogger(__name__)


@dataclass
class SyncConfig:
    """Configuration for the multi-device sync system.

    Attributes:
        enabled: Whether sync is enabled.
        listen_host: Host address for the WebSocket server.
        port: Port for the WebSocket server (default: 8765).
        sync_text: Whether to sync text clipboard items.
        sync_images: Whether to sync image clipboard items.
        sync_files: Whether to sync file clipboard items.
        lan_only: Whether to restrict sync to LAN only (no relay).
        relay_url: URL of the relay server for cross-network sync.
    """

    enabled: bool = False
    listen_host: str = "0.0.0.0"
    port: int = 8765
    sync_text: bool = True
    sync_images: bool = True
    sync_files: bool = False
    lan_only: bool = True
    relay_url: str = ""


class SyncManagerV2:
    """WebSocket-based multi-device clipboard sync manager.

    This class replaces the existing ClipboardSyncManager with support for
    multiple simultaneous WebSocket connections, mDNS discovery, and
    authenticated pairing.

    Usage:
        config = SyncConfig(enabled=True, port=8765)
        manager = SyncManagerV2(config)
        manager.start()
        # ...
        manager.publish(clipboard_item)
        # ...
        manager.stop()
    """

    def __init__(
        self,
        config: Optional[SyncConfig] = None,
        on_clipboard_sync: Optional[Callable] = None,
        on_device_connected: Optional[Callable] = None,
        on_device_disconnected: Optional[Callable] = None,
    ) -> None:
        """Initialize the SyncManagerV2.

        Args:
            config: Sync configuration. If None, uses defaults.
            on_clipboard_sync: Callback when a clipboard sync message is received.
                Signature: (item_type, item_data, binary_payload) -> None
            on_device_connected: Callback when a device connects.
                Signature: (device_id, device_name) -> None
            on_device_disconnected: Callback when a device disconnects.
                Signature: (device_id) -> None
        """
        self.config = config or SyncConfig()
        self.on_clipboard_sync = on_clipboard_sync
        self.on_device_connected = on_device_connected
        self.on_device_disconnected = on_device_disconnected

        # Generate or load this device's node ID
        self.node_id = self._load_or_generate_node_id()

        # Device manager for paired device persistence
        self.device_manager = DeviceManager()

        # Shared secret store: device_id -> shared_secret
        self._shared_secrets: Dict[str, str] = {}

        # WebSocket server (accepts incoming connections)
        self._ws_server = WebSocketServer(
            host=self.config.listen_host,
            port=self.config.port,
            device_manager=self.device_manager,
            on_pairing_request=self._handle_pairing_request,
            on_clipboard_sync=self._handle_clipboard_sync_server,
        )

        # WebSocket client (connects to other desktops / relay)
        self._ws_client = WebSocketClient(
            device_manager=self.device_manager,
            secret_store=self._shared_secrets,
            on_clipboard_sync=self._handle_clipboard_sync_client,
            on_device_online=self._handle_device_online,
            on_device_offline=self._handle_device_offline,
        )

        # mDNS advertiser
        self._mdns = MdnsAdvertiser()

        # Pairing server
        self._pairing_server = PairingServer(
            host="0.0.0.0",
            port=8766,
            device_name=self._get_device_name(),
            device_id=self.node_id,
            device_type="desktop",
            platform=self._get_platform(),
            ws_port=self.config.port,
            on_pairing_confirmed=self._handle_pairing_confirmed,
        )

        # Event queue for thread-safe communication
        self.event_queue: queue.Queue = queue.Queue()

        # Async event loop and thread
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the sync manager in a background thread.

        Starts the WebSocket server, mDNS advertiser, and pairing server.
        Also attempts to reconnect to previously paired devices.
        """
        if self._thread and self._thread.is_alive():
            logger.warning("SyncManagerV2 already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        logger.info("SyncManagerV2 started")

    def stop(self) -> None:
        """Stop the sync manager and all components."""
        self._stop_event.set()

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)

        if self._thread:
            self._thread.join(timeout=10.0)
            self._thread = None

        logger.info("SyncManagerV2 stopped")

    def publish(self, item: dict) -> None:
        """Publish a local clipboard item to all connected devices.

        The item dict should be compatible with serialize_item_for_sync output.
        For text items: {"type": "text", "text": "...", "digest": "...", ...}
        For image items: {"type": "image", "dib_b64": "...", "size": 12345, ...}

        Args:
            item: The clipboard item data.
        """
        if not self.config.enabled:
            return

        item_type = item.get("type", "")
        if item_type == "text" and not self.config.sync_text:
            return
        if item_type == "image" and not self.config.sync_images:
            return

        # Encode the item using ProtocolCodec
        msg, binary_payload = ProtocolCodec.encode_clipboard_item(
            item_type, item, origin=self.node_id
        )

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._async_publish(msg, binary_payload), self._loop
            )

    def connect_to_device(self, device: DeviceInfo) -> None:
        """Connect to a remote device via WebSocket.

        Args:
            device: The device info to connect to.
        """
        url = f"ws://{device.ip_address}:{device.port}"
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._ws_client.connect(device.device_id, url), self._loop
            )

    def disconnect_device(self, device_id: str) -> None:
        """Disconnect from a specific device.

        Args:
            device_id: The device ID to disconnect from.
        """
        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(
                self._ws_client.disconnect(device_id), self._loop
            )

    def get_connected_devices(self) -> List[DeviceInfo]:
        """Get the list of currently connected devices.

        Returns:
            List of DeviceInfo for connected and authenticated devices.
        """
        connected_ids = set()
        if self._loop and self._loop.is_running():
            # This is synchronous since we're just reading internal state
            connected_ids = self._ws_server.get_connected_device_ids()
            connected_ids |= self._ws_client.get_connected_device_ids()

        result = []
        for device_id in connected_ids:
            device = self.device_manager.get_device(device_id)
            if device:
                result.append(device)
        return result

    def generate_pairing_qr(self) -> Tuple[str, Any]:
        """Generate a QR code for device pairing.

        Returns:
            A tuple of (pairing_id, PIL Image with QR code).
        """
        return self._pairing_server.generate_qr_code()

    def generate_pairing_pin(self) -> str:
        """Generate a 6-digit PIN for device pairing.

        Returns:
            The 6-digit PIN string.
        """
        return self._pairing_server.generate_pin()

    # ------------------------------------------------------------------
    # Internal async operations
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main event loop running in a background thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._async_start())
            # Keep the loop running until stop is requested
            while not self._stop_event.is_set():
                self._loop.run_until_complete(asyncio.sleep(0.5))
        except Exception as e:
            logger.error("Error in sync manager event loop: %s", e)
        finally:
            self._loop.run_until_complete(self._async_stop())
            self._loop.close()
            self._loop = None

    async def _async_start(self) -> None:
        """Start all async components."""
        # Load device manager
        self.device_manager.load()

        # Load shared secrets from device manager
        # (shared secrets are stored alongside devices)
        self._load_shared_secrets()

        # Set shared secret store on WS server
        self._ws_server.set_shared_secret_store(self._shared_secrets)

        # Set node ID on WS client
        self._ws_client.set_node_id(self.node_id)

        if self.config.enabled:
            # Start WebSocket server
            await self._ws_server.start()

            # Start mDNS advertiser
            self._mdns.start(
                device_name=self._get_device_name(),
                port=self.config.port,
                device_id=self.node_id,
                device_type="desktop",
                platform=self._get_platform(),
            )

            # Start pairing server
            await self._pairing_server.start()

            # Reconnect to previously paired devices
            await self._reconnect_to_paired_devices()

            logger.info("SyncManagerV2 async components started")

    async def _async_stop(self) -> None:
        """Stop all async components."""
        # Stop mDNS advertiser
        self._mdns.stop()

        # Stop WebSocket server
        await self._ws_server.stop()

        # Stop WebSocket client
        await self._ws_client.disconnect_all()

        # Stop pairing server
        await self._pairing_server.stop()

        # Save device manager state
        self._save_shared_secrets()
        self.device_manager.save()

        logger.info("SyncManagerV2 async components stopped")

    async def _async_publish(self, msg: SyncMessage, binary_payload: Optional[bytes]) -> None:
        """Publish a message to all connected devices (async)."""
        # Broadcast via WebSocket server to connected clients
        await self._ws_server.broadcast(msg, binary_payload)

        # Also send via WebSocket client to peers we connected to
        # (client broadcast is not implemented as a single method,
        #  so we iterate)
        for device_id in self._ws_client.get_connected_device_ids():
            await self._ws_client.send(device_id, msg, binary_payload)

    async def _reconnect_to_paired_devices(self) -> None:
        """Attempt to reconnect to previously paired devices."""
        devices = self.device_manager.list_devices()
        for device in devices:
            if device.ip_address:
                url = f"ws://{device.ip_address}:{device.port}"
                try:
                    await self._ws_client.connect(device.device_id, url)
                    logger.info("Reconnected to device: %s", device.device_name)
                except Exception as e:
                    logger.warning("Failed to reconnect to %s: %s", device.device_name, e)

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _handle_pairing_request(
        self,
        device_id: str,
        device_name: str,
        device_type: str,
        platform: str,
        token: str,
    ) -> bool:
        """Handle a pairing request from a remote device.

        Validates the pairing token and returns whether the request is approved.

        Args:
            device_id: The requesting device's ID.
            device_name: The requesting device's name.
            device_type: The requesting device's type.
            platform: The requesting device's platform.
            token: The pairing token.

        Returns:
            True if the pairing is approved.
        """
        session = self._pairing_server.validate_token(token)
        if not session:
            logger.warning("Invalid pairing token: %s", token)
            return False

        # Auto-confirm the pairing
        shared_secret = self._pairing_server.confirm_pairing(
            session.pairing_id,
            device_id,
            device_name,
            device_type,
            platform,
        )

        # Store the shared secret
        self._shared_secrets[device_id] = shared_secret

        # Add the device to the device manager
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        device_info = DeviceInfo(
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            ip_address="",
            port=8765,
            platform=platform,
            paired_at=now,
            last_seen=now,
        )
        self.device_manager.add_device(device_info)

        # Put event on the queue for the main thread
        self.event_queue.put({
            "type": "pairing_confirmed",
            "device_id": device_id,
            "device_name": device_name,
            "shared_secret": shared_secret,
        })

        return True

    def _handle_pairing_confirmed(
        self,
        device_id: str,
        device_name: str,
        device_type: str,
        platform: str,
        shared_secret: str,
    ) -> None:
        """Handle a pairing confirmation (when this device initiated pairing)."""
        self._shared_secrets[device_id] = shared_secret

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        device_info = DeviceInfo(
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            ip_address="",
            port=8765,
            platform=platform,
            paired_at=now,
            last_seen=now,
        )
        self.device_manager.add_device(device_info)

        self.event_queue.put({
            "type": "pairing_confirmed",
            "device_id": device_id,
            "device_name": device_name,
        })

    def _handle_clipboard_sync_server(
        self,
        device_id: str,
        item_type: str,
        item_data: dict,
        binary_payload: Optional[bytes],
    ) -> None:
        """Handle a clipboard sync message received by the server."""
        self._process_clipboard_sync(item_type, item_data, binary_payload)

    def _handle_clipboard_sync_client(
        self,
        device_id: str,
        item_type: str,
        item_data: dict,
        binary_payload: Optional[bytes],
    ) -> None:
        """Handle a clipboard sync message received by the client."""
        self._process_clipboard_sync(item_type, item_data, binary_payload)

    def _process_clipboard_sync(
        self,
        item_type: str,
        item_data: dict,
        binary_payload: Optional[bytes],
    ) -> None:
        """Process a received clipboard sync message.

        Puts the item on the event queue for the main thread to handle.

        Args:
            item_type: The item type ("text", "image", "files").
            item_data: The item data dict.
            binary_payload: Optional binary payload for large images.
        """
        # For binary images, convert to base64 DIB for compatibility
        if item_type == "image" and binary_payload:
            import base64
            item_data = dict(item_data)
            item_data["dib_b64"] = base64.b64encode(binary_payload).decode("ascii")
            item_data["size"] = len(binary_payload)

        # Apply sync config filters
        if item_type == "text" and not self.config.sync_text:
            return
        if item_type == "image" and not self.config.sync_images:
            return

        self.event_queue.put({
            "type": "clipboard_sync",
            "item_type": item_type,
            "item_data": item_data,
        })

        # Notify callback
        if self.on_clipboard_sync:
            self.on_clipboard_sync(item_type, item_data, binary_payload)

    def _handle_device_online(self, payload: dict) -> None:
        """Handle a device online notification."""
        device_id = payload.get("device_id", "")
        device_name = payload.get("device_name", "")
        logger.info("Device online: %s (%s)", device_name, device_id)
        if self.on_device_connected:
            self.on_device_connected(device_id, device_name)

    def _handle_device_offline(self, payload: dict) -> None:
        """Handle a device offline notification."""
        device_id = payload.get("device_id", "")
        logger.info("Device offline: %s", device_id)
        if self.on_device_disconnected:
            self.on_device_disconnected(device_id)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_or_generate_node_id(self) -> str:
        """Load or generate this device's node ID.

        The node ID is generated once and persisted to ~/.icc/node_id.

        Returns:
            The 16-character hex node ID.
        """
        node_id_path = Path.home() / ".icc" / "node_id"
        if node_id_path.exists():
            try:
                return node_id_path.read_text(encoding="utf-8").strip()
            except Exception:
                pass

        # Generate new node ID
        node_id = hashlib.sha256(os.urandom(16)).hexdigest()[:16]
        node_id_path.parent.mkdir(parents=True, exist_ok=True)
        node_id_path.write_text(node_id, encoding="utf-8")
        return node_id

    def _load_shared_secrets(self) -> None:
        """Load shared secrets from the persistent store.

        Shared secrets are stored in ~/.icc/secrets.json.
        """
        secrets_path = Path.home() / ".icc" / "secrets.json"
        if not secrets_path.exists():
            return

        try:
            import json
            raw = secrets_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                self._shared_secrets = {str(k): str(v) for k, v in data.items()}
        except Exception as e:
            logger.warning("Failed to load shared secrets: %s", e)

    def _save_shared_secrets(self) -> None:
        """Save shared secrets to the persistent store."""
        import json
        secrets_path = Path.home() / ".icc" / "secrets.json"
        secrets_path.parent.mkdir(parents=True, exist_ok=True)
        secrets_path.write_text(
            json.dumps(self._shared_secrets, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _get_device_name() -> str:
        """Get a human-readable device name for this machine."""
        import platform
        hostname = platform.node()
        return f"{platform.system()}-{hostname}" if hostname else platform.system()

    @staticmethod
    def _get_platform() -> str:
        """Get the platform string for this machine."""
        import platform
        system = platform.system().lower()
        release = platform.release()
        return f"{system}_{release}"
