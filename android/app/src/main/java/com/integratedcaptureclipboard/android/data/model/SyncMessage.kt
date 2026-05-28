package com.integratedcaptureclipboard.android.data.model

/**
 * Represents a sync message exchanged between devices via WebSocket.
 * Uses a binary frame protocol: 2-byte header length (big-endian uint16) +
 * header JSON bytes + optional binary payload.
 *
 * @property version Protocol version (currently 1).
 * @property type Message type string (e.g. "clipboard_sync", "ping").
 * @property origin Device ID of the message sender.
 * @property timestamp ISO 8601 UTC timestamp string.
 * @property payload Message payload as a map of key-value pairs.
 * @property binaryLength Length of the trailing binary payload in bytes (0 if none).
 */
data class SyncMessage(
    val version: Int = VERSION,
    val type: String,
    val origin: String,
    val timestamp: String,
    val payload: Map<String, Any> = emptyMap(),
    val binaryLength: Int = 0
) {
    companion object {
        /** Current protocol version. */
        const val VERSION = 1

        // Message type constants
        const val MSG_TYPE_HELLO = "hello"
        const val MSG_TYPE_AUTH_CHALLENGE = "auth_challenge"
        const val MSG_TYPE_AUTH_RESPONSE = "auth_response"
        const val MSG_TYPE_AUTH_OK = "auth_ok"
        const val MSG_TYPE_AUTH_FAIL = "auth_fail"
        const val MSG_TYPE_PAIRING_REQUEST = "pairing_request"
        const val MSG_TYPE_PAIRING_CONFIRM = "pairing_confirm"
        const val MSG_TYPE_CLIPBOARD_SYNC = "clipboard_sync"
        const val MSG_TYPE_CLIPBOARD_SYNC_BINARY = "clipboard_sync_binary"
        const val MSG_TYPE_FILE_STREAM_HEADER = "file_stream_header"
        const val MSG_TYPE_FILE_STREAM_DATA = "file_stream_data"
        const val MSG_TYPE_DEVICE_LIST = "device_list"
        const val MSG_TYPE_DEVICE_ONLINE = "device_online"
        const val MSG_TYPE_DEVICE_OFFLINE = "device_offline"
        const val MSG_TYPE_PING = "ping"
        const val MSG_TYPE_PONG = "pong"

        /**
         * Create a SyncMessage from a Map (typically parsed from JSON).
         */
        fun fromMap(map: Map<String, Any>): SyncMessage {
            return SyncMessage(
                version = (map["version"] as? Number)?.toInt() ?: VERSION,
                type = map["type"] as? String ?: "",
                origin = map["origin"] as? String ?: "",
                timestamp = map["timestamp"] as? String ?: "",
                payload = (map["payload"] as? Map<*, *>)
                    ?.mapNotNull { (key, value) ->
                        value?.let { key.toString() to it }
                    }
                    ?.toMap()
                    ?: emptyMap(),
                binaryLength = (map["binary_length"] as? Number)?.toInt() ?: 0
            )
        }
    }

    /**
     * Convert this SyncMessage to a Map suitable for JSON serialization.
     */
    fun toMap(): Map<String, Any> {
        return mapOf(
            "version" to version,
            "type" to type,
            "origin" to origin,
            "timestamp" to timestamp,
            "payload" to payload,
            "binary_length" to binaryLength
        )
    }
}
