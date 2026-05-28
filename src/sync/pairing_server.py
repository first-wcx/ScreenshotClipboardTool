"""
Pairing server for the ICC multi-device sync system.

Provides an HTTP server for device pairing:
- Generates QR codes containing pairing tokens
- Generates 6-digit PIN codes for manual pairing
- Validates pairing tokens from incoming connections
- Manages shared secret generation and distribution

HTTP endpoints:
- GET /pairing/qr    → Returns QR code image + pairing ID
- GET /pairing/pin   → Returns 6-digit PIN code
- POST /pairing/confirm/<pairing_id> → Confirms a pairing request
- GET /pairing/status/<pairing_id>   → Checks pairing status

QR code format: icc://pair?h={host}&p={port}&t={token}&v=1
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from aiohttp import web

from .auth import generate_pairing_token, generate_shared_secret
from .protocol import (
    MSG_TYPE_PAIRING_CONFIRM,
    ProtocolCodec,
    SyncMessage,
)

logger = logging.getLogger(__name__)

# Default configuration
DEFAULT_PAIRING_HOST = "0.0.0.0"
DEFAULT_PAIRING_PORT = 8766
DEFAULT_TOKEN_TTL = 300  # 5 minutes


@dataclass
class PairingSession:
    """Represents an active pairing session.

    Attributes:
        pairing_id: Unique identifier for this pairing session.
        token: The pairing token (6-digit PIN).
        created_at: Epoch timestamp when the session was created.
        confirmed: Whether the pairing has been confirmed.
        remote_device_id: Device ID of the remote device (set on confirmation).
        remote_device_name: Device name of the remote device.
        remote_device_type: Device type of the remote device.
        remote_platform: Platform string of the remote device.
        shared_secret: The generated shared secret (set on confirmation).
    """

    pairing_id: str
    token: str
    created_at: float = 0.0
    confirmed: bool = False
    remote_device_id: str = ""
    remote_device_name: str = ""
    remote_device_type: str = ""
    remote_platform: str = ""
    shared_secret: str = ""


class PairingServer:
    """HTTP server for device pairing with QR code and PIN support.

    Manages pairing sessions and generates QR codes for Android devices
    to scan. After scanning, the Android device connects via WebSocket
    and sends a pairing_request message.

    Usage:
        server = PairingServer(device_name="MyDesktop")
        await server.start()
        # ...
        pairing_id, qr_image = server.generate_qr_code()
        # ...
        await server.stop()
    """

    def __init__(
        self,
        host: str = DEFAULT_PAIRING_HOST,
        port: int = DEFAULT_PAIRING_PORT,
        device_name: str = "ICC Desktop",
        device_id: str = "",
        device_type: str = "desktop",
        platform: str = "",
        ws_port: int = 8765,
        token_ttl: int = DEFAULT_TOKEN_TTL,
        on_pairing_confirmed: Optional[Any] = None,
    ) -> None:
        """Initialize the PairingServer.

        Args:
            host: Bind address for the HTTP server.
            port: Bind port for the HTTP server (default: 8766).
            device_name: This device's name.
            device_id: This device's unique ID.
            device_type: This device's type.
            platform: This device's platform string.
            ws_port: WebSocket server port for QR code generation.
            token_ttl: Pairing token TTL in seconds.
            on_pairing_confirmed: Callback when pairing is confirmed.
                Signature: (device_id, device_name, device_type, platform, shared_secret) -> None
        """
        self.host = host
        self.port = port
        self.device_name = device_name
        self.device_id = device_id
        self.device_type = device_type
        self.platform = platform
        self.ws_port = ws_port
        self.token_ttl = token_ttl
        self.on_pairing_confirmed = on_pairing_confirmed

        # Active pairing sessions: pairing_id -> PairingSession
        self._sessions: Dict[str, PairingSession] = {}

        # Token to session mapping: token -> pairing_id
        self._token_to_session: Dict[str, str] = {}

        # Shared secrets store: device_id -> shared_secret
        # Used by WebSocketServer to authenticate connections
        self._shared_secrets: Dict[str, str] = {}

        # aiohttp application
        self._app: Optional[web.Application] = None
        self._runner: Optional[web.AppRunner] = None

    @property
    def shared_secrets(self) -> Dict[str, str]:
        """Get the shared secrets store (for use by WebSocketServer)."""
        return self._shared_secrets

    async def start(self) -> None:
        """Start the pairing HTTP server."""
        self._app = web.Application()
        self._app.router.add_get("/pairing/qr", self._handle_qr_request)
        self._app.router.add_get("/pairing/pin", self._handle_pin_request)
        self._app.router.add_post("/pairing/confirm/{pairing_id}", self._handle_confirm)
        self._app.router.add_get("/pairing/status/{pairing_id}", self._handle_status)

        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, self.host, self.port)
        await site.start()
        logger.info("Pairing server started on %s:%d", self.host, self.port)

    async def stop(self) -> None:
        """Stop the pairing HTTP server."""
        if self._runner:
            await self._runner.cleanup()
        self._sessions.clear()
        self._token_to_session.clear()
        logger.info("Pairing server stopped")

    def generate_qr_code(self) -> Tuple[str, Any]:
        """Generate a new pairing session and QR code.

        Returns:
            A tuple of (pairing_id, PIL Image object with QR code).
        """
        token = generate_pairing_token()
        pairing_id = f"pair_{token}_{int(time.time())}"

        session = PairingSession(
            pairing_id=pairing_id,
            token=token,
            created_at=time.time(),
        )
        self._sessions[pairing_id] = session
        self._token_to_session[token] = pairing_id

        # Generate QR code
        qr_text = self._build_qr_text(token)
        qr_image = self._create_qr_image(qr_text)

        logger.info("Generated pairing session: %s, token: %s", pairing_id, token)
        return pairing_id, qr_image

    def generate_pin(self) -> str:
        """Generate a new 6-digit PIN for pairing.

        Returns:
            The generated 6-digit PIN string.
        """
        token = generate_pairing_token()
        pairing_id = f"pair_{token}_{int(time.time())}"

        session = PairingSession(
            pairing_id=pairing_id,
            token=token,
            created_at=time.time(),
        )
        self._sessions[pairing_id] = session
        self._token_to_session[token] = pairing_id

        logger.info("Generated pairing PIN: %s", token)
        return token

    def validate_token(self, token: str) -> Optional[PairingSession]:
        """Validate a pairing token and return the associated session.

        Args:
            token: The pairing token to validate.

        Returns:
            The PairingSession if valid, None otherwise.
        """
        pairing_id = self._token_to_session.get(token)
        if not pairing_id:
            return None

        session = self._sessions.get(pairing_id)
        if not session:
            return None

        # Check expiration
        if time.time() - session.created_at > self.token_ttl:
            self._sessions.pop(pairing_id, None)
            self._token_to_session.pop(token, None)
            return None

        return session

    def confirm_pairing(
        self,
        pairing_id: str,
        remote_device_id: str,
        remote_device_name: str,
        remote_device_type: str,
        remote_platform: str,
    ) -> str:
        """Confirm a pairing and generate a shared secret.

        Args:
            pairing_id: The pairing session ID.
            remote_device_id: The remote device's ID.
            remote_device_name: The remote device's name.
            remote_device_type: The remote device's type.
            remote_platform: The remote device's platform.

        Returns:
            The generated shared secret.

        Raises:
            ValueError: If the pairing session is not found.
        """
        session = self._sessions.get(pairing_id)
        if not session:
            raise ValueError(f"Pairing session not found: {pairing_id}")

        shared_secret = generate_shared_secret()
        session.confirmed = True
        session.remote_device_id = remote_device_id
        session.remote_device_name = remote_device_name
        session.remote_device_type = remote_device_type
        session.remote_platform = remote_platform
        session.shared_secret = shared_secret

        # Store the shared secret for this device
        self._shared_secrets[remote_device_id] = shared_secret

        # Notify callback
        if self.on_pairing_confirmed:
            self.on_pairing_confirmed(
                remote_device_id,
                remote_device_name,
                remote_device_type,
                remote_platform,
                shared_secret,
            )

        logger.info(
            "Pairing confirmed: %s with %s (%s)",
            pairing_id, remote_device_name, remote_device_id,
        )
        return shared_secret

    def cleanup_expired(self) -> None:
        """Remove all expired pairing sessions."""
        now = time.time()
        expired_ids = [
            pid for pid, session in self._sessions.items()
            if now - session.created_at > self.token_ttl
        ]
        for pid in expired_ids:
            session = self._sessions.pop(pid, None)
            if session:
                self._token_to_session.pop(session.token, None)

    # ------------------------------------------------------------------
    # HTTP handlers
    # ------------------------------------------------------------------

    async def _handle_qr_request(self, request: web.Request) -> web.Response:
        """Handle GET /pairing/qr — generate a QR code for pairing."""
        pairing_id, qr_image = self.generate_qr_code()

        # Convert PIL Image to PNG bytes
        buffer = io.BytesIO()
        qr_image.save(buffer, format="PNG")
        png_bytes = buffer.getvalue()

        return web.json_response({
            "pairing_id": pairing_id,
            "qr_image_base64": base64.b64encode(png_bytes).decode("ascii"),
            "token": self._sessions[pairing_id].token,
        })

    async def _handle_pin_request(self, request: web.Request) -> web.Response:
        """Handle GET /pairing/pin — generate a PIN for pairing."""
        pin = self.generate_pin()
        return web.json_response({"pin": pin})

    async def _handle_confirm(self, request: web.Request) -> web.Response:
        """Handle POST /pairing/confirm/{pairing_id} — confirm a pairing."""
        pairing_id = request.match_info["pairing_id"]
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "Invalid JSON"}, status=400)

        remote_device_id = data.get("device_id", "")
        remote_device_name = data.get("device_name", "")
        remote_device_type = data.get("device_type", "")
        remote_platform = data.get("platform", "")

        if not remote_device_id:
            return web.json_response({"error": "device_id is required"}, status=400)

        try:
            shared_secret = self.confirm_pairing(
                pairing_id,
                remote_device_id,
                remote_device_name,
                remote_device_type,
                remote_platform,
            )
            return web.json_response({
                "status": "confirmed",
                "shared_secret": shared_secret,
            })
        except ValueError as e:
            return web.json_response({"error": str(e)}, status=404)

    async def _handle_status(self, request: web.Request) -> web.Response:
        """Handle GET /pairing/status/{pairing_id} — check pairing status."""
        pairing_id = request.match_info["pairing_id"]
        session = self._sessions.get(pairing_id)

        if not session:
            return web.json_response({"error": "Session not found"}, status=404)

        return web.json_response({
            "pairing_id": session.pairing_id,
            "confirmed": session.confirmed,
            "remote_device_name": session.remote_device_name if session.confirmed else "",
        })

    # ------------------------------------------------------------------
    # QR code generation
    # ------------------------------------------------------------------

    def _build_qr_text(self, token: str) -> str:
        """Build the QR code content string.

        Format: icc://pair?h={host}&p={port}&t={token}&v=1

        Args:
            token: The pairing token.

        Returns:
            The QR code content string.
        """
        # Determine the host IP to include in the QR code
        host_ip = self._get_local_ip()
        return f"icc://pair?h={host_ip}&p={self.ws_port}&t={token}&v=1"

    @staticmethod
    def _create_qr_image(text: str) -> Any:
        """Create a QR code image from text content.

        Args:
            text: The content to encode in the QR code.

        Returns:
            A PIL Image object containing the QR code.
        """
        try:
            import qrcode
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_M,
                box_size=10,
                border=4,
            )
            qr.add_data(text)
            qr.make(fit=True)
            return qr.make_image(fill_color="black", back_color="white")
        except ImportError:
            logger.warning("qrcode library not available, generating placeholder image")
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (200, 200), "white")
            draw = ImageDraw.Draw(img)
            draw.text((10, 80), "QR Code", fill="black")
            draw.text((10, 100), text[:30], fill="gray")
            return img

    @staticmethod
    def _get_local_ip() -> str:
        """Get the local machine's IP address on the LAN."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
