package com.integratedcaptureclipboard.android.sync

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.IBinder
import android.util.Log
import androidx.core.app.NotificationCompat
import com.integratedcaptureclipboard.android.R
import com.integratedcaptureclipboard.android.sync.SyncManager
import com.integratedcaptureclipboard.android.sync.SyncConfig
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Foreground Service that keeps the WebSocket sync connections alive.
 *
 * On Android 10+, background network access is restricted, so a foreground
 * service with a persistent notification is required to maintain WebSocket
 * connections for real-time clipboard synchronization.
 *
 * Notification configuration:
 * - Channel ID: "sync_service"
 * - Notification ID: 2
 * - Foreground service type: dataSync (Android 14+)
 */
@AndroidEntryPoint
class SyncService : Service() {

    companion object {
        private const val TAG = "SyncService"
        const val CHANNEL_ID = "sync_service"
        const val NOTIFICATION_ID = 2

        /** Action to start the sync service. */
        const val ACTION_START = "com.integratedcaptureclipboard.android.action.SYNC_START"

        /** Action to stop the sync service. */
        const val ACTION_STOP = "com.integratedcaptureclipboard.android.action.SYNC_STOP"

        /** Extra key for sync configuration. */
        const val EXTRA_SYNC_ENABLED = "sync_enabled"
        const val EXTRA_SYNC_TEXT = "sync_text"
        const val EXTRA_SYNC_IMAGES = "sync_images"
        const val EXTRA_SYNC_FILES = "sync_files"

        /**
         * Start the sync service.
         *
         * @param context Application context.
         * @param config Sync configuration.
         */
        fun start(context: Context, config: SyncConfig) {
            val intent = Intent(context, SyncService::class.java).apply {
                action = ACTION_START
                putExtra(EXTRA_SYNC_ENABLED, config.enabled)
                putExtra(EXTRA_SYNC_TEXT, config.syncText)
                putExtra(EXTRA_SYNC_IMAGES, config.syncImages)
                putExtra(EXTRA_SYNC_FILES, config.syncFiles)
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        /**
         * Stop the sync service.
         *
         * @param context Application context.
         */
        fun stop(context: Context) {
            val intent = Intent(context, SyncService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }

    @Inject
    lateinit var syncManager: SyncManager

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        Log.d(TAG, "SyncService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val config = SyncConfig(
                    enabled = intent.getBooleanExtra(EXTRA_SYNC_ENABLED, false),
                    nodeId = syncManager.nodeId,
                    syncText = intent.getBooleanExtra(EXTRA_SYNC_TEXT, true),
                    syncImages = intent.getBooleanExtra(EXTRA_SYNC_IMAGES, true),
                    syncFiles = intent.getBooleanExtra(EXTRA_SYNC_FILES, false)
                )

                // Start as foreground service with notification
                val notification = buildNotification(
                    if (config.enabled) "Sync active" else "Sync idle"
                )
                startForeground(NOTIFICATION_ID, notification)

                if (config.enabled) {
                    syncManager.start(config)
                    Log.i(TAG, "Sync started with config: enabled=${config.enabled}")
                } else {
                    syncManager.stop()
                    Log.i(TAG, "Sync stopped")
                }

                // Update notification with connected device count
                updateNotification()
            }
            ACTION_STOP -> {
                syncManager.stop()
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                Log.i(TAG, "SyncService stopped")
            }
        }

        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null // Not bindable
    }

    override fun onDestroy() {
        syncManager.stop()
        super.onDestroy()
        Log.d(TAG, "SyncService destroyed")
    }

    /**
     * Create the notification channel for Android 8.0+.
     */
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "Sync Service",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "Keeps clipboard sync connections alive"
                setShowBadge(false)
                lockscreenVisibility = Notification.VISIBILITY_PRIVATE
            }

            val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            notificationManager.createNotificationChannel(channel)
        }
    }

    /**
     * Build the foreground service notification.
     *
     * @param statusText Status text to display in the notification.
     * @return The notification instance.
     */
    private fun buildNotification(statusText: String): Notification {
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("ICC Clipboard Sync")
            .setContentText(statusText)
            .setSmallIcon(R.drawable.ic_notification)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setShowWhen(false)
            .build()
    }

    /**
     * Update the notification to reflect the current connection state.
     */
    private fun updateNotification() {
        val connectedCount = syncManager.connectedDevices.value.size
        val statusText = if (connectedCount > 0) {
            "Connected to $connectedCount device${if (connectedCount != 1) "s" else ""}"
        } else {
            "Searching for devices..."
        }

        val notification = buildNotification(statusText)
        val notificationManager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        notificationManager.notify(NOTIFICATION_ID, notification)
    }
}
