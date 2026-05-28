package com.integratedcaptureclipboard.android.sync

import android.util.Log
import com.integratedcaptureclipboard.android.data.model.SyncMessage
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * WebSocket client manager for the ICC multi-device sync system.
 *
 * Manages multiple WebSocket connections to different devices using OkHttp.
 * Each connection is identified by a device ID and supports:
 * - Binary frame protocol (consistent with Python ProtocolCodec)
 * - Automatic ping/pong heartbeat (handled by OkHttp)
 * - Connection state tracking
 * - Send and broadcast operations
 */
class WebSocketClient(
    private val okHttpClient: OkHttpClient
) {
    companion object {
        private const val TAG = "WebSocketClient"
        private const val CONNECT_TIMEOUT_SECONDS = 10L
        private const val READ_TIMEOUT_SECONDS = 0L // No read timeout for persistent connections
        private const val PING_INTERVAL_SECONDS = 30L
    }

    /** Active WebSocket connections keyed by device ID. */
    private val activeConnections = ConcurrentHashMap<String, WebSocket>()

    /** Connection state listeners keyed by device ID. */
    private val connectionListeners = ConcurrentHashMap<String, WebSocketConnectionListener>()

    /** Connection state tracker: device ID -> is connected. */
    private val connectionStates = ConcurrentHashMap<String, Boolean>()

    /**
     * Connect to a WebSocket server at the given URL.
     *
     * @param deviceId The device ID to associate with this connection.
     * @param url The WebSocket URL (e.g. "ws://192.168.1.100:8765").
     * @param listener Callback for connection events and received messages.
     * @return The created WebSocket instance.
     */
    fun connect(deviceId: String, url: String, listener: WebSocketConnectionListener): WebSocket {
        // Close existing connection if any
        disconnect(deviceId)

        connectionListeners[deviceId] = listener

        val request = Request.Builder()
            .url(url)
            .build()

        val wsListener = object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: okhttp3.Response) {
                Log.d(TAG, "WebSocket opened for device: $deviceId")
                activeConnections[deviceId] = webSocket
                connectionStates[deviceId] = true
                listener.onConnected(deviceId)
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                // We use binary frames exclusively; text messages are unexpected
                Log.w(TAG, "Received unexpected text message from device: $deviceId")
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                try {
                    val (msg, binaryPayload) = SyncSerializer.decodeMessage(bytes.toByteArray())
                    listener.onMessage(deviceId, msg, binaryPayload)
                } catch (e: Exception) {
                    Log.e(TAG, "Failed to decode message from device: $deviceId", e)
                }
            }

            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closing for device: $deviceId, code: $code, reason: $reason")
                webSocket.close(1000, "Normal closure")
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                Log.d(TAG, "WebSocket closed for device: $deviceId, code: $code")
                activeConnections.remove(deviceId)
                connectionStates[deviceId] = false
                listener.onDisconnected(deviceId, code, reason)
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: okhttp3.Response?) {
                Log.e(TAG, "WebSocket failure for device: $deviceId", t)
                activeConnections.remove(deviceId)
                connectionStates[deviceId] = false
                listener.onError(deviceId, t)
            }

        }

        val client = okHttpClient.newBuilder()
            .connectTimeout(CONNECT_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .readTimeout(READ_TIMEOUT_SECONDS, TimeUnit.SECONDS)
            .pingInterval(PING_INTERVAL_SECONDS, TimeUnit.SECONDS)
            .build()

        val ws = client.newWebSocket(request, wsListener)
        activeConnections[deviceId] = ws
        return ws
    }

    /**
     * Disconnect from a specific device.
     *
     * @param deviceId The device ID to disconnect from.
     */
    fun disconnect(deviceId: String) {
        val ws = activeConnections.remove(deviceId)
        if (ws != null) {
            ws.close(1000, "Client disconnecting")
            connectionStates[deviceId] = false
        }
        connectionListeners.remove(deviceId)
    }

    /**
     * Disconnect all active connections.
     */
    fun disconnectAll() {
        val deviceIds = activeConnections.keys.toList()
        for (deviceId in deviceIds) {
            disconnect(deviceId)
        }
    }

    /**
     * Send a SyncMessage (with optional binary payload) to a specific device.
     *
     * @param deviceId The target device ID.
     * @param msg The sync message to send.
     * @param binaryPayload Optional binary payload (e.g. image data).
     * @return True if the message was queued successfully.
     */
    fun send(deviceId: String, msg: SyncMessage, binaryPayload: ByteArray? = null): Boolean {
        val ws = activeConnections[deviceId]
        if (ws == null) {
            Log.w(TAG, "Cannot send to device $deviceId: not connected")
            return false
        }

        return try {
            val encoded = SyncSerializer.encodeMessage(msg, binaryPayload)
            ws.send(encoded.toByteString())
        } catch (e: Exception) {
            Log.e(TAG, "Failed to send message to device: $deviceId", e)
            false
        }
    }

    /**
     * Broadcast a SyncMessage to all connected devices, optionally excluding some.
     *
     * @param msg The sync message to broadcast.
     * @param binaryPayload Optional binary payload.
     * @param exclude Device IDs to exclude from the broadcast.
     */
    fun broadcast(msg: SyncMessage, binaryPayload: ByteArray? = null, exclude: Set<String> = emptySet()) {
        val encoded = try {
            SyncSerializer.encodeMessage(msg, binaryPayload)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to encode broadcast message", e)
            return
        }

        val byteString = encoded.toByteString()
        for ((deviceId, ws) in activeConnections) {
            if (deviceId in exclude) continue
            try {
                ws.send(byteString)
            } catch (e: Exception) {
                Log.e(TAG, "Failed to broadcast to device: $deviceId", e)
            }
        }
    }

    /**
     * Check if a device is currently connected.
     *
     * @param deviceId The device ID to check.
     * @return True if connected.
     */
    fun isConnected(deviceId: String): Boolean {
        return connectionStates[deviceId] == true
    }

    /**
     * Get the list of currently connected device IDs.
     *
     * @return Set of connected device IDs.
     */
    fun getConnectedDeviceIds(): Set<String> {
        return activeConnections.keys.filter { connectionStates[it] == true }.toSet()
    }

    /**
     * Callback interface for WebSocket connection events.
     */
    interface WebSocketConnectionListener {
        /**
         * Called when the WebSocket connection is established.
         *
         * @param deviceId The connected device's ID.
         */
        fun onConnected(deviceId: String)

        /**
         * Called when a binary message is received and decoded.
         *
         * @param deviceId The sender device's ID.
         * @param message The decoded SyncMessage.
         * @param binaryPayload Optional binary payload.
         */
        fun onMessage(deviceId: String, message: SyncMessage, binaryPayload: ByteArray?)

        /**
         * Called when the WebSocket connection is closed.
         *
         * @param deviceId The disconnected device's ID.
         * @param code The WebSocket close code.
         * @param reason The close reason string.
         */
        fun onDisconnected(deviceId: String, code: Int, reason: String)

        /**
         * Called when a WebSocket error occurs.
         *
         * @param deviceId The device ID with the error.
         * @param error The throwable error.
         */
        fun onError(deviceId: String, error: Throwable)
    }
}
