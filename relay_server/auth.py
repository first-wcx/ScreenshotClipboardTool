"""
Authentication utilities for the ICC relay server.

Provides async-compatible HMAC validation and token verification.
Logic is consistent with the desktop auth module (src/sync/auth.py)
but adapted for the relay server's async context.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import string
import time
from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class PendingToken:
    """Represents a pending pairing token awaiting confirmation.

    Attributes:
        token: The 6-digit PIN or UUID token string.
        created_at: Epoch timestamp when the token was created.
        device_name: Optional device name hint from the pairing request.
    """

    token: str
    created_at: float
    device_name: str = ""


@dataclass
class AuthSession:
    """Represents an authenticated session for a connected device.

    Attributes:
        device_id: The authenticated device's unique ID.
        session_token: The session token for this connection.
        created_at: Epoch timestamp when the session was established.
        expires_at: Epoch timestamp when the session expires.
    """

    device_id: str
    session_token: str
    created_at: float
    expires_at: float


class RelayAuthenticator:
    """Manages authentication for the relay server.

    Handles pairing token generation/validation and HMAC challenge-response
    verification for device authentication.
    """

    def __init__(
        self,
        token_ttl: int = 300,
        session_ttl: int = 86400,
    ) -> None:
        """Initialize the RelayAuthenticator.

        Args:
            token_ttl: Pairing token time-to-live in seconds (default: 5 minutes).
            session_ttl: Auth session time-to-live in seconds (default: 24 hours).
        """
        self.token_ttl = token_ttl
        self.session_ttl = session_ttl
        self._pending_tokens: Dict[str, PendingToken] = {}
        self._active_sessions: Dict[str, AuthSession] = {}

    # ------------------------------------------------------------------
    # HMAC utilities (same logic as src/sync/auth.py)
    # ------------------------------------------------------------------

    @staticmethod
    def generate_challenge() -> str:
        """Generate a 32-character random nonce for HMAC challenge.

        Returns:
            A hex-encoded random string of 32 characters.
        """
        return secrets.token_hex(16)

    @staticmethod
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

    @staticmethod
    def verify_hmac(secret: str, challenge: str, response: str) -> bool:
        """Verify an HMAC-SHA256 response using constant-time comparison.

        Args:
            secret: The shared secret key.
            challenge: The challenge nonce that was sent.
            response: The HMAC response received from the client.

        Returns:
            True if the response matches the expected HMAC.
        """
        expected = RelayAuthenticator.compute_hmac(secret, challenge)
        return hmac.compare_digest(expected, response)

    # ------------------------------------------------------------------
    # Pairing token management
    # ------------------------------------------------------------------

    def generate_pairing_token(self, device_name: str = "") -> str:
        """Generate a new pairing token (6-digit PIN).

        Args:
            device_name: Optional device name hint for the pairing.

        Returns:
            The generated 6-digit PIN string.
        """
        token = "".join(secrets.choice(string.digits) for _ in range(6))
        self._pending_tokens[token] = PendingToken(
            token=token,
            created_at=time.time(),
            device_name=device_name,
        )
        return token

    def validate_token(self, token: str) -> bool:
        """Validate a pairing token.

        A token is valid if it exists in the pending tokens and has not expired.

        Args:
            token: The pairing token to validate.

        Returns:
            True if the token is valid and not expired.
        """
        pending = self._pending_tokens.get(token)
        if pending is None:
            return False

        # Check expiration
        if time.time() - pending.created_at > self.token_ttl:
            # Clean up expired token
            del self._pending_tokens[token]
            return False

        return True

    def consume_token(self, token: str) -> Optional[PendingToken]:
        """Validate and consume a pairing token (one-time use).

        Args:
            token: The pairing token to consume.

        Returns:
            The PendingToken if valid, None otherwise.
        """
        if not self.validate_token(token):
            return None

        pending = self._pending_tokens.pop(token)
        return pending

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def create_session(self, device_id: str) -> AuthSession:
        """Create a new authentication session for a device.

        Args:
            device_id: The authenticated device's unique ID.

        Returns:
            The new AuthSession.
        """
        session_token = secrets.token_hex(32)
        now = time.time()
        session = AuthSession(
            device_id=device_id,
            session_token=session_token,
            created_at=now,
            expires_at=now + self.session_ttl,
        )
        self._active_sessions[session_token] = session
        return session

    def validate_session(self, session_token: str) -> Optional[AuthSession]:
        """Validate an existing session token.

        Args:
            session_token: The session token to validate.

        Returns:
            The AuthSession if valid and not expired, None otherwise.
        """
        session = self._active_sessions.get(session_token)
        if session is None:
            return None

        if time.time() > session.expires_at:
            del self._active_sessions[session_token]
            return None

        return session

    def revoke_session(self, session_token: str) -> None:
        """Revoke an active session.

        Args:
            session_token: The session token to revoke.
        """
        self._active_sessions.pop(session_token, None)

    def cleanup_expired(self) -> None:
        """Remove all expired tokens and sessions."""
        now = time.time()

        # Clean up expired pairing tokens
        expired_tokens = [
            t for t, p in self._pending_tokens.items()
            if now - p.created_at > self.token_ttl
        ]
        for t in expired_tokens:
            del self._pending_tokens[t]

        # Clean up expired sessions
        expired_sessions = [
            s for s, sess in self._active_sessions.items()
            if now > sess.expires_at
        ]
        for s in expired_sessions:
            del self._active_sessions[s]

    @staticmethod
    def generate_shared_secret() -> str:
        """Generate a 32-character random hex string as a shared secret.

        Returns:
            A 32-character hex-encoded random string.
        """
        return secrets.token_hex(16)
