package com.integratedcaptureclipboard.android.data.db

import androidx.room.ColumnInfo
import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * Room Entity representing a clipboard history item.
 * Stores text clips, image references, and file references
 * that have been captured from the system clipboard or received via sync.
 */
@Entity(tableName = "clipboard_items")
data class ClipboardItemEntity(
    @PrimaryKey(autoGenerate = true)
    val id: Long = 0,

    /** Item type: "text", "image", or "files". */
    @ColumnInfo(name = "type")
    val type: String,

    /** Text content for text items. Null for image/file items. */
    @ColumnInfo(name = "text", defaultValue = "NULL")
    val text: String? = null,

    /** Local file path for image items. Null for text items. */
    @ColumnInfo(name = "image_path", defaultValue = "NULL")
    val imagePath: String? = null,

    /** Base64-encoded DIB data for image items (used for sync). Null for text items. */
    @ColumnInfo(name = "dib_b64", defaultValue = "NULL")
    val dibB64: String? = null,

    /** Size of the clipboard data in bytes. */
    @ColumnInfo(name = "size", defaultValue = "0")
    val size: Long = 0,

    /** Preview text (shortened content preview). */
    @ColumnInfo(name = "preview", defaultValue = "")
    val preview: String = "",

    /** Digest string for deduplication (e.g. "text:sha256hex" or "image:sha256hex"). */
    @ColumnInfo(name = "digest", defaultValue = "")
    val digest: String = "",

    /** Timestamp when the item was captured (display format: "2025-07-11 12:00:00"). */
    @ColumnInfo(name = "time")
    val time: String,

    /** Device ID from which this item was synced. Null if captured locally. */
    @ColumnInfo(name = "synced_from", defaultValue = "NULL")
    val syncedFrom: String? = null
)
