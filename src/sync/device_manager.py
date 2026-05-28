"""
Device manager for the ICC multi-device sync system.

Manages paired device information with persistence to a JSON file.
Compatible with the desktop app's existing sync configuration model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Default path for device persistence
DEFAULT_CONFIG_DIR = Path.home() / ".icc"
DEFAULT_DEVICES_PATH = DEFAULT_CONFIG_DIR / "devices.json"


@dataclass
class DeviceInfo:
    """Represents information about a discovered or paired device.

    Attributes:
        device_id: Unique device identifier (16-char hex string).
        device_name: Human-readable device name.
        device_type: Device type ("android" or "desktop").
        ip_address: IP address on the local network.
        port: WebSocket port number.
        platform: Platform string (e.g., "android_14", "windows_11").
        paired_at: ISO 8601 timestamp when the device was paired.
        last_seen: ISO 8601 timestamp when the device was last seen.
    """

    device_id: str = ""
    device_name: str = ""
    device_type: str = ""
    ip_address: str = ""
    port: int = 8765
    platform: str = ""
    paired_at: str = ""
    last_seen: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceInfo":
        """Create a DeviceInfo from a dictionary."""
        return cls(
            device_id=str(data.get("device_id", "")),
            device_name=str(data.get("device_name", "")),
            device_type=str(data.get("device_type", "")),
            ip_address=str(data.get("ip_address", "")),
            port=int(data.get("port", 8765)),
            platform=str(data.get("platform", "")),
            paired_at=str(data.get("paired_at", "")),
            last_seen=str(data.get("last_seen", "")),
        )


# Type alias for the internal device storage
_DictAny = Dict[str, Any]


class DeviceManager:
    """Manages paired device information with JSON file persistence.

    The device registry is stored in ``~/.icc/devices.json`` and contains
    a mapping of device_id -> DeviceInfo for all paired devices.

    Thread safety: This class is NOT thread-safe. Callers should use
    appropriate locking if accessed from multiple threads.
    """

    def __init__(self, config_path: Optional[Path] = None) -> None:
        """Initialize the DeviceManager.

        Args:
            config_path: Path to the JSON file for persistence.
                         Defaults to ``~/.icc/devices.json``.
        """
        self.config_path: Path = config_path or DEFAULT_DEVICES_PATH
        self._devices: Dict[str, DeviceInfo] = {}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Load paired devices from the JSON config file.

        If the file does not exist or is invalid, starts with an empty device list.
        """
        if not self.config_path.exists():
            self._devices = {}
            return

        try:
            raw = self.config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if not isinstance(data, dict):
                self._devices = {}
                return

            self._devices = {}
            for device_id, device_data in data.items():
                if isinstance(device_data, dict):
                    info = DeviceInfo.from_dict(device_data)
                    self._devices[device_id] = info
        except (json.JSONDecodeError, OSError, ValueError):
            self._devices = {}

    def save(self) -> None:
        """Save paired devices to the JSON config file.

        Creates the parent directory if it does not exist.
        """
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        data = {did: info.to_dict() for did, info in self._devices.items()}
        raw = json.dumps(data, ensure_ascii=False, indent=2)
        self.config_path.write_text(raw, encoding="utf-8")

    # ------------------------------------------------------------------
    # Device CRUD
    # ------------------------------------------------------------------

    def add_device(self, device: DeviceInfo) -> None:
        """Add or update a paired device.

        If a device with the same device_id already exists, it will be replaced.

        Args:
            device: The DeviceInfo to add.
        """
        if not device.device_id:
            return
        self._devices[device.device_id] = device
        self.save()

    def remove_device(self, device_id: str) -> None:
        """Remove a paired device by its ID.

        Args:
            device_id: The device ID to remove.
        """
        if device_id in self._devices:
            del self._devices[device_id]
            self.save()

    def get_device(self, device_id: str) -> Optional[DeviceInfo]:
        """Get a paired device by its ID.

        Args:
            device_id: The device ID to look up.

        Returns:
            The DeviceInfo if found, None otherwise.
        """
        return self._devices.get(device_id)

    def list_devices(self) -> List[DeviceInfo]:
        """List all paired devices, ordered by last_seen (most recent first).

        Returns:
            List of all DeviceInfo objects.
        """
        return sorted(
            self._devices.values(),
            key=lambda d: d.last_seen,
            reverse=True,
        )

    def update_last_seen(self, device_id: str) -> None:
        """Update the last_seen timestamp for a device to the current time.

        Args:
            device_id: The device ID to update.
        """
        device = self._devices.get(device_id)
        if device:
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            self._devices[device_id] = DeviceInfo(
                device_id=device.device_id,
                device_name=device.device_name,
                device_type=device.device_type,
                ip_address=device.ip_address,
                port=device.port,
                platform=device.platform,
                paired_at=device.paired_at,
                last_seen=now,
            )
            self.save()

    def is_paired(self, device_id: str) -> bool:
        """Check if a device is paired (exists in the registry).

        Args:
            device_id: The device ID to check.

        Returns:
            True if the device is paired.
        """
        return device_id in self._devices
