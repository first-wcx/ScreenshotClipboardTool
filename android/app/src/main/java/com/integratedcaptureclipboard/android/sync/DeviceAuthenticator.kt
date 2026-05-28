package com.integratedcaptureclipboard.android.sync

import java.security.InvalidKeyException
import java.security.NoSuchAlgorithmException
import java.security.SecureRandom
import javax.crypto.Mac
import javax.crypto.spec.SecretKeySpec

/**
 * Device authenticator for the ICC multi-device sync system.
 *
 * Provides HMAC-SHA256 challenge-response authentication,
 * consistent with the Python-side auth module (src/sync/auth.py)
 * and relay server authenticator (relay_server/auth.py).
 *
 * Authentication flow:
 * 1. Server sends auth_challenge with a random nonce
 * 2. Client computes HMAC-SHA256(shared_secret, nonce) and returns auth_response
 * 3. Server verifies the HMAC response
 */
object DeviceAuthenticator {

    private const val HMAC_ALGORITHM = "HmacSHA256"
    private const val CHALLENGE_LENGTH = 16 // 16 bytes -> 32 hex characters
    private const val TOKEN_DIGIT_COUNT = 6

    /**
     * Generate a 32-character random nonce for HMAC challenge-response.
     *
     * @return A hex-encoded random string of 32 characters.
     */
    fun generateChallenge(): String {
        val bytes = ByteArray(CHALLENGE_LENGTH)
        SecureRandom().nextBytes(bytes)
        return bytes.joinToString("") { "%02x".format(it) }
    }

    /**
     * Compute HMAC-SHA256 of a challenge using the shared secret.
     *
     * @param secret The shared secret key.
     * @param challenge The challenge nonce string.
     * @return Hex-encoded HMAC-SHA256 digest.
     */
    fun computeHmac(secret: String, challenge: String): String {
        try {
            val mac = Mac.getInstance(HMAC_ALGORITHM)
            val secretKeySpec = SecretKeySpec(secret.toByteArray(Charsets.UTF_8), HMAC_ALGORITHM)
            mac.init(secretKeySpec)
            val hmacBytes = mac.doFinal(challenge.toByteArray(Charsets.UTF_8))
            return hmacBytes.joinToString("") { "%02x".format(it) }
        } catch (e: NoSuchAlgorithmException) {
            throw RuntimeException("HMAC-SHA256 algorithm not available", e)
        } catch (e: InvalidKeyException) {
            throw RuntimeException("Invalid key for HMAC-SHA256", e)
        }
    }

    /**
     * Verify an HMAC-SHA256 response against an expected value.
     *
     * Uses constant-time comparison to prevent timing attacks.
     *
     * @param secret The shared secret key.
     * @param challenge The challenge nonce that was sent.
     * @param response The HMAC response received from the client.
     * @return True if the response matches the expected HMAC.
     */
    fun verifyHmac(secret: String, challenge: String, response: String): Boolean {
        val expected = computeHmac(secret, challenge)
        return constantTimeEquals(expected, response)
    }

    /**
     * Generate a 6-digit numeric PIN for device pairing.
     *
     * @return A string of 6 random digits (e.g. "123456").
     */
    fun generatePairingToken(): String {
        val random = SecureRandom()
        val digits = CharArray(TOKEN_DIGIT_COUNT)
        for (i in 0 until TOKEN_DIGIT_COUNT) {
            digits[i] = ('0' + random.nextInt(10))
        }
        return String(digits)
    }

    /**
     * Constant-time string comparison to prevent timing attacks.
     *
     * @param a First string.
     * @param b Second string.
     * @return True if the strings are equal.
     */
    private fun constantTimeEquals(a: String, b: String): Boolean {
        if (a.length != b.length) {
            return false
        }
        var result = 0
        for (i in a.indices) {
            result = result or (a[i].code xor b[i].code)
        }
        return result == 0
    }
}
