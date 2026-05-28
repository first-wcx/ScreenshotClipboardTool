package com.integratedcaptureclipboard.android.sync

import android.util.Log
import com.integratedcaptureclipboard.android.data.model.DeviceInfo
import com.integratedcaptureclipboard.android.data.model.PairingInfo
import com.integratedcaptureclipboard.android.data.model.SyncMessage
import com.integratedcaptureclipboard.android.data.repository.ClipboardRepository
import com.integratedcaptureclipboard.android.data.repository.DeviceRepository
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.time.Instant
import java.time.format.DateTimeFormatter
import java.util.UUID
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Core sync manager for the Android ICC multi-device sync system.
 *
 * Manages WebSocket connections, authentication handshakes, device pairing,
 * and clipboard content synchronization across multiple devices.
 *
 * The SyncManager is the central coordinator that:
 * - Manages multiple WebSocket connections via [WebSocketClient]
 * - Performs HMAC-SHA256 authentication handshakes
 * - Handles pairing requests via QR code scanning
 * - Publishes local clipboard changes to connected devices
 * - Processes incoming clipboard sync messages (with digest deduplication)
 * - Manages device discovery via [NsdDiscovery]
 */
@Singleton
class SyncManager @Inject constructor(
    private val wsClient: WebSocketClient,
    private val deviceRepository: DeviceRepository,
    private val clipboardRepository: ClipboardRepository,
    private val nsdDiscovery: NsdDiscovery
) : WebSocketClient.WebSocketConnectionListener {

    companion object {
        private const val TAG = "SyncManager"
        private const val RECONNECT_DELAY_MS = 5000L
        private const val MAX_RECONNECT_ATTEMPTS = 10
        private const val AUTH_TIMEOUT_MS = 15000L
    }

    /** This device's unique node ID, generated once and persisted. */
    val nodeId: String = UUID.randomUUID().toString().replace("-", "").take(16)

    /** Current sync configuration. */
    private var syncConfig: SyncConfig = SyncConfig(nodeId = nodeId)

    /** Coroutine scope for async operations. */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** Reconnect jobs keyed by device ID. */
    private val reconnectJobs = ConcurrentHashMap<String, Job>()

    /** Authentication state tracker: device ID -> is authenticated. */
    private val authStates = ConcurrentHashMap<String, Boolean>()

    /** Pending pairing requests awaiting user confirmation. */
    private val pendingPairings = ConcurrentHashMap<String, PairingRequest>()

    /** Observable state: list of connected device IDs. */
    private val _connectedDevices = MutableStateFlow<List<DeviceInfo>>(emptyList())
    val connectedDevices: StateFlow<List<DeviceInfo>> = _connectedDevices

    /** Observable state: discovered devices via mDNS. */
    private val _discoveredDevices = MutableStateFlow<List<NsdDiscovery.DiscoveredDevice>>(emptyList())
    val discoveredDevices: StateFlow<List<NsdDiscovery.DiscoveredDevice>> = _discoveredDevices

    /** Listener for incoming clipboard sync events. */
    private var onClipboardSyncListener: OnClipboardSyncListener? = null

    /** Listener for pairing confirmation requests. */
    private var onPairingRequestListener: OnPairingRequestListener? = null

    /** Whether the sync manager is currently active. */
    @Volatile
    private var isActive = false

    /**
     * Start the sync manager: begin device discovery and attempt to reconnect
     * to previously paired devices.
     *
     * @param config Sync configuration.
     */
    fun start(config: SyncConfig) {
        if (isActive) {
            Log.d(TAG, "SyncManager already active")
            return
        }

        syncConfig = config.copy(nodeId = nodeId)
        isActive = true
        Log.i(TAG, "SyncManager starting with nodeId: $nodeId")

        // Set up WebSocket connection listener
        // (wsClient will delegate to this class)

        // Start mDNS discovery
        nsdDiscovery.setOnDeviceFoundListener(object : NsdDiscovery.OnDeviceFoundListener {
            override fun onDeviceFound(device: NsdDiscovery.DiscoveredDevice) {
                Log.d(TAG, "Device discovered: ${device.deviceName} at ${device.host}:${device.port}")
                val current = _discoveredDevices.value.toMutableList()
                // Avoid duplicates
                if (current.none { it.host == device.host && it.port == device.port }) {
                    current.add(device)
                    _discoveredDevices.value = current
                }
            }

            override fun onDeviceLost(serviceName: String) {
                Log.d(TAG, "Device lost: $serviceName")
                val current = _discoveredDevices.value.toMutableList()
                _discoveredDevices.value = current.filter { it.serviceName != serviceName }
            }
        })

        if (syncConfig.enabled) {
            nsdDiscovery.startDiscovery()
            reconnectToPairedDevices()
        }
    }

    /**
     * Stop the sync manager: disconnect all connections and stop discovery.
     */
    fun stop() {
        if (!isActive) return

        Log.i(TAG, "SyncManager stopping")
        isActive = false

        // Cancel all reconnect jobs
        reconnectJobs.values.forEach { it.cancel() }
        reconnectJobs.clear()

        // Stop discovery
        nsdDiscovery.stopDiscovery()

        // Disconnect all WebSocket connections
        wsClient.disconnectAll()

        // Clear state
        authStates.clear()
        pendingPairings.clear()
        _connectedDevices.value = emptyList()
        _discoveredDevices.value = emptyList()
    }

    /**
     * Update the sync configuration.
     *
     * @param config New sync configuration.
     */
    fun updateConfig(config: SyncConfig) {
        val wasEnabled = syncConfig.enabled
        syncConfig = config.copy(nodeId = nodeId)

        if (config.enabled && !wasEnabled) {
            nsdDiscovery.startDiscovery()
            reconnectToPairedDevices()
        } else if (!config.enabled && wasEnabled) {
            nsdDiscovery.stopDiscovery()
            wsClient.disconnectAll()
        }
    }

    /**
     * Connect to a specific device via WebSocket.
     *
     * @param device The device info to connect to.
     */
    fun connectToDevice(device: DeviceInfo) {
        if (!syncConfig.enabled) return

        val url = "ws://${device.ipAddress}:${device.port}"
        Log.i(TAG, "Connecting to device: ${device.deviceName} at $url")
        wsClient.connect(device.deviceId, url, this)
    }

    /**
     * Connect to a device discovered via mDNS.
     *
     * @param discoveredDevice The discovered device info.
     */
    fun connectToDiscoveredDevice(discoveredDevice: NsdDiscovery.DiscoveredDevice) {
        val device = DeviceInfo(
            deviceId = discoveredDevice.deviceId,
            deviceName = discoveredDevice.deviceName,
            deviceType = discoveredDevice.deviceType,
            ipAddress = discoveredDevice.host,
            port = discoveredDevice.port,
            platform = discoveredDevice.platform,
            pairedAt = "",
            lastSeen = DateTimeFormatter.ISO_INSTANT.format(Instant.now())
        )
        connectToDevice(device)
    }

    /**
     * Initiate pairing via QR code scan.
     *
     * After scanning the QR code, connects to the pairing server and
     * sends a pairing_request message.
     *
     * @param pairingInfo Parsed from the QR code content.
     */
    fun initiatePairing(pairingInfo: PairingInfo) {
        val url = "ws://${pairingInfo.host}:${pairingInfo.port}"
        val tempDeviceId = "pairing_${pairingInfo.host}_${pairingInfo.port}"

        Log.i(TAG, "Initiating pairing to ${pairingInfo.host}:${pairingInfo.port}")

        wsClient.connect(tempDeviceId, url, object : WebSocketClient.WebSocketConnectionListener {
            override fun onConnected(deviceId: String) {
                Log.d(TAG, "Pairing connection established")
                // Send pairing_request
                val pairingMsg = SyncMessage(
                    type = SyncMessage.MSG_TYPE_PAIRING_REQUEST,
                    origin = nodeId,
                    timestamp = DateTimeFormatter.ISO_INSTANT.format(Instant.now()),
                    payload = mapOf(
                        "token" to pairingInfo.token,
                        "device_name" to android.os.Build.MODEL,
                        "device_type" to "android",
                        "platform" to "android_${android.os.Build.VERSION.SDK_INT}"
                    ),
                    binaryLength = 0
                )
                wsClient.send(deviceId, pairingMsg)
            }

            override fun onMessage(deviceId: String, message: SyncMessage, binaryPayload: ByteArray?) {
                handlePairingMessage(deviceId, message, pairingInfo)
            }

            override fun onDisconnected(deviceId: String, code: Int, reason: String) {
                Log.d(TAG, "Pairing connection closed: $code $reason")
            }

            override fun onError(deviceId: String, error: Throwable) {
                Log.e(TAG, "Pairing connection error", error)
            }
        })
    }

    /**
     * Disconnect from a specific device.
     *
     * @param deviceId The device ID to disconnect from.
     */
    fun disconnectDevice(deviceId: String) {
        reconnectJobs[deviceId]?.cancel()
        reconnectJobs.remove(deviceId)
        wsClient.disconnect(deviceId)
        authStates.remove(deviceId)
        updateConnectedDevicesList()
    }

    /**
     * Publish a local clipboard item to all connected devices.
     *
     * @param itemType The item type ("text", "image", or "files").
     * @param itemData The item data map (compatible with serialize_item_for_sync format).
     * @param rawBytes Optional raw bytes for large images (for binary frame protocol).
     */
    fun publishClipboardItem(itemType: String, itemData: Map<String, Any>, rawBytes: ByteArray? = null) {
        if (!syncConfig.enabled) return

        val msg = SyncSerializer.encodeClipboardItem(itemType, itemData, syncConfig)
        val binaryPayload = if (msg.type == SyncMessage.MSG_TYPE_CLIPBOARD_SYNC_BINARY && rawBytes != null) {
            rawBytes
        } else {
            null
        }

        wsClient.broadcast(msg, binaryPayload, exclude = setOf())
    }

    /**
     * Set the listener for incoming clipboard sync events.
     */
    fun setOnClipboardSyncListener(listener: OnClipboardSyncListener) {
        onClipboardSyncListener = listener
    }

    /**
     * Set the listener for pairing confirmation requests.
     */
    fun setOnPairingRequestListener(listener: OnPairingRequestListener) {
        onPairingRequestListener = listener
    }

    // ------------------------------------------------------------------
    // WebSocketConnectionListener implementation
    // ------------------------------------------------------------------

    override fun onConnected(deviceId: String) {
        Log.d(TAG, "Device connected: $deviceId")
        // Start authentication handshake (client side)
        // The server will send auth_challenge; we wait for it.
    }

    override fun onMessage(deviceId: String, message: SyncMessage, binaryPayload: ByteArray?) {
        when (message.type) {
            SyncMessage.MSG_TYPE_AUTH_CHALLENGE -> handleAuthChallenge(deviceId, message)
            SyncMessage.MSG_TYPE_AUTH_OK -> handleAuthOk(deviceId, message)
            SyncMessage.MSG_TYPE_AUTH_FAIL -> handleAuthFail(deviceId)
            SyncMessage.MSG_TYPE_PAIRING_CONFIRM -> handlePairingConfirm(deviceId, message)
            SyncMessage.MSG_TYPE_CLIPBOARD_SYNC -> handleClipboardSync(deviceId, message)
            SyncMessage.MSG_TYPE_CLIPBOARD_SYNC_BINARY -> handleClipboardSyncBinary(deviceId, message, binaryPayload)
            SyncMessage.MSG_TYPE_DEVICE_ONLINE -> handleDeviceOnline(message)
            SyncMessage.MSG_TYPE_DEVICE_OFFLINE -> handleDeviceOffline(message)
            SyncMessage.MSG_TYPE_PONG -> { /* heartbeat response, no action needed */ }
            else -> Log.d(TAG, "Unhandled message type: ${message.type}")
        }
    }

    override fun onDisconnected(deviceId: String, code: Int, reason: String) {
        Log.d(TAG, "Device disconnected: $deviceId, code: $code")
        authStates.remove(deviceId)
        updateConnectedDevicesList()

        // Schedule reconnect if sync is active and device is paired
        if (isActive && syncConfig.enabled) {
            scheduleReconnect(deviceId)
        }
    }

    override fun onError(deviceId: String, error: Throwable) {
        Log.e(TAG, "Device error: $deviceId", error)
        authStates.remove(deviceId)
        updateConnectedDevicesList()

        if (isActive && syncConfig.enabled) {
            scheduleReconnect(deviceId)
        }
    }

    // ------------------------------------------------------------------
    // Authentication handlers
    // ------------------------------------------------------------------

    /**
     * Handle an auth_challenge from the server by computing HMAC and sending auth_response.
     */
    private fun handleAuthChallenge(deviceId: String, message: SyncMessage) {
        val nonce = message.payload["nonce"] as? String ?: return
        val secret = runBlocking { deviceRepository.getSharedSecret(deviceId) }
        if (secret.isNullOrEmpty()) {
            Log.w(TAG, "No shared secret for device: $deviceId, cannot authenticate")
            return
        }

        val hmac = DeviceAuthenticator.computeHmac(secret, nonce)
        val responseMsg = SyncMessage(
            type = SyncMessage.MSG_TYPE_AUTH_RESPONSE,
            origin = nodeId,
            timestamp = DateTimeFormatter.ISO_INSTANT.format(Instant.now()),
            payload = mapOf("hmac" to hmac),
            binaryLength = 0
        )
        wsClient.send(deviceId, responseMsg)
        Log.d(TAG, "Auth response sent for device: $deviceId")
    }

    /**
     * Handle auth_ok — authentication succeeded.
     */
    private fun handleAuthOk(deviceId: String, message: SyncMessage) {
        Log.i(TAG, "Authentication succeeded for device: $deviceId")
        authStates[deviceId] = true

        // Cancel any pending reconnect
        reconnectJobs[deviceId]?.cancel()
        reconnectJobs.remove(deviceId)

        // Send hello with device info
        val helloMsg = SyncMessage(
            type = SyncMessage.MSG_TYPE_HELLO,
            origin = nodeId,
            timestamp = DateTimeFormatter.ISO_INSTANT.format(Instant.now()),
            payload = mapOf(
                "device_name" to android.os.Build.MODEL,
                "device_type" to "android",
                "platform" to "android_${android.os.Build.VERSION.SDK_INT}"
            ),
            binaryLength = 0
        )
        wsClient.send(deviceId, helloMsg)

        // Update last seen
        scope.launch {
            deviceRepository.updateLastSeen(deviceId)
        }

        updateConnectedDevicesList()
    }

    /**
     * Handle auth_fail — authentication failed.
     */
    private fun handleAuthFail(deviceId: String) {
        Log.w(TAG, "Authentication failed for device: $deviceId")
        authStates[deviceId] = false
        wsClient.disconnect(deviceId)
    }

    // ------------------------------------------------------------------
    // Pairing handlers
    // ------------------------------------------------------------------

    /**
     * Handle a pairing_confirm message from the desktop.
     * Stores the shared secret and device info.
     */
    private fun handlePairingConfirm(deviceId: String, message: SyncMessage) {
        val sharedSecret = message.payload["shared_secret"] as? String ?: return
        val deviceName = message.payload["device_name"] as? String ?: "Unknown Desktop"
        val deviceType = message.payload["device_type"] as? String ?: "desktop"
        val platform = message.payload["platform"] as? String ?: ""

        Log.i(TAG, "Pairing confirmed with device: $deviceName")

        val deviceInfo = DeviceInfo(
            deviceId = message.origin,
            deviceName = deviceName,
            deviceType = deviceType,
            ipAddress = "",  // Will be updated on next connection
            port = 8765,
            platform = platform,
            pairedAt = DateTimeFormatter.ISO_INSTANT.format(Instant.now()),
            lastSeen = DateTimeFormatter.ISO_INSTANT.format(Instant.now())
        )

        scope.launch {
            deviceRepository.addDevice(deviceInfo, sharedSecret)
        }

        // Close the temporary pairing connection
        wsClient.disconnect(deviceId)

        onPairingRequestListener?.onPairingConfirmed(deviceInfo)
    }

    /**
     * Handle pairing messages during the QR pairing flow.
     */
    private fun handlePairingMessage(deviceId: String, message: SyncMessage, pairingInfo: PairingInfo) {
        when (message.type) {
            SyncMessage.MSG_TYPE_AUTH_CHALLENGE -> handleAuthChallenge(deviceId, message)
            SyncMessage.MSG_TYPE_PAIRING_CONFIRM -> handlePairingConfirm(deviceId, message)
            SyncMessage.MSG_TYPE_AUTH_FAIL -> {
                Log.w(TAG, "Pairing authentication failed")
                wsClient.disconnect(deviceId)
            }
            else -> Log.d(TAG, "Unexpected pairing message type: ${message.type}")
        }
    }

    // ------------------------------------------------------------------
    // Clipboard sync handlers
    // ------------------------------------------------------------------

    /**
     * Handle a clipboard_sync message (text or small image with base64).
     */
    private fun handleClipboardSync(deviceId: String, message: SyncMessage) {
        if (message.origin == nodeId) return // Skip own messages

        val (itemType, itemData) = SyncSerializer.decodeClipboardItem(message)
        if (itemType.isEmpty()) return

        // Deduplication check
        val digest = itemData["digest"] as? String ?: ""
        if (digest.isNotEmpty()) {
            val existing = runBlocking { clipboardRepository.getItemByDigest(digest) }
            if (existing != null) {
                Log.d(TAG, "Skipping duplicate clipboard item: $digest")
                return
            }
        }

        onClipboardSyncListener?.onClipboardItemReceived(itemType, itemData)
    }

    /**
     * Handle a clipboard_sync_binary message (large image with binary payload).
     */
    private fun handleClipboardSyncBinary(deviceId: String, message: SyncMessage, binaryPayload: ByteArray?) {
        if (message.origin == nodeId) return

        if (binaryPayload == null) {
            Log.w(TAG, "clipboard_sync_binary without binary payload from: $deviceId")
            return
        }

        val (itemType, itemData) = SyncSerializer.decodeClipboardItem(message)
        if (itemType != "image") return

        // Reconstruct base64 DIB for compatibility with desktop format
        val dibB64 = android.util.Base64.encodeToString(binaryPayload, android.util.Base64.NO_WRAP)
        val reconstructedData = itemData.toMutableMap()
        reconstructedData["dib_b64"] = dibB64
        reconstructedData["size"] = binaryPayload.size

        // Deduplication check
        val digest = reconstructedData["digest"] as? String ?: ""
        if (digest.isNotEmpty()) {
            val existing = runBlocking { clipboardRepository.getItemByDigest(digest) }
            if (existing != null) return
        }

        onClipboardSyncListener?.onClipboardItemReceived(itemType, reconstructedData)
    }

    /**
     * Handle a device_online notification.
     */
    private fun handleDeviceOnline(message: SyncMessage) {
        val deviceInfo = message.payload
        Log.d(TAG, "Device online: ${deviceInfo["device_name"]}")
    }

    /**
     * Handle a device_offline notification.
     */
    private fun handleDeviceOffline(message: SyncMessage) {
        val offlineDeviceId = message.payload["device_id"] as? String ?: return
        Log.d(TAG, "Device offline: $offlineDeviceId")
        authStates.remove(offlineDeviceId)
        updateConnectedDevicesList()
    }

    // ------------------------------------------------------------------
    // Reconnection logic
    // ------------------------------------------------------------------

    /**
     * Attempt to reconnect to all previously paired devices.
     */
    private fun reconnectToPairedDevices() {
        scope.launch {
            val devices = deviceRepository.getAllDevices()
            // Collect first emission
            val deviceList = mutableListOf<DeviceInfo>()
            devices.collect { deviceList.addAll(it) }

            for (device in deviceList) {
                if (device.ipAddress.isNotEmpty()) {
                    connectToDevice(device)
                }
            }
        }
    }

    /**
     * Schedule a reconnect attempt for a specific device with exponential backoff.
     */
    private fun scheduleReconnect(deviceId: String) {
        if (reconnectJobs.containsKey(deviceId)) return

        reconnectJobs[deviceId] = scope.launch {
            for (attempt in 1..MAX_RECONNECT_ATTEMPTS) {
                if (!isActive) break

                val delayMs = RECONNECT_DELAY_MS * (1L shl (attempt - 1).coerceAtMost(4))
                Log.d(TAG, "Reconnect attempt $attempt for device $deviceId in ${delayMs}ms")
                delay(delayMs)

                if (!isActive) break

                val device = deviceRepository.getDevice(deviceId) ?: break
                if (device.ipAddress.isNotEmpty()) {
                    connectToDevice(device)
                    break // onConnected or onError will handle subsequent attempts
                }
            }
        }
    }

    /**
     * Update the observable connected devices list.
     */
    private fun updateConnectedDevicesList() {
        scope.launch {
            val allDevices = mutableListOf<DeviceInfo>()
            deviceRepository.getAllDevices().collect { list ->
                allDevices.clear()
                allDevices.addAll(list)
            }
            val connected = allDevices.filter { authStates[it.deviceId] == true }
            _connectedDevices.value = connected
        }
    }

    // ------------------------------------------------------------------
    // Listener interfaces
    // ------------------------------------------------------------------

    /**
     * Listener for incoming clipboard sync events.
     */
    interface OnClipboardSyncListener {
        /**
         * Called when a clipboard item is received from a remote device.
         *
         * @param itemType The item type ("text", "image").
         * @param itemData The item data map (compatible with deserialize_synced_item format).
         */
        fun onClipboardItemReceived(itemType: String, itemData: Map<String, Any>)
    }

    /**
     * Listener for pairing confirmation events.
     */
    interface OnPairingRequestListener {
        /**
         * Called when a pairing is confirmed by the remote device.
         *
         * @param deviceInfo Information about the paired device.
         */
        fun onPairingConfirmed(deviceInfo: DeviceInfo)
    }

    /**
     * Represents a pending pairing request.
     */
    data class PairingRequest(
        val deviceId: String,
        val deviceName: String,
        val deviceType: String,
        val platform: String,
        val token: String,
        val timestamp: Long = System.currentTimeMillis()
    )
}
