package com.integratedcaptureclipboard.android.di

import android.content.Context
import androidx.room.Room
import com.integratedcaptureclipboard.android.data.db.AppDatabase
import com.integratedcaptureclipboard.android.data.db.ClipboardItemDao
import com.integratedcaptureclipboard.android.data.db.DeviceDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * DI module for Room database and DAO providers.
 * Ensures a single database instance and provides
 * DAOs for clipboard items and devices.
 */
@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {

    /**
     * Provide the Room [AppDatabase] instance.
     * Uses a singleton to avoid multiple database instances.
     */
    @Provides
    @Singleton
    fun provideAppDatabase(@ApplicationContext context: Context): AppDatabase {
        return Room.databaseBuilder(
            context,
            AppDatabase::class.java,
            "icc_database"
        )
            .fallbackToDestructiveMigration()
            .build()
    }

    /**
     * Provide the [ClipboardItemDao] from the [AppDatabase].
     */
    @Provides
    @Singleton
    fun provideClipboardItemDao(database: AppDatabase): ClipboardItemDao {
        return database.clipboardItemDao()
    }

    /**
     * Provide the [DeviceDao] from the [AppDatabase].
     */
    @Provides
    @Singleton
    fun provideDeviceDao(database: AppDatabase): DeviceDao {
        return database.deviceDao()
    }
}
