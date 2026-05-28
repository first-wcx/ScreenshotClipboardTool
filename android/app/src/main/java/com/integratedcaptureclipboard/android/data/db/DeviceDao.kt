package com.integratedcaptureclipboard.android.data.db

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/**
 * Data Access Object for [DeviceEntity].
 * Provides CRUD operations for paired device records.
 */
@Dao
interface DeviceDao {

    /**
     * Query all paired devices ordered by last seen time descending.
     */
    @Query("SELECT * FROM devices ORDER BY last_seen DESC")
    suspend fun getAll(): List<DeviceEntity>

    /**
     * Query a specific device by its device ID.
     *
     * @param deviceId The unique device identifier.
     * @return The matching device entity, or null if not found.
     */
    @Query("SELECT * FROM devices WHERE device_id = :deviceId LIMIT 1")
    suspend fun getById(deviceId: String): DeviceEntity?

    /**
     * Insert a device. If a conflict occurs on the primary key (device_id),
     * replace the existing entry.
     *
     * @param device The device entity to insert.
     * @return The row ID of the inserted device.
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(device: DeviceEntity): Long

    /**
     * Delete a specific device.
     *
     * @param device The device entity to delete.
     */
    @Delete
    suspend fun delete(device: DeviceEntity)

    /**
     * Delete a device by its ID.
     *
     * @param deviceId The ID of the device to delete.
     */
    @Query("DELETE FROM devices WHERE device_id = :deviceId")
    suspend fun deleteById(deviceId: String)

    /**
     * Update the last_seen timestamp for a device.
     *
     * @param deviceId The device ID to update.
     * @param lastSeen The new last_seen ISO 8601 timestamp.
     */
    @Query("UPDATE devices SET last_seen = :lastSeen WHERE device_id = :deviceId")
    suspend fun updateLastSeen(deviceId: String, lastSeen: String)

    /**
     * Count the total number of paired devices.
     */
    @Query("SELECT COUNT(*) FROM devices")
    suspend fun count(): Int
}
