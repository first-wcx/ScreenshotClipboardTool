"""
ICC Relay Server — FastAPI + WebSocket main entry point.

Provides:
- HTTP API for device management and pairing
- WebSocket endpoint for real-time sync message relay
- Authentication via HMAC challenge-response
- Health check and status endpoints

Default port: 8766
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .config import RelayConfig, load_config
from .auth import RelayAuthenticator
from .device_registry import DeviceRegistry
from .signaling import SignalingHandler
from .turn_relay import TurnRelay

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

config: RelayConfig = load_config()
authenticator = RelayAuthenticator(
    token_ttl=config.auth_token_ttl,
    session_ttl=config.auth_session_ttl,
)
registry = DeviceRegistry()
signaling_handler = SignalingHandler(registry, authenticator, config)
turn_relay = TurnRelay(registry, config)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    # Startup
    logger.info("ICC Relay Server starting on %s:%d", config.host, config.port)
    await registry.load_from_db(config.db_path)

    # Start cleanup background task
    cleanup_task = asyncio.create_task(_periodic_cleanup())

    yield

    # Shutdown
    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    await registry.save_to_db(config.db_path)
    logger.info("ICC Relay Server stopped")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ICC Relay Server",
    description="Integrated Capture Clipboard - Relay Server for cross-network sync",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class PairingRequestModel(BaseModel):
    """Request body for generating a pairing token."""
    device_name: str = ""
    device_type: str = "desktop"


class PairingResponseModel(BaseModel):
    """Response for pairing token generation."""
    token: str
    expires_in: int


class RegisterDeviceModel(BaseModel):
    """Request body for device registration."""
    device_id: str
    device_name: str
    device_type: str = "desktop"
    platform: str = ""


class DeviceInfoModel(BaseModel):
    """Device information response."""
    device_id: str
    device_name: str
    device_type: str
    platform: str
    is_online: bool
    paired_with: list


# ---------------------------------------------------------------------------
# HTTP API endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "uptime": time.time(),
        "online_devices": len(registry.list_online_devices()),
        "total_devices": len(registry.list_devices()),
    }


@app.post("/pairing/token", response_model=PairingResponseModel)
async def generate_pairing_token(request: PairingRequestModel):
    """Generate a new pairing token (6-digit PIN).

    The token is valid for 5 minutes (configurable).
    """
    token = authenticator.generate_pairing_token(request.device_name)
    return PairingResponseModel(
        token=token,
        expires_in=config.auth_token_ttl,
    )


@app.post("/devices/register")
async def register_device(request: RegisterDeviceModel):
    """Register a new device with the relay server.

    If the device already exists, its information is updated.
    A shared secret is generated for HMAC authentication.
    """
    # Check device limit
    current_count = len([d for d in registry.list_devices() if d.device_type == request.device_type])
    if current_count >= config.max_devices_per_user:
        raise HTTPException(
            status_code=429,
            detail=f"Maximum device limit ({config.max_devices_per_user}) reached",
        )

    shared_secret = RelayAuthenticator.generate_shared_secret()
    device = registry.register_device(
        device_id=request.device_id,
        device_name=request.device_name,
        device_type=request.device_type,
        platform=request.platform,
        shared_secret=shared_secret,
    )

    return {
        "device_id": device.device_id,
        "shared_secret": shared_secret,
        "status": "registered",
    }


@app.get("/devices", response_model=list)
async def list_devices():
    """List all registered devices."""
    devices = registry.list_devices()
    return [
        DeviceInfoModel(
            device_id=d.device_id,
            device_name=d.device_name,
            device_type=d.device_type,
            platform=d.platform,
            is_online=d.is_online,
            paired_with=list(d.paired_with),
        )
        for d in devices
    ]


@app.get("/devices/{device_id}")
async def get_device(device_id: str):
    """Get information about a specific device."""
    device = registry.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    return DeviceInfoModel(
        device_id=device.device_id,
        device_name=device.device_name,
        device_type=device.device_type,
        platform=device.platform,
        is_online=device.is_online,
        paired_with=list(device.paired_with),
    )


@app.delete("/devices/{device_id}")
async def unregister_device(device_id: str):
    """Unregister a device from the relay server."""
    registry.unregister_device(device_id)
    return {"status": "unregistered"}


@app.post("/devices/{device_id_a}/pair/{device_id_b}")
async def pair_devices(device_id_a: str, device_id_b: str):
    """Establish a pairing relationship between two devices."""
    if not registry.pair_devices(device_id_a, device_id_b):
        raise HTTPException(status_code=404, detail="One or both devices not found")

    return {"status": "paired"}


@app.delete("/devices/{device_id_a}/pair/{device_id_b}")
async def unpair_devices(device_id_a: str, device_id_b: str):
    """Remove a pairing relationship between two devices."""
    if not registry.unpair_devices(device_id_a, device_id_b):
        raise HTTPException(status_code=404, detail="One or both devices not found")

    return {"status": "unpaired"}


@app.get("/devices/{device_id}/paired")
async def get_paired_devices(device_id: str):
    """Get all devices paired with the given device."""
    devices = registry.get_paired_devices(device_id)
    return [
        DeviceInfoModel(
            device_id=d.device_id,
            device_name=d.device_name,
            device_type=d.device_type,
            platform=d.platform,
            is_online=d.is_online,
            paired_with=list(d.paired_with),
        )
        for d in devices
    ]


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time sync message relay.

    Authentication flow:
    1. Client connects via WebSocket
    2. Server sends auth_challenge with a nonce
    3. Client sends auth_response with HMAC(shared_secret, nonce)
    4. Server verifies and sends auth_ok or auth_fail
    5. Once authenticated, messages are relayed between paired devices
    """
    await websocket.accept()

    device_id: str = ""
    try:
        # Step 1: Send auth challenge
        import json
        import struct

        nonce = authenticator.generate_challenge()
        challenge_msg = {
            "version": 1,
            "type": "auth_challenge",
            "origin": "",
            "timestamp": "",
            "payload": {"nonce": nonce},
            "binary_length": 0,
        }
        challenge_json = json.dumps(challenge_msg, separators=(",", ":")).encode("utf-8")
        challenge_frame = struct.pack("!H", len(challenge_json)) + challenge_json
        await websocket.send_bytes(challenge_frame)

        # Step 2: Wait for auth response
        raw_data = await asyncio.wait_for(websocket.receive_bytes(), timeout=15.0)

        # Decode the response
        if len(raw_data) < 2:
            await websocket.close(1008, "Invalid message format")
            return

        header_len = struct.unpack("!H", raw_data[:2])[0]
        if len(raw_data) < 2 + header_len:
            await websocket.close(1008, "Invalid message format")
            return

        header_json = json.loads(raw_data[2:2 + header_len].decode("utf-8"))
        msg_type = header_json.get("type", "")
        msg_origin = header_json.get("origin", "")
        msg_payload = header_json.get("payload", {})

        if msg_type != "auth_response":
            await websocket.close(1008, "Expected auth_response")
            return

        # Step 3: Verify HMAC
        hmac_response = msg_payload.get("hmac", "")
        device_id = msg_origin

        if not device_id:
            await _send_auth_fail(websocket)
            await websocket.close(1008, "Missing device ID")
            return

        device = registry.get_device(device_id)
        if not device:
            await _send_auth_fail(websocket)
            await websocket.close(1008, "Device not registered")
            return

        if not authenticator.verify_hmac(device.shared_secret, nonce, hmac_response):
            await _send_auth_fail(websocket)
            await websocket.close(1008, "Authentication failed")
            return

        # Step 4: Send auth_ok
        auth_ok_msg = {
            "version": 1,
            "type": "auth_ok",
            "origin": "",
            "timestamp": "",
            "payload": {},
            "binary_length": 0,
        }
        auth_ok_json = json.dumps(auth_ok_msg, separators=(",", ":")).encode("utf-8")
        auth_ok_frame = struct.pack("!H", len(auth_ok_json)) + auth_ok_json
        await websocket.send_bytes(auth_ok_frame)

        # Mark device as online
        registry.set_online(device_id, websocket)
        logger.info("Device authenticated and online: %s", device_id)

        # Create session
        session = authenticator.create_session(device_id)

        # Notify paired devices about online status
        await signaling_handler.notify_device_online(device_id)

        # Step 5: Message relay loop
        while True:
            try:
                raw_data = await websocket.receive_bytes()
                await signaling_handler.handle_message(device_id, raw_data)
            except WebSocketDisconnect:
                break
            except Exception as e:
                logger.error("Error in relay loop for %s: %s", device_id, e)
                break

    except asyncio.TimeoutError:
        logger.warning("Auth timeout for connection")
        try:
            await websocket.close(1008, "Authentication timeout")
        except Exception:
            pass
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error("Error in WebSocket handler: %s", e)
        try:
            await websocket.close(1011, "Internal server error")
        except Exception:
            pass
    finally:
        if device_id:
            registry.set_offline(device_id)
            authenticator.revoke_session(device_id)
            await signaling_handler.notify_device_offline(device_id)
            logger.info("Device offline: %s", device_id)


async def _send_auth_fail(websocket: WebSocket) -> None:
    """Send an auth_fail message to the client."""
    import json
    import struct

    fail_msg = {
        "version": 1,
        "type": "auth_fail",
        "origin": "",
        "timestamp": "",
        "payload": {},
        "binary_length": 0,
    }
    fail_json = json.dumps(fail_msg, separators=(",", ":")).encode("utf-8")
    fail_frame = struct.pack("!H", len(fail_json)) + fail_json
    try:
        await websocket.send_bytes(fail_frame)
    except Exception:
        pass


async def _periodic_cleanup() -> None:
    """Periodic cleanup task for expired tokens and sessions."""
    while True:
        await asyncio.sleep(60)  # Run every minute
        authenticator.cleanup_expired()
        registry.cleanup_offline()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Run the relay server using uvicorn."""
    import uvicorn

    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "relay_server.server:app",
        host=config.host,
        port=config.port,
        log_level=config.log_level.lower(),
    )


if __name__ == "__main__":
    main()
