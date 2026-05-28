package com.integratedcaptureclipboard.android.data.model

/**
 * Represents information about a discovered or paired device.
 * Used in device discovery, pairing, and connection management.
 *
 * @property deviceId Unique device identifier (16-char hex string).
 * @property deviceName Human-readable device name (e.g. "Pixel 8 Pro").
 * @property deviceType Device type: "android" or "desktop".
 * @property ipAddress IP address of the device on the local network.
 * @property port WebSocket port number.
 * @property platform Platform string (e.g. "android_14", "windows_11").
 * @property pairedAt ISO 8601 timestamp when the device was paired.
 * @property lastSeen ISO 8601 timestamp when the device was last seen online.
 */
data class DeviceInfo(
    val deviceId: String,
    val deviceName: String,
    val deviceType: String,
    val ipAddress: String,
    val port: Int,
    val platform: String,
    val pairedAt: String,
    val lastSeen: String
)
