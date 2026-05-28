"""
Device registry for the ICC relay server.

Manages online device status and pairing relationships using
in-memory state with aiosqlite persistence.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set


@dataclass
class RegisteredDevice:
    """Represents a device registered with the relay server.

    Attributes:
        device_id: Unique device identifier.
        device_name: Human-readable device name.
        device_type: Device type ("android" or "desktop").
        platform: Platform string (e.g., "android_14", "windows_11").
        shared_secret: HMAC shared secret for authentication.
        paired_at: Epoch timestamp when the device was first paired.
        last_seen: Epoch timestamp of last heartbeat/message.
        is_online: Whether the device currently has an active connection.
        paired_with: Set of device IDs this device is paired with.
    """

    device_id: str = ""
    device_name: str = ""
    device_type: str = ""
    platform: str = ""
    shared_secret: str = ""
    paired_at: float = 0.0
    last_seen: float = 0.0
    is_online: bool = False
    paired_with: Set[str] = field(default_factory=set)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for JSON serialization."""
        result = {
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_type": self.device_type,
            "platform": self.platform,
            "shared_secret": self.shared_secret,
            "paired_at": self.paired_at,
            "last_seen": self.last_seen,
            "is_online": self.is_online,
            "paired_with": list(self.paired_with),
        }
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RegisteredDevice":
        """Create a RegisteredDevice from a dictionary."""
        paired_with = data.get("paired_with", [])
        if isinstance(paired_with, list):
            paired_with = set(paired_with)
        elif isinstance(paired_with, set):
            pass
        else:
            paired_with = set()

        return cls(
            device_id=str(data.get("device_id", "")),
            device_name=str(data.get("device_name", "")),
            device_type=str(data.get("device_type", "")),
            platform=str(data.get("platform", "")),
            shared_secret=str(data.get("shared_secret", "")),
            paired_at=float(data.get("paired_at", 0.0)),
            last_seen=float(data.get("last_seen", 0.0)),
            is_online=bool(data.get("is_online", False)),
            paired_with=paired_with,
        )


class DeviceRegistry:
    """Manages device registration, online status, and pairing relationships.

    Uses in-memory state for fast lookups and aiosqlite for persistence.
    Designed for single-process async usage.
    """

    def __init__(self) -> None:
        """Initialize the DeviceRegistry with empty in-memory state."""
        self._devices: Dict[str, RegisteredDevice] = {}
        self._ws_connections: Dict[str, Any] = {}  # device_id -> websocket

    # ------------------------------------------------------------------
    # Device CRUD
    # ------------------------------------------------------------------

    def register_device(
        self,
        device_id: str,
        device_name: str,
        device_type: str,
        platform: str,
        shared_secret: str,
    ) -> RegisteredDevice:
        """Register a new device or update an existing one.

        Args:
            device_id: Unique device identifier.
            device_name: Human-readable device name.
            device_type: Device type ("android" or "desktop").
            platform: Platform string.
            shared_secret: HMAC shared secret.

        Returns:
            The registered RegisteredDevice.
        """
        now = time.time()
        existing = self._devices.get(device_id)
        if existing:
            # Update existing device
            existing.device_name = device_name
            existing.device_type = device_type
            existing.platform = platform
            if shared_secret:
                existing.shared_secret = shared_secret
            existing.last_seen = now
            return existing

        device = RegisteredDevice(
            device_id=device_id,
            device_name=device_name,
            device_type=device_type,
            platform=platform,
            shared_secret=shared_secret,
            paired_at=now,
            last_seen=now,
            is_online=False,
        )
        self._devices[device_id] = device
        return device

    def unregister_device(self, device_id: str) -> None:
        """Remove a device from the registry.

        Also removes pairing relationships with other devices.

        Args:
            device_id: The device ID to remove.
        """
        device = self._devices.pop(device_id, None)
        if device:
            # Remove pairing relationships
            for paired_id in device.paired_with:
                paired = self._devices.get(paired_id)
                if paired:
                    paired.paired_with.discard(device_id)

        # Remove websocket connection
        self._ws_connections.pop(device_id, None)

    def get_device(self, device_id: str) -> Optional[RegisteredDevice]:
        """Get a registered device by its ID.

        Args:
            device_id: The device ID to look up.

        Returns:
            The RegisteredDevice if found, None otherwise.
        """
        return self._devices.get(device_id)

    def list_devices(self) -> List[RegisteredDevice]:
        """List all registered devices.

        Returns:
            List of all RegisteredDevice objects.
        """
        return list(self._devices.values())

    def list_online_devices(self) -> List[RegisteredDevice]:
        """List all currently online devices.

        Returns:
            List of online RegisteredDevice objects.
        """
        return [d for d in self._devices.values() if d.is_online]

    # ------------------------------------------------------------------
    # Online status management
    # ------------------------------------------------------------------

    def set_online(self, device_id: str, websocket: Any) -> None:
        """Mark a device as online and associate its WebSocket connection.

        Args:
            device_id: The device ID.
            websocket: The WebSocket connection object.
        """
        device = self._devices.get(device_id)
        if device:
            device.is_online = True
            device.last_seen = time.time()
        self._ws_connections[device_id] = websocket

    def set_offline(self, device_id: str) -> None:
        """Mark a device as offline and remove its WebSocket connection.

        Args:
            device_id: The device ID.
        """
        device = self._devices.get(device_id)
        if device:
            device.is_online = False
            device.last_seen = time.time()
        self._ws_connections.pop(device_id, None)

    def get_websocket(self, device_id: str) -> Optional[Any]:
        """Get the WebSocket connection for a device.

        Args:
            device_id: The device ID.

        Returns:
            The WebSocket connection if the device is online, None otherwise.
        """
        return self._ws_connections.get(device_id)

    # ------------------------------------------------------------------
    # Pairing management
    # ------------------------------------------------------------------

    def pair_devices(self, device_id_a: str, device_id_b: str) -> bool:
        """Establish a pairing relationship between two devices.

        Args:
            device_id_a: First device ID.
            device_id_b: Second device ID.

        Returns:
            True if both devices exist and pairing was successful.
        """
        device_a = self._devices.get(device_id_a)
        device_b = self._devices.get(device_id_b)

        if not device_a or not device_b:
            return False

        device_a.paired_with.add(device_id_b)
        device_b.paired_with.add(device_id_a)
        return True

    def unpair_devices(self, device_id_a: str, device_id_b: str) -> bool:
        """Remove a pairing relationship between two devices.

        Args:
            device_id_a: First device ID.
            device_id_b: Second device ID.

        Returns:
            True if both devices exist and unpairing was successful.
        """
        device_a = self._devices.get(device_id_a)
        device_b = self._devices.get(device_id_b)

        if not device_a or not device_b:
            return False

        device_a.paired_with.discard(device_id_b)
        device_b.paired_with.discard(device_id_a)
        return True

    def get_paired_devices(self, device_id: str) -> List[RegisteredDevice]:
        """Get all devices paired with the given device.

        Args:
            device_id: The device ID to query.

        Returns:
            List of RegisteredDevice objects paired with the given device.
        """
        device = self._devices.get(device_id)
        if not device:
            return []

        return [
            self._devices[pid]
            for pid in device.paired_with
            if pid in self._devices
        ]

    def is_paired(self, device_id_a: str, device_id_b: str) -> bool:
        """Check if two devices are paired.

        Args:
            device_id_a: First device ID.
            device_id_b: Second device ID.

        Returns:
            True if the devices are paired.
        """
        device_a = self._devices.get(device_id_a)
        if not device_a:
            return False
        return device_id_b in device_a.paired_with

    # ------------------------------------------------------------------
    # Persistence (aiosqlite)
    # ------------------------------------------------------------------

    async def save_to_db(self, db_path: str = "relay_server.db") -> None:
        """Persist the device registry to SQLite using aiosqlite.

        Args:
            db_path: Path to the SQLite database file.
        """
        try:
            import aiosqlite

            async with aiosqlite.connect(db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS devices (
                        device_id TEXT PRIMARY KEY,
                        data TEXT NOT NULL
                    )
                """)
                # Clear existing data
                await db.execute("DELETE FROM devices")

                # Insert current devices
                for device_id, device in self._devices.items():
                    data_json = json.dumps(device.to_dict(), ensure_ascii=False)
                    await db.execute(
                        "INSERT INTO devices (device_id, data) VALUES (?, ?)",
                        (device_id, data_json),
                    )

                await db.commit()
        except ImportError:
            # aiosqlite not available; skip persistence
            pass

    async def load_from_db(self, db_path: str = "relay_server.db") -> None:
        """Load the device registry from SQLite using aiosqlite.

        Args:
            db_path: Path to the SQLite database file.
        """
        try:
            import aiosqlite

            async with aiosqlite.connect(db_path) as db:
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS devices (
                        device_id TEXT PRIMARY KEY,
                        data TEXT NOT NULL
                    )
                """)
                cursor = await db.execute("SELECT device_id, data FROM devices")
                rows = await cursor.fetchall()

                for row in rows:
                    device_id = row[0]
                    data_json = row[1]
                    try:
                        data = json.loads(data_json)
                        device = RegisteredDevice.from_dict(data)
                        # Preserve online status reset (all offline on load)
                        device.is_online = False
                        self._devices[device_id] = device
                    except (json.JSONDecodeError, ValueError):
                        continue
        except ImportError:
            # aiosqlite not available; start with empty registry
            pass
        except Exception:
            # Database file doesn't exist yet; start fresh
            pass
