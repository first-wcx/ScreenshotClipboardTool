"""
Relay server configuration.

Defines all configurable parameters for the ICC relay server,
including host, port, authentication token TTL, and other settings.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class RelayConfig:
    """Immutable configuration for the relay server."""

    # Server bind address
    host: str = "0.0.0.0"

    # HTTP/WebSocket port for the relay server
    port: int = 8766

    # WebSocket ping interval in seconds
    ws_ping_interval: float = 30.0

    # WebSocket ping timeout in seconds
    ws_ping_timeout: float = 10.0

    # Pairing token time-to-live in seconds (default: 5 minutes)
    auth_token_ttl: int = 300

    # Auth session token time-to-live in seconds (default: 24 hours)
    auth_session_ttl: int = 86400

    # Maximum number of concurrent connected devices per user
    max_devices_per_user: int = 5

    # Maximum binary payload size in bytes (32 MB, consistent with desktop)
    max_binary_size: int = 32 * 1024 * 1024

    # Maximum message size in bytes for WebSocket frames
    max_message_size: int = 64 * 1024 * 1024

    # SQLite database path for device registry persistence
    db_path: str = "relay_server.db"

    # Shared secret for initial relay authentication (set via env or config)
    relay_secret: str = ""

    # Logging level
    log_level: str = "INFO"

    # CORS allowed origins (for FastAPI)
    cors_origins: list = field(default_factory=lambda: ["*"])


def load_config() -> RelayConfig:
    """
    Load relay configuration from environment variables with defaults.
    Environment variables are prefixed with ICC_RELAY_.
    """
    import os

    def env(key: str, default: str) -> str:
        return os.environ.get(f"ICC_RELAY_{key}", default)

    return RelayConfig(
        host=env("HOST", "0.0.0.0"),
        port=int(env("PORT", "8766")),
        ws_ping_interval=float(env("WS_PING_INTERVAL", "30.0")),
        ws_ping_timeout=float(env("WS_PING_TIMEOUT", "10.0")),
        auth_token_ttl=int(env("AUTH_TOKEN_TTL", "300")),
        auth_session_ttl=int(env("AUTH_SESSION_TTL", "86400")),
        max_devices_per_user=int(env("MAX_DEVICES_PER_USER", "5")),
        max_binary_size=int(env("MAX_BINARY_SIZE", str(32 * 1024 * 1024))),
        max_message_size=int(env("MAX_MESSAGE_SIZE", str(64 * 1024 * 1024))),
        db_path=env("DB_PATH", "relay_server.db"),
        relay_secret=env("RELAY_SECRET", ""),
        log_level=env("LOG_LEVEL", "INFO"),
    )
