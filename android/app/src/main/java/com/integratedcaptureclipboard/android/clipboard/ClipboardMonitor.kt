package com.integratedcaptureclipboard.android.clipboard

import android.content.ClipboardManager
import android.content.Context
import android.util.Base64
import android.util.Log
import com.integratedcaptureclipboard.android.data.db.ClipboardItemEntity
import com.integratedcaptureclipboard.android.data.repository.ClipboardRepository
import com.integratedcaptureclipboard.android.sync.SyncManager
import com.integratedcaptureclipboard.android.sync.SyncConfig
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.format.DateTimeFormatter
import java.time.ZoneId
import java.time.format.DateTimeFormatter as JavaDateTimeFormatter

/**
 * Monitors the Android system clipboard for changes and persists new items
 * to the local database, optionally syncing them to connected devices.
 *
 * On Android 10+, clipboard monitoring requires a foreground service.
 * This class uses [ClipboardManager.OnPrimaryClipChangedListener] to
 * detect clipboard changes.
 *
 * @property context Application context.
 * @property clipboardRepository Repository for persisting clipboard items.
 * @property clipboardHelper Helper for reading/writing the clipboard.
 * @property syncManager Sync manager for publishing clipboard changes.
 */
class ClipboardMonitor(
    private val context: Context,
    private val clipboardRepository: ClipboardRepository,
    private val clipboardHelper: ClipboardHelper,
    private val syncManager: SyncManager
) {
    companion object {
        private const val TAG = "ClipboardMonitor"
    }

    /** Coroutine scope for async operations. */
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    /** The system ClipboardManager. */
    private val clipboardManager: ClipboardManager by lazy {
        context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    }

    /** The clip change listener reference (kept to allow unregistration). */
    private var clipListener: ClipboardManager.OnPrimaryClipChangedListener? = null

    /** Whether monitoring is currently active. */
    @Volatile
    private var isMonitoring = false

    /** The last digest we processed, to avoid duplicate processing. */
    @Volatile
    private var lastProcessedDigest: String = ""

    /**
     * Start monitoring the clipboard for changes.
     *
     * If already monitoring, this is a no-op.
     */
    fun startMonitoring() {
        if (isMonitoring) {
            Log.d(TAG, "Already monitoring clipboard")
            return
        }

        val listener = ClipboardManager.OnPrimaryClipChangedListener {
            onClipChanged()
        }

        clipListener = listener
        clipboardManager.addPrimaryClipChangedListener(listener)
        isMonitoring = true
        Log.i(TAG, "Clipboard monitoring started")
    }

    /**
     * Stop monitoring the clipboard.
     */
    fun stopMonitoring() {
        if (!isMonitoring) return

        clipListener?.let {
            clipboardManager.removePrimaryClipChangedListener(it)
        }
        clipListener = null
        isMonitoring = false
        Log.i(TAG, "Clipboard monitoring stopped")
    }

    /**
     * Called when the system clipboard content changes.
     * Reads the current clipboard, computes a digest, and persists
     * the item if it is new (not a duplicate).
     */
    private fun onClipChanged() {
        scope.launch {
            try {
                val text = clipboardHelper.readText()
                if (text.isNullOrEmpty()) {
                    // Could be an image or unsupported format
                    Log.d(TAG, "Clipboard changed but no text content available")
                    return@launch
                }

                val digest = clipboardHelper.computeTextDigest(text)
                if (digest == lastProcessedDigest) {
                    Log.d(TAG, "Skipping duplicate clipboard content: $digest")
                    return@launch
                }

                // Check database deduplication
                val existing = clipboardRepository.getItemByDigest(digest)
                if (existing != null) {
                    Log.d(TAG, "Clipboard item already in database: $digest")
                    lastProcessedDigest = digest
                    return@launch
                }

                val now = DateTimeFormatter
                    .ofPattern("yyyy-MM-dd HH:mm:ss")
                    .withZone(ZoneId.systemDefault())
                    .format(Instant.now())

                val preview = if (text.length > 80) {
                    text.take(79) + "..."
                } else {
                    text.replace("\r", "\n").replace("\n", " ").trim()
                }

                val entity = ClipboardItemEntity(
                    type = "text",
                    text = text,
                    preview = preview,
                    digest = digest,
                    time = now,
                    size = text.toByteArray(Charsets.UTF_8).size.toLong()
                )

                val rowId = clipboardRepository.insertItem(entity)
                if (rowId >= 0) {
                    lastProcessedDigest = digest
                    Log.i(TAG, "Saved clipboard item: digest=$digest, rowId=$rowId")

                    // Publish to sync
                    publishClipboardItem(entity)
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error processing clipboard change", e)
            }
        }
    }

    /**
     * Publish a locally captured clipboard item to connected sync devices.
     */
    private fun publishClipboardItem(item: ClipboardItemEntity) {
        try {
            val itemData = mutableMapOf<String, Any>(
                "type" to item.type,
                "time" to item.time,
                "digest" to item.digest,
                "preview" to item.preview
            )

            if (item.type == "text" && !item.text.isNullOrEmpty()) {
                itemData["text"] = item.text
            }

            if (item.type == "image") {
                item.imagePath?.let { itemData["image_path"] = it }
                item.dibB64?.let { itemData["dib_b64"] = it }
                itemData["size"] = item.size
            }

            val config = SyncConfig(
                enabled = true,
                nodeId = syncManager.nodeId,
                syncText = true,
                syncImages = true
            )

            syncManager.publishClipboardItem(item.type, itemData)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to publish clipboard item via sync", e)
        }
    }

    /**
     * Handle a clipboard item received from a remote device via sync.
     * Persists it to the database and writes to the system clipboard.
     */
    fun onSyncedClipboardItemReceived(itemType: String, itemData: Map<String, Any>) {
        scope.launch {
            try {
                val digest = itemData["digest"] as? String ?: ""
                if (digest.isNotEmpty() && digest == lastProcessedDigest) {
                    return@launch
                }

                val now = DateTimeFormatter
                    .ofPattern("yyyy-MM-dd HH:mm:ss")
                    .withZone(ZoneId.systemDefault())
                    .format(Instant.now())

                val entity = when (itemType) {
                    "text" -> {
                        val text = itemData["text"] as? String ?: return@launch
                        val preview = itemData["preview"] as? String
                            ?: text.take(80)
                        ClipboardItemEntity(
                            type = "text",
                            text = text,
                            preview = preview,
                            digest = digest,
                            time = now,
                            size = text.toByteArray(Charsets.UTF_8).size.toLong()
                        )
                    }
                    "image" -> {
                        val dibB64 = itemData["dib_b64"] as? String
                        val size = (itemData["size"] as? Number)?.toLong() ?: 0L
                        val preview = itemData["preview"] as? String
                            ?: "图片数据 ($size bytes)"
                        ClipboardItemEntity(
                            type = "image",
                            preview = preview,
                            digest = digest,
                            time = now,
                            size = size,
                            dibB64 = dibB64
                        )
                    }
                    else -> return@launch
                }

                val rowId = clipboardRepository.insertItem(entity)
                if (rowId >= 0) {
                    lastProcessedDigest = digest
                    Log.i(TAG, "Saved synced clipboard item: digest=$digest, rowId=$rowId")

                    // Write to system clipboard (text only)
                    if (itemType == "text") {
                        val text = itemData["text"] as? String ?: return@launch
                        clipboardHelper.writeText(text)
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Error processing synced clipboard item", e)
            }
        }
    }
}
