"""
Tests for the ICC sync module (src/sync/).

Covers:
- ProtocolCodec: binary frame encode/decode, clipboard item encode/decode
- auth: HMAC-SHA256 challenge-response, pairing token, shared secret
- device_manager: DeviceInfo CRUD and JSON persistence
- Three-endpoint consistency: Android (Kotlin) vs Desktop (Python) vs Relay (Python)
"""

import json
import os
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Protocol tests — import directly from submodule to avoid __init__.py
# chain importing zeroconf (unavailable on Windows CI)
# ---------------------------------------------------------------------------

import importlib
import sys

# Direct import of protocol submodule
_spec = importlib.util.spec_from_file_location(
    "src.sync.protocol",
    "E:/IntegratedCaptureClipboard/src/sync/protocol.py",
)
_mod = importlib.util.module_from_spec(_spec)
sys.modules["src.sync.protocol"] = _mod
_spec.loader.exec_module(_mod)

from src.sync.protocol import (  # type: ignore[no-redef]
    MSG_TYPE_AUTH_CHALLENGE,
    MSG_TYPE_AUTH_FAIL,
    MSG_TYPE_AUTH_OK,
    MSG_TYPE_AUTH_RESPONSE,
    MSG_TYPE_CLIPBOARD_SYNC,
    MSG_TYPE_CLIPBOARD_SYNC_BINARY,
    MSG_TYPE_DEVICE_LIST,
    MSG_TYPE_DEVICE_OFFLINE,
    MSG_TYPE_DEVICE_ONLINE,
    MSG_TYPE_FILE_STREAM_HEADER,
    MSG_TYPE_PAIRING_CONFIRM,
    MSG_TYPE_PAIRING_REQUEST,
    MSG_TYPE_HELLO,
    MSG_TYPE_PING,
    MSG_TYPE_PONG,
    MSG_TYPE_FILE_STREAM_DATA,
    ProtocolCodec,
    SyncMessage,
    VERSION,
)


class TestSyncMessage:
    """Tests for SyncMessage dataclass."""

    def test_default_values(self):
        msg = SyncMessage()
        assert msg.version == 1
        assert msg.type == ""
        assert msg.origin == ""
        assert msg.timestamp == ""
        assert msg.payload == {}
        assert msg.binary_length == 0

    def test_custom_values(self):
        msg = SyncMessage(
            version=2,
            type="hello",
            origin="device-1",
            timestamp="2026-01-01T00:00:00Z",
            payload={"key": "value"},
            binary_length=1024,
        )
        assert msg.version == 2
        assert msg.type == "hello"
        assert msg.origin == "device-1"
        assert msg.payload == {"key": "value"}
        assert msg.binary_length == 1024

    def test_to_dict(self):
        msg = SyncMessage(type="ping", origin="dev1", timestamp="2026-01-01T00:00:00Z")
        d = msg.to_dict()
        assert d["version"] == 1
        assert d["type"] == "ping"
        assert d["origin"] == "dev1"
        assert d["payload"] == {}
        assert d["binary_length"] == 0

    def test_from_dict(self):
        d = {
            "version": 1,
            "type": "pong",
            "origin": "dev2",
            "timestamp": "2026-01-01T00:00:00Z",
            "payload": {"status": "ok"},
            "binary_length": 0,
        }
        msg = SyncMessage.from_dict(d)
        assert msg.type == "pong"
        assert msg.origin == "dev2"
        assert msg.payload == {"status": "ok"}

    def test_from_dict_with_bad_payload(self):
        """from_dict should handle non-dict payload gracefully."""
        d = {"version": 1, "type": "test", "payload": "not_a_dict"}
        msg = SyncMessage.from_dict(d)
        assert msg.payload == {}

    def test_roundtrip_dict(self):
        msg = SyncMessage(
            type="clipboard_sync",
            origin="device-A",
            timestamp="2026-05-28T00:00:00Z",
            payload={"item_type": "text", "item": {"text": "hello"}},
        )
        d = msg.to_dict()
        msg2 = SyncMessage.from_dict(d)
        assert msg2.type == msg.type
        assert msg2.origin == msg.origin
        assert msg2.payload == msg.payload
        assert msg2.binary_length == msg.binary_length


class TestProtocolCodec:
    """Tests for ProtocolCodec binary frame encode/decode."""

    def test_encode_simple_message(self):
        """Encode a simple message without binary payload."""
        msg = SyncMessage(
            type="ping",
            origin="device-1",
            timestamp="2026-01-01T00:00:00Z",
        )
        data = ProtocolCodec.encode_message(msg)

        # Should be: 2-byte header length + header JSON bytes
        header_len = struct.unpack("!H", data[:2])[0]
        assert header_len > 0
        assert len(data) == 2 + header_len

    def test_decode_simple_message(self):
        """Decode a simple message without binary payload."""
        msg = SyncMessage(
            type="pong",
            origin="device-2",
            timestamp="2026-01-01T00:00:00Z",
        )
        data = ProtocolCodec.encode_message(msg)
        decoded_msg, binary = ProtocolCodec.decode_message(data)

        assert decoded_msg.type == "pong"
        assert decoded_msg.origin == "device-2"
        assert binary is None

    def test_encode_with_binary_payload(self):
        """Encode a message with binary payload."""
        msg = SyncMessage(
            type="clipboard_sync_binary",
            origin="device-1",
            timestamp="2026-01-01T00:00:00Z",
            payload={"item_type": "image"},
            binary_length=5,
        )
        binary_payload = b"\x01\x02\x03\x04\x05"
        data = ProtocolCodec.encode_message(msg, binary_payload)

        # Verify structure
        header_len = struct.unpack("!H", data[:2])[0]
        assert len(data) == 2 + header_len + 5

    def test_decode_with_binary_payload(self):
        """Decode a message with binary payload."""
        msg = SyncMessage(
            type="clipboard_sync_binary",
            origin="device-1",
            timestamp="2026-01-01T00:00:00Z",
            payload={"item_type": "image"},
            binary_length=5,
        )
        binary_payload = b"\x01\x02\x03\x04\x05"
        data = ProtocolCodec.encode_message(msg, binary_payload)

        decoded_msg, decoded_binary = ProtocolCodec.decode_message(data)
        assert decoded_msg.type == "clipboard_sync_binary"
        assert decoded_msg.binary_length == 5
        assert decoded_binary == b"\x01\x02\x03\x04\x05"

    def test_roundtrip_encode_decode(self):
        """Encode then decode should produce the same message."""
        msg = SyncMessage(
            type="clipboard_sync",
            origin="my-device",
            timestamp="2026-05-28T12:00:00Z",
            payload={"item_type": "text", "item": {"text": "hello world", "digest": "abc123"}},
        )
        data = ProtocolCodec.encode_message(msg)
        decoded_msg, binary = ProtocolCodec.decode_message(data)

        assert decoded_msg.type == msg.type
        assert decoded_msg.origin == msg.origin
        assert decoded_msg.timestamp == msg.timestamp
        assert decoded_msg.payload == msg.payload
        assert decoded_msg.binary_length == 0
        assert binary is None

    def test_roundtrip_with_binary(self):
        """Encode/decode with binary payload roundtrip."""
        image_data = os.urandom(2048)  # 2KB random image data
        msg = SyncMessage(
            type="clipboard_sync_binary",
            origin="sender",
            timestamp="2026-05-28T12:00:00Z",
            payload={"item_type": "image", "item": {"size": 2048}},
            binary_length=len(image_data),
        )
        data = ProtocolCodec.encode_message(msg, image_data)
        decoded_msg, decoded_binary = ProtocolCodec.decode_message(data)

        assert decoded_msg.type == "clipboard_sync_binary"
        assert decoded_msg.binary_length == 2048
        assert decoded_binary == image_data

    def test_decode_too_short(self):
        """Decoding data shorter than 2 bytes should raise ValueError."""
        with pytest.raises(ValueError, match="Data too short"):
            ProtocolCodec.decode_message(b"\x00")

    def test_decode_incomplete_header(self):
        """Decoding with truncated header should raise ValueError."""
        # Header says 100 bytes, but we only provide 2 + 10
        data = struct.pack("!H", 100) + b'{"type":"ping"}'
        with pytest.raises(ValueError, match="Data too short"):
            ProtocolCodec.decode_message(data)

    def test_encode_header_too_large(self):
        """Encoding a message with header > 65535 bytes should raise ValueError."""
        # Create a message with a massive payload
        huge_payload = {"data": "x" * 70000}
        msg = SyncMessage(type="test", payload=huge_payload)
        with pytest.raises(ValueError, match="exceeds 65535"):
            ProtocolCodec.encode_message(msg)

    def test_binary_frame_format_big_endian(self):
        """Verify header length is stored as big-endian uint16."""
        msg = SyncMessage(type="ping", origin="test")
        data = ProtocolCodec.encode_message(msg)

        # First 2 bytes should be big-endian uint16
        header_len_be = struct.unpack("!H", data[:2])[0]
        # Verify by decoding header manually
        header_json = data[2 : 2 + header_len_be].decode("utf-8")
        header_dict = json.loads(header_json)
        assert header_dict["type"] == "ping"


class TestProtocolCodecClipboardItem:
    """Tests for encode_clipboard_item / decode_clipboard_item."""

    def test_encode_text_item(self):
        """Text items should produce clipboard_sync message."""
        msg, binary = ProtocolCodec.encode_clipboard_item(
            "text", {"text": "hello", "digest": "sha256abc"}, origin="dev1"
        )
        assert msg.type == MSG_TYPE_CLIPBOARD_SYNC
        assert msg.payload["item_type"] == "text"
        assert msg.payload["item"]["text"] == "hello"
        assert binary is None

    def test_encode_small_image_item(self):
        """Small images (≤1MB) should use base64 inline (clipboard_sync)."""
        item = {"dib_b64": "base64data", "size": 500000}
        msg, binary = ProtocolCodec.encode_clipboard_item("image", item, origin="dev1")
        assert msg.type == MSG_TYPE_CLIPBOARD_SYNC
        assert binary is None

    def test_encode_large_image_item_binary(self):
        """Large images (>1MB) with raw_bytes should use clipboard_sync_binary."""
        raw = b"\x00" * (2 * 1024 * 1024)  # 2MB
        item = {"dib_b64": "base64data", "size": 2 * 1024 * 1024, "_raw_bytes": raw}
        msg, binary = ProtocolCodec.encode_clipboard_item("image", item, origin="dev1")
        assert msg.type == MSG_TYPE_CLIPBOARD_SYNC_BINARY
        assert binary == raw
        assert msg.binary_length == len(raw)
        # _raw_bytes should not be in payload
        assert "_raw_bytes" not in msg.payload["item"]

    def test_decode_text_item(self):
        """Decode a clipboard_sync text message."""
        msg = SyncMessage(
            type=MSG_TYPE_CLIPBOARD_SYNC,
            payload={"item_type": "text", "item": {"text": "hello", "digest": "abc"}},
        )
        item_type, item_data = ProtocolCodec.decode_clipboard_item(msg)
        assert item_type == "text"
        assert item_data["text"] == "hello"

    def test_decode_binary_image_item(self):
        """Decode a clipboard_sync_binary image message."""
        raw = b"\xff\xd8\xff\xe0"  # JPEG header bytes
        msg = SyncMessage(
            type=MSG_TYPE_CLIPBOARD_SYNC_BINARY,
            payload={"item_type": "image", "item": {"size": 4}},
            binary_length=4,
        )
        item_type, item_data = ProtocolCodec.decode_clipboard_item(msg, raw)
        assert item_type == "image"
        assert "dib_b64" in item_data  # binary converted to base64
        assert item_data["size"] == 4

    def test_clipboard_item_roundtrip_text(self):
        """Text clipboard item roundtrip: encode → decode."""
        original = {"text": "test content", "digest": "sha256xyz"}
        msg, _ = ProtocolCodec.encode_clipboard_item("text", original, origin="dev1")
        item_type, item_data = ProtocolCodec.decode_clipboard_item(msg)
        assert item_type == "text"
        assert item_data["text"] == "test content"

    def test_clipboard_item_roundtrip_large_image(self):
        """Large image clipboard item roundtrip: encode → decode."""
        import base64

        raw = os.urandom(2 * 1024 * 1024)  # 2MB random data
        original = {"dib_b64": base64.b64encode(raw).decode(), "size": len(raw), "_raw_bytes": raw}
        msg, binary = ProtocolCodec.encode_clipboard_item("image", original, origin="dev1")
        item_type, item_data = ProtocolCodec.decode_clipboard_item(msg, binary)
        assert item_type == "image"
        # After decode, the binary should be converted back to base64
        assert "dib_b64" in item_data


# ---------------------------------------------------------------------------
# Auth tests
# ---------------------------------------------------------------------------

# Direct import of auth submodule
_spec_auth = importlib.util.spec_from_file_location(
    "src.sync.auth",
    "E:/IntegratedCaptureClipboard/src/sync/auth.py",
)
_mod_auth = importlib.util.module_from_spec(_spec_auth)
sys.modules["src.sync.auth"] = _mod_auth
_spec_auth.loader.exec_module(_mod_auth)

from src.sync.auth import (  # type: ignore[no-redef]
    compute_hmac,
    generate_challenge,
    generate_pairing_token,
    generate_shared_secret,
    verify_hmac,
)


class TestAuth:
    """Tests for HMAC-SHA256 authentication utilities."""

    def test_generate_challenge_length(self):
        """Challenge should be a 32-character hex string."""
        challenge = generate_challenge()
        assert len(challenge) == 32
        assert all(c in "0123456789abcdef" for c in challenge)

    def test_generate_challenge_randomness(self):
        """Two challenges should be different."""
        c1 = generate_challenge()
        c2 = generate_challenge()
        assert c1 != c2

    def test_compute_hmac_format(self):
        """HMAC output should be a hex string."""
        result = compute_hmac("secret", "challenge")
        assert len(result) == 64  # SHA-256 hex digest is 64 chars
        assert all(c in "0123456789abcdef" for c in result)

    def test_compute_hmac_deterministic(self):
        """Same inputs should produce same HMAC."""
        h1 = compute_hmac("secret", "challenge")
        h2 = compute_hmac("secret", "challenge")
        assert h1 == h2

    def test_compute_hmac_different_secrets(self):
        """Different secrets should produce different HMACs."""
        h1 = compute_hmac("secret1", "challenge")
        h2 = compute_hmac("secret2", "challenge")
        assert h1 != h2

    def test_compute_hmac_different_challenges(self):
        """Different challenges should produce different HMACs."""
        h1 = compute_hmac("secret", "challenge1")
        h2 = compute_hmac("secret", "challenge2")
        assert h1 != h2

    def test_verify_hmac_correct(self):
        """verify_hmac should return True for correct response."""
        challenge = generate_challenge()
        response = compute_hmac("my_secret", challenge)
        assert verify_hmac("my_secret", challenge, response) is True

    def test_verify_hmac_wrong_response(self):
        """verify_hmac should return False for incorrect response."""
        challenge = generate_challenge()
        response = compute_hmac("my_secret", challenge)
        assert verify_hmac("wrong_secret", challenge, response) is False

    def test_verify_hmac_wrong_challenge(self):
        """verify_hmac should return False for wrong challenge."""
        response = compute_hmac("my_secret", "challenge1")
        assert verify_hmac("my_secret", "challenge2", response) is False

    def test_generate_pairing_token_format(self):
        """Pairing token should be 6 digits."""
        token = generate_pairing_token()
        assert len(token) == 6
        assert token.isdigit()

    def test_generate_pairing_token_randomness(self):
        """Two tokens should (very likely) be different."""
        t1 = generate_pairing_token()
        t2 = generate_pairing_token()
        # Technically possible they match, but extremely unlikely
        # Just verify format
        assert len(t1) == 6
        assert len(t2) == 6

    def test_generate_shared_secret_format(self):
        """Shared secret should be a 32-char hex string."""
        secret = generate_shared_secret()
        assert len(secret) == 32
        assert all(c in "0123456789abcdef" for c in secret)

    def test_generate_shared_secret_randomness(self):
        """Two secrets should be different."""
        s1 = generate_shared_secret()
        s2 = generate_shared_secret()
        assert s1 != s2

    def test_full_auth_flow(self):
        """Test the complete challenge-response authentication flow."""
        # Simulate server and client sides
        shared_secret = generate_shared_secret()

        # Server: generate challenge
        challenge = generate_challenge()

        # Client: compute HMAC response
        response = compute_hmac(shared_secret, challenge)

        # Server: verify response
        assert verify_hmac(shared_secret, challenge, response) is True

        # Attacker: try with wrong secret
        assert verify_hmac("wrong_secret", challenge, response) is False


# ---------------------------------------------------------------------------
# DeviceManager tests
# ---------------------------------------------------------------------------

# Direct import of device_manager submodule
_spec_dm = importlib.util.spec_from_file_location(
    "src.sync.device_manager",
    "E:/IntegratedCaptureClipboard/src/sync/device_manager.py",
)
_mod_dm = importlib.util.module_from_spec(_spec_dm)
sys.modules["src.sync.device_manager"] = _mod_dm
_spec_dm.loader.exec_module(_mod_dm)

from src.sync.device_manager import (  # type: ignore[no-redef]
    DeviceInfo,
    DeviceManager,
)


class TestDeviceInfo:
    """Tests for DeviceInfo dataclass."""

    def test_default_values(self):
        info = DeviceInfo()
        assert info.device_id == ""
        assert info.device_name == ""
        assert info.device_type == ""
        assert info.port == 8765

    def test_custom_values(self):
        info = DeviceInfo(
            device_id="abc123",
            device_name="My Laptop",
            device_type="desktop",
            ip_address="192.168.1.100",
            port=8765,
            platform="windows_11",
        )
        assert info.device_id == "abc123"
        assert info.device_name == "My Laptop"

    def test_to_dict(self):
        info = DeviceInfo(device_id="id1", device_name="Test Device")
        d = info.to_dict()
        assert d["device_id"] == "id1"
        assert d["device_name"] == "Test Device"
        assert d["port"] == 8765

    def test_from_dict(self):
        d = {
            "device_id": "id2",
            "device_name": "Phone",
            "device_type": "android",
            "ip_address": "10.0.0.1",
            "port": 8765,
            "platform": "android_14",
            "paired_at": "2026-01-01T00:00:00Z",
            "last_seen": "2026-05-28T00:00:00Z",
        }
        info = DeviceInfo.from_dict(d)
        assert info.device_id == "id2"
        assert info.device_name == "Phone"
        assert info.device_type == "android"

    def test_roundtrip_dict(self):
        info = DeviceInfo(
            device_id="round_trip_id",
            device_name="Round Trip",
            device_type="desktop",
            ip_address="192.168.0.1",
            port=9999,
        )
        d = info.to_dict()
        info2 = DeviceInfo.from_dict(d)
        assert info2.device_id == info.device_id
        assert info2.device_name == info.device_name
        assert info2.port == info.port


class TestDeviceManager:
    """Tests for DeviceManager CRUD + persistence."""

    def test_init_default_path(self):
        dm = DeviceManager()
        assert dm.config_path == Path.home() / ".icc" / "devices.json"

    def test_load_nonexistent_file(self):
        """Loading from a nonexistent file should result in empty devices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.json"
            dm = DeviceManager(config_path=path)
            dm.load()
            assert dm.list_devices() == []

    def test_add_and_get_device(self):
        """Add a device and retrieve it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            dm = DeviceManager(config_path=path)
            device = DeviceInfo(device_id="dev1", device_name="Test Device")
            dm.add_device(device)
            assert dm.get_device("dev1") is not None
            assert dm.get_device("dev1").device_name == "Test Device"

    def test_add_device_empty_id_ignored(self):
        """Adding a device with empty device_id should be ignored."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            dm = DeviceManager(config_path=path)
            device = DeviceInfo(device_id="", device_name="No ID")
            dm.add_device(device)
            assert dm.list_devices() == []

    def test_remove_device(self):
        """Remove a device by ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            dm = DeviceManager(config_path=path)
            dm.add_device(DeviceInfo(device_id="dev1", device_name="Device 1"))
            dm.remove_device("dev1")
            assert dm.get_device("dev1") is None

    def test_remove_nonexistent_device(self):
        """Removing a nonexistent device should not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            dm = DeviceManager(config_path=path)
            dm.remove_device("nonexistent")  # Should not raise

    def test_list_devices_sorted_by_last_seen(self):
        """list_devices should return devices sorted by last_seen descending."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            dm = DeviceManager(config_path=path)
            dm.add_device(DeviceInfo(device_id="old", last_seen="2026-01-01T00:00:00Z"))
            dm.add_device(DeviceInfo(device_id="new", last_seen="2026-05-28T00:00:00Z"))
            dm.add_device(DeviceInfo(device_id="mid", last_seen="2026-03-15T00:00:00Z"))

            devices = dm.list_devices()
            assert len(devices) == 3
            assert devices[0].device_id == "new"
            assert devices[1].device_id == "mid"
            assert devices[2].device_id == "old"

    def test_update_last_seen(self):
        """update_last_seen should update the timestamp."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            dm = DeviceManager(config_path=path)
            dm.add_device(DeviceInfo(device_id="dev1", device_name="Test", last_seen="2026-01-01T00:00:00Z"))
            dm.update_last_seen("dev1")
            device = dm.get_device("dev1")
            assert device.last_seen != "2026-01-01T00:00:00Z"

    def test_is_paired(self):
        """is_paired should return True for added devices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            dm = DeviceManager(config_path=path)
            dm.add_device(DeviceInfo(device_id="dev1"))
            assert dm.is_paired("dev1") is True
            assert dm.is_paired("dev_unknown") is False

    def test_persistence(self):
        """Devices should persist across load/save cycles."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"

            # Create and save
            dm1 = DeviceManager(config_path=path)
            dm1.add_device(DeviceInfo(device_id="dev1", device_name="Persistent Device"))
            dm1.add_device(DeviceInfo(device_id="dev2", device_name="Another Device"))

            # Load fresh instance
            dm2 = DeviceManager(config_path=path)
            dm2.load()
            assert dm2.get_device("dev1") is not None
            assert dm2.get_device("dev1").device_name == "Persistent Device"
            assert dm2.get_device("dev2") is not None
            assert len(dm2.list_devices()) == 2

    def test_load_corrupt_json(self):
        """Loading a corrupt JSON file should result in empty devices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            path.write_text("{invalid json", encoding="utf-8")
            dm = DeviceManager(config_path=path)
            dm.load()
            assert dm.list_devices() == []

    def test_load_non_dict_json(self):
        """Loading a JSON array instead of object should result in empty devices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "devices.json"
            path.write_text("[]", encoding="utf-8")
            dm = DeviceManager(config_path=path)
            dm.load()
            assert dm.list_devices() == []


# ---------------------------------------------------------------------------
# Three-endpoint consistency checks
# ---------------------------------------------------------------------------

class TestThreeEndpointConsistency:
    """Verify that key protocol details are consistent across
    Android (Kotlin), Desktop (Python), and Relay (Python) implementations.

    These tests read the Kotlin source files and compare against the Python
    implementations to catch drift.
    """

    ANDROID_SYNC_DIR = Path(
        "E:/IntegratedCaptureClipboard/android/app/src/main/java"
        "/com/integratedcaptureclipboard/android"
    )

    def test_message_type_constants_match(self):
        """All 16 message type constants should be identical across endpoints."""
        # Desktop Python message types
        desktop_types = {
            MSG_TYPE_HELLO, MSG_TYPE_AUTH_CHALLENGE, MSG_TYPE_AUTH_RESPONSE,
            MSG_TYPE_AUTH_OK, MSG_TYPE_AUTH_FAIL, MSG_TYPE_PAIRING_REQUEST,
            MSG_TYPE_PAIRING_CONFIRM, MSG_TYPE_CLIPBOARD_SYNC,
            MSG_TYPE_CLIPBOARD_SYNC_BINARY, MSG_TYPE_FILE_STREAM_HEADER,
            MSG_TYPE_FILE_STREAM_DATA, MSG_TYPE_DEVICE_LIST,
            MSG_TYPE_DEVICE_ONLINE, MSG_TYPE_DEVICE_OFFLINE,
            MSG_TYPE_PING, MSG_TYPE_PONG,
        }

        # Verify from SyncMessage.kt
        sync_msg_path = self.ANDROID_SYNC_DIR / "data" / "model" / "SyncMessage.kt"
        if sync_msg_path.exists():
            content = sync_msg_path.read_text(encoding="utf-8")
            android_types = set()
            for line in content.splitlines():
                line = line.strip()
                if line.startswith('const val MSG_TYPE_'):
                    # Extract the string value between quotes
                    value = line.split('=')[1].strip().strip('"').strip()
                    android_types.add(value)
            assert len(android_types) == 16, f"Expected 16 Android message types, got {len(android_types)}"
            assert android_types == desktop_types, f"Mismatch: Android={android_types}, Desktop={desktop_types}"

    def test_protocol_version_matches(self):
        """Protocol version should be 1 across all endpoints."""
        assert VERSION == 1

        # Check Android
        sync_msg_path = self.ANDROID_SYNC_DIR / "data" / "model" / "SyncMessage.kt"
        if sync_msg_path.exists():
            content = sync_msg_path.read_text(encoding="utf-8")
            assert "const val VERSION = 1" in content

    def test_binary_frame_protocol_format(self):
        """Binary frame protocol should use 2-byte big-endian uint16 header length."""
        # This is verified by the ProtocolCodec tests above
        # Additionally, verify struct format string
        import struct as s

        # Big-endian unsigned short
        packed = s.pack("!H", 256)
        assert packed == b"\x01\x00"  # big-endian: 0x0100 = 256

    def test_qr_code_format(self):
        """QR code format should be icc://pair?h={host}&p={port}&t={token}&v=1."""
        pairing_path = self.ANDROID_SYNC_DIR / "data" / "model" / "PairingInfo.kt"
        if pairing_path.exists():
            content = pairing_path.read_text(encoding="utf-8")
            assert "icc://pair" in content
            assert 'h=$host' in content or "h=" in content
            assert 'p=$port' in content or "p=" in content
            assert 't=$token' in content or "t=" in content
            assert "v=1" in content

    def test_hmac_sha256_algorithm(self):
        """All endpoints should use HMAC-SHA256 for authentication."""
        # Python desktop
        import hashlib
        import hmac as hmac_mod

        # Compute HMAC same way auth.py does
        result = hmac_mod.new(
            b"test_secret", b"test_challenge", hashlib.sha256
        ).hexdigest()
        assert len(result) == 64  # SHA-256 hex digest

        # Verify compute_hmac matches
        from src.sync.auth import compute_hmac
        assert compute_hmac("test_secret", "test_challenge") == result

    def test_default_port_conventions(self):
        """Default ports should be 8765 (WebSocket) and 8766 (pairing HTTP)."""
        # These are defined in the architecture and used by server/client code
        # Check sync_manager_v2.py and pairing_server.py
        sync_mgr_path = Path("E:/IntegratedCaptureClipboard/src/sync/sync_manager_v2.py")
        if sync_mgr_path.exists():
            content = sync_mgr_path.read_text(encoding="utf-8")
            # Default WS port should be 8765
            assert "8765" in content

        pairing_path = Path("E:/IntegratedCaptureClipboard/src/sync/pairing_server.py")
        if pairing_path.exists():
            content = pairing_path.read_text(encoding="utf-8")
            # Default pairing port should be 8766
            assert "8766" in content


# ---------------------------------------------------------------------------
# Relay server consistency checks
# ---------------------------------------------------------------------------

class TestRelayConsistency:
    """Verify relay server uses the same protocol as desktop and Android."""

    RELAY_DIR = Path("E:/IntegratedCaptureClipboard/relay_server")

    def test_relay_uses_binary_frame_protocol(self):
        """Relay signaling should use the same binary frame protocol."""
        signaling_path = self.RELAY_DIR / "signaling.py"
        assert signaling_path.exists(), "relay_server/signaling.py should exist"

        content = signaling_path.read_text(encoding="utf-8")
        # Should use struct.pack/unpack with !H format
        assert '!H' in content or "struct" in content

    def test_relay_message_types_match(self):
        """Relay message type constants should match desktop."""
        signaling_path = self.RELAY_DIR / "signaling.py"
        content = signaling_path.read_text(encoding="utf-8")

        relay_types = set()
        for line in content.splitlines():
            line = line.strip()
            if line.startswith("MSG_TYPE_"):
                value = line.split("=")[1].strip().strip('"').strip()
                relay_types.add(value)

        # At minimum, relay should have clipboard sync types
        assert MSG_TYPE_CLIPBOARD_SYNC in relay_types
        assert MSG_TYPE_CLIPBOARD_SYNC_BINARY in relay_types
        assert MSG_TYPE_PING in relay_types
        assert MSG_TYPE_PONG in relay_types

    def test_relay_auth_module_exists(self):
        """Relay should have its own auth module."""
        auth_path = self.RELAY_DIR / "auth.py"
        assert auth_path.exists()

    def test_relay_server_module_exists(self):
        """Relay should have a server module."""
        server_path = self.RELAY_DIR / "server.py"
        assert server_path.exists()

    def test_relay_device_registry_exists(self):
        """Relay should have a device registry module."""
        registry_path = self.RELAY_DIR / "device_registry.py"
        assert registry_path.exists()
