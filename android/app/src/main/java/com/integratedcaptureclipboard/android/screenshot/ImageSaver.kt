package com.integratedcaptureclipboard.android.screenshot

import android.content.ContentValues
import android.content.Context
import android.graphics.Bitmap
import android.os.Build
import android.os.Environment
import android.provider.MediaStore
import android.util.Log
import java.io.File
import java.io.FileOutputStream
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject

/**
 * Saves screenshot bitmaps to local storage.
 *
 * Supports saving to:
 * - App-private directory (always accessible)
 * - MediaStore / Pictures directory (visible in gallery, Android 10+)
 *
 * @property context Application context.
 */
class ImageSaver @Inject constructor(@ApplicationContext private val context: Context) {

    companion object {
        private const val TAG = "ImageSaver"
        private const val SCREENSHOT_DIR_NAME = "ICC_Screenshots"
        private const val FILENAME_PATTERN = "screenshot_%s.png"
        private const val DATE_FORMAT = "yyyyMMdd_HHmmss"
    }

    /**
     * Save a bitmap to the app-private files directory.
     *
     * This location is always writable without permissions, but files
     * are not visible to other apps or the gallery.
     *
     * @param bitmap The bitmap to save.
     * @return The absolute path of the saved file, or null on failure.
     */
    fun saveToPrivateDir(bitmap: Bitmap): String? {
        val timestamp = SimpleDateFormat(DATE_FORMAT, Locale.US).format(Date())
        val filename = FILENAME_PATTERN.format(timestamp)

        val dir = File(context.filesDir, SCREENSHOT_DIR_NAME)
        if (!dir.exists()) {
            dir.mkdirs()
        }

        val file = File(dir, filename)
        return try {
            FileOutputStream(file).use { fos ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, fos)
                fos.flush()
            }
            Log.i(TAG, "Screenshot saved to private dir: ${file.absolutePath}")
            file.absolutePath
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save screenshot to private dir", e)
            null
        }
    }

    /**
     * Save a bitmap to the MediaStore Pictures directory.
     *
     * On Android 10+ (API 29+), uses MediaStore API which doesn't
     * require storage permissions. On older versions, uses
     * Environment.getExternalStoragePublicDirectory.
     *
     * @param bitmap The bitmap to save.
     * @return The absolute path of the saved file, or null on failure.
     */
    fun saveToMediaStore(bitmap: Bitmap): String? {
        val timestamp = SimpleDateFormat(DATE_FORMAT, Locale.US).format(Date())
        val filename = FILENAME_PATTERN.format(timestamp)

        return try {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                saveWithMediaStoreApi(bitmap, filename)
            } else {
                @Suppress("DEPRECATION")
                saveWithLegacyApi(bitmap, filename)
            }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to save screenshot to MediaStore", e)
            // Fallback to private dir
            saveToPrivateDir(bitmap)
        }
    }

    /**
     * Save using the MediaStore API (Android 10+).
     */
    private fun saveWithMediaStoreApi(bitmap: Bitmap, filename: String): String? {
        val contentValues = ContentValues().apply {
            put(MediaStore.Images.Media.DISPLAY_NAME, filename)
            put(MediaStore.Images.Media.MIME_TYPE, "image/png")
            put(MediaStore.Images.Media.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/$SCREENSHOT_DIR_NAME")
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                put(MediaStore.Images.Media.IS_PENDING, 1)
            }
        }

        val uri = context.contentResolver.insert(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            contentValues
        ) ?: return null

        try {
            context.contentResolver.openOutputStream(uri)?.use { os ->
                bitmap.compress(Bitmap.CompressFormat.PNG, 100, os)
                os.flush()
            }

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                contentValues.clear()
                contentValues.put(MediaStore.Images.Media.IS_PENDING, 0)
                context.contentResolver.update(uri, contentValues, null, null)
            }

            // Query the actual file path
            val projection = arrayOf(MediaStore.Images.Media.DATA)
            context.contentResolver.query(uri, projection, null, null, null)?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val path = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Images.Media.DATA))
                    Log.i(TAG, "Screenshot saved to MediaStore: $path")
                    return path
                }
            }

            Log.i(TAG, "Screenshot saved to MediaStore (URI: $uri)")
            return uri.toString()
        } catch (e: Exception) {
            context.contentResolver.delete(uri, null, null)
            throw e
        }
    }

    /**
     * Save using the legacy external storage API (pre-Android 10).
     */
    @Suppress("DEPRECATION")
    private fun saveWithLegacyApi(bitmap: Bitmap, filename: String): String? {
        val dir = File(
            Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES),
            SCREENSHOT_DIR_NAME
        )
        if (!dir.exists()) {
            dir.mkdirs()
        }

        val file = File(dir, filename)
        FileOutputStream(file).use { fos ->
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, fos)
            fos.flush()
        }
        Log.i(TAG, "Screenshot saved to legacy path: ${file.absolutePath}")
        return file.absolutePath
    }
}
