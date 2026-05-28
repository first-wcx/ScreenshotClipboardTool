package com.integratedcaptureclipboard.android.clipboard

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.util.Base64
import java.security.MessageDigest

/**
 * Utility class for reading from and writing to the Android system clipboard.
 *
 * Provides a simplified API for the most common clipboard operations
 * (text read/write) and digest computation for deduplication.
 *
 * @property context Application context used to obtain the ClipboardManager.
 */
class ClipboardHelper(private val context: Context) {

    /** The system ClipboardManager. */
    private val clipboardManager: ClipboardManager by lazy {
        context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
    }

    /**
     * Read the current primary clipboard text, if available.
     *
     * @return The clipboard text, or null if no text is available.
     */
    fun readText(): String? {
        val clip = clipboardManager.primaryClip ?: return null
        if (clip.itemCount == 0) return null
        return clip.getItemAt(0)?.text?.toString()
    }

    /**
     * Check whether the clipboard currently contains text.
     *
     * @return True if the clipboard has text content.
     */
    fun hasText(): Boolean {
        val clip = clipboardManager.primaryClip ?: return false
        if (clip.itemCount == 0) return false
        return clip.description.hasMimeType(ClipDescription.MIMETYPE_TEXT_PLAIN) ||
                clip.description.hasMimeType(ClipDescription.MIMETYPE_TEXT_HTML)
    }

    /**
     * Write text to the system clipboard.
     *
     * @param text The text to copy to the clipboard.
     */
    fun writeText(text: String) {
        val clip = ClipData.newPlainText("text", text)
        clipboardManager.setPrimaryClip(clip)
    }

    /**
     * Compute a SHA-256 digest for deduplication.
     *
     * @param text The input text.
     * @return A hex-encoded digest string prefixed with "text:".
     */
    fun computeTextDigest(text: String): String {
        val bytes = MessageDigest.getInstance("SHA-256")
            .digest(text.toByteArray(Charsets.UTF_8))
        val hex = bytes.joinToString("") { "%02x".format(it) }
        return "text:$hex"
    }

    /**
     * Compute a SHA-256 digest for image data deduplication.
     *
     * @param imageData The raw image bytes.
     * @return A hex-encoded digest string prefixed with "image:".
     */
    fun computeImageDigest(imageData: ByteArray): String {
        val bytes = MessageDigest.getInstance("SHA-256").digest(imageData)
        val hex = bytes.joinToString("") { "%02x".format(it) }
        return "image:$hex"
    }

    companion object {
        /** MIME type constants for clipboard format detection. */
        const val MIME_TEXT_PLAIN = "text/plain"
        const val MIME_TEXT_HTML = "text/html"
    }
}

/**
 * ClipDescription compatibility helper — provides MIME type constants
 * that may not be available on all API levels.
 */
private object ClipDescription {
    const val MIMETYPE_TEXT_PLAIN = "text/plain"
    const val MIMETYPE_TEXT_HTML = "text/html"
}
