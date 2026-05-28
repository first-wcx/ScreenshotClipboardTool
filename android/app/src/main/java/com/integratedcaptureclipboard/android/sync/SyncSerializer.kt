package com.integratedcaptureclipboard.android.sync

import com.integratedcaptureclipboard.android.data.model.SyncMessage
import org.json.JSONObject
import java.nio.ByteBuffer
import java.time.Instant
import java.time.format.DateTimeFormatter

/**
 * Utility class for encoding and decoding sync messages using the binary frame protocol.
 *
 * Protocol format:
 * ┌──────────┬──────────┬───────────────┬────────────────────┐
 * │  Header  │  Header  │    Payload    │   Binary Payload   │
 * │  Length  │  JSON    │    JSON       │   (optional)        │
 * │  (2B)    │  (nB)    │   (variable)  │   (variable)       │
 * └──────────┴──────────┴───────────────┴────────────────────┘
 *
 * - Header Length: 2-byte big-endian unsigned integer (uint16)
 * - Header JSON: UTF-8 encoded JSON with fields: version, type, origin, timestamp, payload, binary_length
 * - Binary Payload: optional raw bytes (e.g. image data), length specified by binary_length
 */
object SyncSerializer {

    /** Maximum image size for base64 inline sync (1MB threshold). */
    private const val BINARY_THRESHOLD = 1 * 1024 * 1024

    /**
     * Encode a [SyncMessage] with an optional binary payload into a byte array
     * following the binary frame protocol.
     *
     * @param msg The sync message to encode.
     * @param binaryPayload Optional binary data (e.g. raw image bytes).
     * @return Encoded byte array ready to send over WebSocket.
     */
    fun encodeMessage(msg: SyncMessage, binaryPayload: ByteArray? = null): ByteArray {
        val headerJson = JSONObject(msg.toMap()).toString()
        val headerBytes = headerJson.toByteArray(Charsets.UTF_8)

        require(headerBytes.size <= 65535) {
            "Header JSON exceeds 65535 bytes (was ${headerBytes.size})"
        }

        val headerLength = headerBytes.size
        val totalSize = 2 + headerLength + (binaryPayload?.size ?: 0)
        val buffer = ByteBuffer.allocate(totalSize)

        // 2-byte header length (big-endian uint16)
        buffer.putShort(headerLength.toShort())

        // Header JSON bytes
        buffer.put(headerBytes)

        // Binary payload (if present)
        binaryPayload?.let { buffer.put(it) }

        return buffer.array()
    }

    /**
     * Decode a byte array received from WebSocket into a [SyncMessage] and
     * optional binary payload.
     *
     * @param data The raw byte array received from WebSocket.
     * @return A pair of (SyncMessage, binary payload or null).
     * @throws IllegalArgumentException If the data is too short or header is invalid.
     */
    fun decodeMessage(data: ByteArray): Pair<SyncMessage, ByteArray?> {
        require(data.size >= 2) { "Data too short: expected at least 2 bytes for header length" }

        val buffer = ByteBuffer.wrap(data)

        // Read 2-byte header length (big-endian uint16)
        val headerLength = buffer.short.toInt() and 0xFFFF

        require(data.size >= 2 + headerLength) {
            "Data too short: expected ${2 + headerLength} bytes, got ${data.size}"
        }

        // Read header JSON bytes
        val headerBytes = ByteArray(headerLength)
        buffer.get(headerBytes)

        // Parse header JSON
        val headerJson = JSONObject(String(headerBytes, Charsets.UTF_8))
        val payloadMap = mutableMapOf<String, Any>()

        val payloadObj = headerJson.optJSONObject("payload")
        if (payloadObj != null) {
            val keys = payloadObj.keys()
            while (keys.hasNext()) {
                val key = keys.next()
                payloadMap[key] = payloadObj.get(key)
            }
        }

        val msg = SyncMessage(
            version = headerJson.optInt("version", SyncMessage.VERSION),
            type = headerJson.optString("type", ""),
            origin = headerJson.optString("origin", ""),
            timestamp = headerJson.optString("timestamp", ""),
            payload = payloadMap,
            binaryLength = headerJson.optInt("binary_length", 0)
        )

        // Read binary payload (if indicated by binary_length)
        val binaryPayload: ByteArray? = if (msg.binaryLength > 0 && data.size >= 2 + headerLength + msg.binaryLength) {
            val binary = ByteArray(msg.binaryLength)
            buffer.get(binary)
            binary
        } else if (msg.binaryLength > 0) {
            // Binary payload is incomplete; return what we have
            val remaining = data.size - (2 + headerLength)
            if (remaining > 0) {
                val binary = ByteArray(remaining)
                buffer.get(binary)
                binary
            } else {
                null
            }
        } else {
            null
        }

        return Pair(msg, binaryPayload)
    }

    /**
     * Encode a clipboard item into a [SyncMessage], compatible with the
     * desktop app's serialize_item_for_sync format.
     *
     * For text items: produces a "clipboard_sync" message with text in payload.
     * For image items ≤ 1MB: produces a "clipboard_sync" message with base64 DIB in payload.
     * For image items > 1MB: produces a "clipboard_sync_binary" message with binary payload.
     *
     * @param type The item type ("text", "image", or "files").
     * @param item The item data as a map (compatible with desktop's serialize_item_for_sync output).
     * @param config Sync configuration (to check sync_text/sync_images flags).
     * @return A SyncMessage ready to be encoded and sent.
     */
    fun encodeClipboardItem(
        type: String,
        item: Map<String, Any>,
        config: SyncConfig
    ): SyncMessage {
        val now = DateTimeFormatter.ISO_INSTANT.format(Instant.now())

        when (type) {
            "text" -> {
                if (!config.syncText) {
                    return SyncMessage(
                        type = SyncMessage.MSG_TYPE_CLIPBOARD_SYNC,
                        origin = config.nodeId,
                        timestamp = now,
                        payload = emptyMap(),
                        binaryLength = 0
                    )
                }
                return SyncMessage(
                    type = SyncMessage.MSG_TYPE_CLIPBOARD_SYNC,
                    origin = config.nodeId,
                    timestamp = now,
                    payload = mapOf(
                        "item_type" to "text",
                        "item" to item
                    ),
                    binaryLength = 0
                )
            }
            "image" -> {
                if (!config.syncImages) {
                    return SyncMessage(
                        type = SyncMessage.MSG_TYPE_CLIPBOARD_SYNC,
                        origin = config.nodeId,
                        timestamp = now,
                        payload = emptyMap(),
                        binaryLength = 0
                    )
                }
                val size = (item["size"] as? Number)?.toInt() ?: 0
                if (size > BINARY_THRESHOLD && item.containsKey("raw_bytes")) {
                    // Large image: use binary frame
                    return SyncMessage(
                        type = SyncMessage.MSG_TYPE_CLIPBOARD_SYNC_BINARY,
                        origin = config.nodeId,
                        timestamp = now,
                        payload = mapOf(
                            "item_type" to "image",
                            "item" to item.filterKeys { it != "raw_bytes" }
                        ),
                        binaryLength = size
                    )
                }
                // Small image or base64 embedded
                return SyncMessage(
                    type = SyncMessage.MSG_TYPE_CLIPBOARD_SYNC,
                    origin = config.nodeId,
                    timestamp = now,
                    payload = mapOf(
                        "item_type" to "image",
                        "item" to item.filterKeys { it != "raw_bytes" }
                    ),
                    binaryLength = 0
                )
            }
            else -> {
                return SyncMessage(
                    type = SyncMessage.MSG_TYPE_CLIPBOARD_SYNC,
                    origin = config.nodeId,
                    timestamp = now,
                    payload = mapOf(
                        "item_type" to type,
                        "item" to item
                    ),
                    binaryLength = 0
                )
            }
        }
    }

    /**
     * Decode a received sync message back into a clipboard item type and data map,
     * compatible with the desktop app's deserialize_synced_item format.
     *
     * @param msg The received SyncMessage.
     * @return A pair of (item type string, item data map).
     */
    fun decodeClipboardItem(msg: SyncMessage): Pair<String, Map<String, Any>> {
        val itemType = msg.payload["item_type"] as? String ?: ""
        val itemData = msg.payload["item"] as? Map<String, Any> ?: emptyMap()
        return Pair(itemType, itemData)
    }
}

/**
 * Sync configuration data class used by [SyncSerializer.encodeClipboardItem].
 * This is a lightweight version of the full SyncConfig that will be
 * implemented in T03.
 *
 * @property enabled Whether sync is enabled.
 * @property nodeId This device's node ID.
 * @property syncText Whether to sync text clipboard items.
 * @property syncImages Whether to sync image clipboard items.
 * @property syncFiles Whether to sync file clipboard items.
 */
data class SyncConfig(
    val enabled: Boolean = false,
    val nodeId: String = "",
    val syncText: Boolean = true,
    val syncImages: Boolean = true,
    val syncFiles: Boolean = false
)
