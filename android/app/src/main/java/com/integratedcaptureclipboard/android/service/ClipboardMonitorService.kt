package com.integratedcaptureclipboard.android.service

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
import com.integratedcaptureclipboard.android.clipboard.ClipboardHelper
import com.integratedcaptureclipboard.android.clipboard.ClipboardMonitor
import com.integratedcaptureclipboard.android.data.repository.ClipboardRepository
import com.integratedcaptureclipboard.android.sync.SyncManager
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject

/**
 * Foreground Service for monitoring the system clipboard.
 *
 * On Android 10+, background apps cannot receive clipboard change
 * notifications. This foreground service maintains a persistent
 * notification and registers [android.content.ClipboardManager.OnPrimaryClipChangedListener]
 * to detect clipboard changes.
 *
 * Notification configuration:
 * - Channel ID: "clipboard_monitor"
 * - Notification ID: 1
 * - Foreground service type: specialUse (Android 14+)
 */
@AndroidEntryPoint
class ClipboardMonitorService : Service() {

    companion object {
        private const val TAG = "ClipboardMonitorService"
        const val CHANNEL_ID = "clipboard_monitor"
        const val NOTIFICATION_ID = 1

        /** Action to start the clipboard monitor service. */
        const val ACTION_START = "com.integratedcaptureclipboard.android.action.CLIPBOARD_MONITOR_START"

        /** Action to stop the clipboard monitor service. */
        const val ACTION_STOP = "com.integratedcaptureclipboard.android.action.CLIPBOARD_MONITOR_STOP"

        /**
         * Start the clipboard monitor service.
         *
         * @param context Application context.
         */
        fun start(context: Context) {
            val intent = Intent(context, ClipboardMonitorService::class.java).apply {
                action = ACTION_START
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        /**
         * Stop the clipboard monitor service.
         *
         * @param context Application context.
         */
        fun stop(context: Context) {
            val intent = Intent(context, ClipboardMonitorService::class.java).apply {
                action = ACTION_STOP
            }
            context.startService(intent)
        }
    }

    @Inject
    lateinit var syncManager: SyncManager

    @Inject
    lateinit var clipboardRepository: ClipboardRepository

    private var clipboardMonitor: ClipboardMonitor? = null

    override fun onCreate() {
        super.onCreate()
        createNotificationChannel()
        Log.d(TAG, "ClipboardMonitorService created")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_START -> {
                val notification = buildNotification("正在监听剪贴板变化")
                startForeground(NOTIFICATION_ID, notification)

                // Initialize and start clipboard monitoring
                val clipboardHelper = ClipboardHelper(this)
                clipboardMonitor = ClipboardMonitor(
                    context = this,
                    clipboardRepository = clipboardRepository,
                    clipboardHelper = clipboardHelper,
                    syncManager = syncManager
                )

                // Set up sync listener to receive items from other devices
                syncManager.setOnClipboardSyncListener(object : SyncManager.OnClipboardSyncListener {
                    override fun onClipboardItemReceived(itemType: String, itemData: Map<String, Any>) {
                        clipboardMonitor?.onSyncedClipboardItemReceived(itemType, itemData)
                    }
                })

                clipboardMonitor?.startMonitoring()
                Log.i(TAG, "Clipboard monitoring started")
            }
            ACTION_STOP -> {
                clipboardMonitor?.stopMonitoring()
                clipboardMonitor = null
                stopForeground(STOP_FOREGROUND_REMOVE)
                stopSelf()
                Log.i(TAG, "ClipboardMonitorService stopped")
            }
        }

        return START_STICKY
    }

    override fun onBind(intent: Intent?): IBinder? {
        return null // Not bindable
    }

    override fun onDestroy() {
        clipboardMonitor?.stopMonitoring()
        clipboardMonitor = null
        super.onDestroy()
        Log.d(TAG, "ClipboardMonitorService destroyed")
    }

    /**
     * Create the notification channel for Android 8.0+.
     */
    private fun createNotificationChannel() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                CHANNEL_ID,
                "剪贴板监听",
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = "监听剪贴板变化并同步到其他设备"
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
            .setContentTitle("ICC 剪贴板监听")
            .setContentText(statusText)
            .setSmallIcon(R.drawable.ic_notification)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setOngoing(true)
            .setShowWhen(false)
            .build()
    }
}
