package com.integratedcaptureclipboard.android.data.db

import androidx.room.Database
import androidx.room.RoomDatabase

/**
 * Room database definition for the Integrated Capture Clipboard app.
 * Contains [ClipboardItemEntity] and [DeviceEntity] tables.
 */
@Database(
    entities = [
        ClipboardItemEntity::class,
        DeviceEntity::class
    ],
    version = 1,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {

    /**
     * Provides the DAO for clipboard history items.
     */
    abstract fun clipboardItemDao(): ClipboardItemDao

    /**
     * Provides the DAO for paired devices.
     */
    abstract fun deviceDao(): DeviceDao
}
