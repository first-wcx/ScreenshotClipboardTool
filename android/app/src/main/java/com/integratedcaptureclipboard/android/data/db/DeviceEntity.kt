package com.integratedcaptureclipboard.android.data.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Room Entity representing a paired device.
 * Stores device information and shared secret for authenticated
 * WebSocket connections between devices.
 */
@Entity(tableName = "devices")
data class DeviceEntity(
    @PrimaryKey
    @ColumnInfo(name = "device_id")
    val deviceId: String,

    /** Human-readable device name (e.g. "Windows-Desktop", "Pixel 8 Pro"). */
    @ColumnInfo(name = "device_name")
    val deviceName: String,

    /** Device type: "android" or "desktop". */
    @ColumnInfo(name = "device_type")
    val deviceType: String,

    /** IP address of the device on the local network. */
    @ColumnInfo(name = "ip_address")
    val ipAddress: String,

    /** WebSocket port number. */
    @ColumnInfo(name = "port")
    val port: Int,

    /** Platform string (e.g. "android_14", "windows_11"). */
    @ColumnInfo(name = "platform")
    val platform: String,

    /** Shared secret for HMAC authentication (generated during pairing). */
    @ColumnInfo(name = "shared_secret")
    val sharedSecret: String,

    /** ISO 8601 timestamp when the device was paired. */
    @ColumnInfo(name = "paired_at")
    val pairedAt: String,

    /** ISO 8601 timestamp when the device was last seen online. */
    @ColumnInfo(name = "last_seen")
    val lastSeen: String
)
