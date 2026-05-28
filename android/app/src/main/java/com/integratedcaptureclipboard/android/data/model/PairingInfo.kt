package com.integratedcaptureclipboard.android.data.model

/**
 * Represents pairing information for QR-code or PIN-based device pairing.
 * Used when initiating a pairing session between devices.
 *
 * @property pairingId Unique identifier for this pairing session.
 * @property host Host address of the pairing server.
 * @property port Port number of the pairing server.
 * @property token Temporary pairing token (6-digit PIN or UUID).
 * @property expiresAt Expiration timestamp (epoch seconds).
 */
data class PairingInfo(
    val pairingId: String,
    val host: String,
    val port: Int,
    val token: String,
    val expiresAt: Long
) {
    companion object {
        /** QR code URI scheme prefix. */
        private const val QR_SCHEME = "icc://pair"

        /**
         * Parse a QR code text string into a PairingInfo.
         * Expected format: icc://pair?h={host}&p={port}&t={token}&v=1
         *
         * @param qrText The QR code content string.
         * @return PairingInfo if parsing succeeds, null otherwise.
         */
        fun fromQrText(qrText: String): PairingInfo? {
            if (!qrText.startsWith("$QR_SCHEME?")) {
                return null
            }
            val queryPart = qrText.substringAfter("?")
            val params = parseQueryParams(queryPart)

            val host = params["h"] ?: return null
            val port = params["p"]?.toIntOrNull() ?: return null
            val token = params["t"] ?: return null
            val version = params["v"]?.toIntOrNull() ?: return null
            if (version != 1) {
                return null
            }

            return PairingInfo(
                pairingId = "",
                host = host,
                port = port,
                token = token,
                expiresAt = System.currentTimeMillis() / 1000 + 300 // 5 min default
            )
        }

        /**
         * Parse a URL query string into a map of key-value pairs.
         */
        private fun parseQueryParams(query: String): Map<String, String> {
            val result = mutableMapOf<String, String>()
            for (pair in query.split("&")) {
                val parts = pair.split("=", limit = 2)
                if (parts.size == 2) {
                    result[parts[0]] = parts[1]
                }
            }
            return result
        }
    }

    /**
     * Generate the QR code text representation of this pairing info.
     * Format: icc://pair?h={host}&p={port}&t={token}&v=1
     *
     * @return QR code content string.
     */
    fun toQrText(): String {
        return "$QR_SCHEME?h=$host&p=$port&t=$token&v=1"
    }
}
