package com.integratedcaptureclipboard.android.data.repository

import com.integratedcaptureclipboard.android.data.db.DeviceDao
import com.integratedcaptureclipboard.android.data.db.DeviceEntity
import com.integratedcaptureclipboard.android.data.model.DeviceInfo
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import java.time.Instant
import java.time.format.DateTimeFormatter
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for paired device data.
 * Encapsulates [DeviceDao] operations and provides a clean API
 * for the ViewModel layer, including conversion between
 * [DeviceEntity] and [DeviceInfo] models.
 */
@Singleton
class DeviceRepository @Inject constructor(
    private val deviceDao: DeviceDao
) {

    /**
     * Get all paired devices as a Flow of [DeviceInfo] list.
     * Devices are ordered by last seen time (most recent first).
     */
    fun getAllDevices(): Flow<List<DeviceInfo>> = flow {
        val entities = deviceDao.getAll()
        emit(entities.map { it.toDeviceInfo() })
    }

    /**
     * Get a specific device by its ID.
     *
     * @param deviceId The unique device identifier.
     * @return The [DeviceInfo] if found, null otherwise.
     */
    suspend fun getDevice(deviceId: String): DeviceInfo? {
        return deviceDao.getById(deviceId)?.toDeviceInfo()
    }

    /**
     * Add a new paired device. Converts [DeviceInfo] to [DeviceEntity] for storage.
     *
     * @param device The device info to add.
     */
    suspend fun addDevice(device: DeviceInfo, sharedSecret: String) {
        val entity = DeviceEntity(
            deviceId = device.deviceId,
            deviceName = device.deviceName,
            deviceType = device.deviceType,
            ipAddress = device.ipAddress,
            port = device.port,
            platform = device.platform,
            sharedSecret = sharedSecret,
            pairedAt = device.pairedAt,
            lastSeen = device.lastSeen
        )
        deviceDao.insert(entity)
    }

    /**
     * Remove a paired device by its ID.
     *
     * @param deviceId The ID of the device to remove.
     */
    suspend fun removeDevice(deviceId: String) {
        deviceDao.deleteById(deviceId)
    }

    /**
     * Update the last seen timestamp for a device.
     *
     * @param deviceId The device ID to update.
     */
    suspend fun updateLastSeen(deviceId: String) {
        val now = DateTimeFormatter.ISO_INSTANT.format(Instant.now())
        deviceDao.updateLastSeen(deviceId, now)
    }

    /**
     * Check if a device is paired (exists in the database).
     *
     * @param deviceId The device ID to check.
     * @return True if the device is paired.
     */
    suspend fun isPaired(deviceId: String): Boolean {
        return deviceDao.getById(deviceId) != null
    }

    /**
     * Get the shared secret for a paired device.
     *
     * @param deviceId The device ID.
     * @return The shared secret string, or null if device not found.
     */
    suspend fun getSharedSecret(deviceId: String): String? {
        return deviceDao.getById(deviceId)?.sharedSecret
    }

    /**
     * Count the total number of paired devices.
     */
    suspend fun getDeviceCount(): Int {
        return deviceDao.count()
    }

    /**
     * Convert a [DeviceEntity] to a [DeviceInfo] model.
     */
    private fun DeviceEntity.toDeviceInfo(): DeviceInfo {
        return DeviceInfo(
            deviceId = this.deviceId,
            deviceName = this.deviceName,
            deviceType = this.deviceType,
            ipAddress = this.ipAddress,
            port = this.port,
            platform = this.platform,
            pairedAt = this.pairedAt,
            lastSeen = this.lastSeen
        )
    }
}
