"""
mDNS service advertiser for the ICC multi-device sync system.

Uses the zeroconf library to broadcast the ICC sync service on the
local network so that Android devices can discover the desktop via NsdManager.

Service type: _icc_sync._tcp
Default port: 8765
"""

from __future__ import annotations

import logging
import socket
from typing import Optional

from zeroconf import IPVersion, ServiceInfo, Zeroconf

logger = logging.getLogger(__name__)

# mDNS service type for ICC sync (consistent with Android NsdDiscovery)
SERVICE_TYPE = "_icc_sync._tcp"


class MdnsAdvertiser:
    """Broadcasts the ICC sync service via mDNS for local network discovery.

    Android devices use NsdManager to discover services of type
    ``_icc_sync._tcp`` on the local network. This advertiser registers
    the service with the device name, port, and optional attributes
    (device_id, device_type, platform).

    Usage:
        advertiser = MdnsAdvertiser()
        advertiser.start("MyDesktop", 8765, device_id="abc123", platform="windows_11")
        # ... later ...
        advertiser.stop()
    """

    def __init__(self) -> None:
        """Initialize the MdnsAdvertiser."""
        self._zeroconf: Optional[Zeroconf] = None
        self._service_info: Optional[ServiceInfo] = None
        self._is_running: bool = False

    @property
    def is_running(self) -> bool:
        """Whether the mDNS advertiser is currently active."""
        return self._is_running

    def start(
        self,
        device_name: str,
        port: int = 8765,
        device_id: str = "",
        device_type: str = "desktop",
        platform: str = "",
    ) -> None:
        """Start broadcasting the ICC sync service via mDNS.

        Args:
            device_name: Human-readable device name for the service.
            port: WebSocket server port (default: 8765).
            device_id: This device's unique ID (included in service attributes).
            device_type: Device type string (default: "desktop").
            platform: Platform string (e.g. "windows_11").
        """
        if self._is_running:
            logger.warning("MdnsAdvertiser already running, stopping first")
            self.stop()

        try:
            # Get the local IP address
            local_ip = self._get_local_ip()

            # Build service properties
            properties: dict = {}
            if device_id:
                properties[b"device_id"] = device_id.encode("utf-8")
            if device_type:
                properties[b"device_type"] = device_type.encode("utf-8")
            if platform:
                properties[b"platform"] = platform.encode("utf-8")
            properties[b"device_name"] = device_name.encode("utf-8")

            # Create service info
            # Service name must be unique on the network; use device_id if available
            service_name = f"ICC Sync - {device_name}"
            if device_id:
                # Ensure valid DNS-SD service name
                service_name = f"ICC-{device_id[:8]}"

            self._service_info = ServiceInfo(
                type_=SERVICE_TYPE,
                name=f"{service_name}.{SERVICE_TYPE}",
                addresses=[socket.inet_aton(local_ip)],
                port=port,
                properties=properties,
                server=f"{device_id or 'icc-desktop'}.local.",
            )

            # Register the service
            self._zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
            self._zeroconf.register_service(self._service_info)
            self._is_running = True

            logger.info(
                "mDNS service registered: %s at %s:%d",
                service_name, local_ip, port,
            )

        except Exception as e:
            logger.error("Failed to start mDNS advertiser: %s", e)
            self._is_running = False

    def stop(self) -> None:
        """Stop broadcasting the ICC sync service and clean up."""
        if not self._is_running:
            return

        try:
            if self._zeroconf and self._service_info:
                self._zeroconf.unregister_service(self._service_info)
                self._zeroconf.close()
        except Exception as e:
            logger.error("Error stopping mDNS advertiser: %s", e)
        finally:
            self._zeroconf = None
            self._service_info = None
            self._is_running = False
            logger.info("mDNS service unregistered")

    @staticmethod
    def _get_local_ip() -> str:
        """Get the local machine's IP address on the LAN.

        Returns:
            The local IP address as a string.
        """
        try:
            # Create a UDP socket to determine the local IP
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                # Connect to a public DNS server (doesn't actually send data)
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
