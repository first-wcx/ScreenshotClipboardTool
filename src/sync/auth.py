"""
Authentication utilities for the ICC multi-device sync system.

Provides HMAC-SHA256 challenge-response authentication,
pairing token generation, and shared secret generation.
This module is the Python-side counterpart to the Android
DeviceAuthenticator class.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import string
from typing import Optional


def generate_challenge() -> str:
    """Generate a 32-character random nonce for HMAC challenge-response.

    Returns:
        A hex-encoded random string of 32 characters.
    """
    return secrets.token_hex(16)


def compute_hmac(secret: str, challenge: str) -> str:
    """Compute HMAC-SHA256 of a challenge using the shared secret.

    Args:
        secret: The shared secret key.
        challenge: The challenge nonce string.

    Returns:
        Hex-encoded HMAC-SHA256 digest.
    """
    return hmac.new(
        secret.encode("utf-8"),
        challenge.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac(secret: str, challenge: str, response: str) -> bool:
    """Verify an HMAC-SHA256 response against an expected value.

    Uses constant-time comparison to prevent timing attacks.

    Args:
        secret: The shared secret key.
        challenge: The challenge nonce that was sent.
        response: The HMAC response received from the client.

    Returns:
        True if the response matches the expected HMAC.
    """
    expected = compute_hmac(secret, challenge)
    return hmac.compare_digest(expected, response)


def generate_pairing_token() -> str:
    """Generate a 6-digit numeric PIN for device pairing.

    Returns:
        A string of 6 random digits (e.g., "123456").
    """
    return "".join(secrets.choice(string.digits) for _ in range(6))


def generate_shared_secret() -> str:
    """Generate a 32-character random hex string as a shared secret.

    The shared secret is exchanged during pairing and used for
    subsequent HMAC-based authentication.

    Returns:
        A 32-character hex-encoded random string.
    """
    return secrets.token_hex(16)
