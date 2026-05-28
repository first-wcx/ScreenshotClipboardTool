package com.integratedcaptureclipboard.android.screenshot

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.util.Log
import androidx.activity.result.ActivityResultLauncher

/**
 * Manages the MediaProjection lifecycle for screen capture.
 *
 * Handles requesting screen capture permission, obtaining the
 * MediaProjection instance, and proper cleanup on release.
 *
 * On Android 10+, screen capture requires user confirmation via
 * a system dialog. The result is delivered via [ActivityResultLauncher].
 *
 * @property context Application context for accessing system services.
 */
class MediaProjectionManager(private val context: Context) {

    companion object {
        private const val TAG = "MediaProjectionManager"
        /** Request code for the screen capture permission dialog. */
        const val REQUEST_CODE_SCREEN_CAPTURE = 1001
    }

    /** The system MediaProjectionManager. */
    private val projectionManager: MediaProjectionManager by lazy {
        context.getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
    }

    /** The current active MediaProjection, or null if not acquired. */
    @Volatile
    var mediaProjection: MediaProjection? = null
        private set

    /** Callback for media projection state changes. */
    private var projectionCallback: MediaProjection.Callback? = null

    /**
     * Create the screen capture permission intent.
     * This intent must be launched via [ActivityResultLauncher] to
     * obtain user consent.
     *
     * @return The intent to launch for screen capture permission.
     */
    fun createScreenCaptureIntent(): Intent {
        return projectionManager.createScreenCaptureIntent()
    }

    /**
     * Acquire a MediaProjection from the permission result.
     *
     * Must be called from [ActivityResultLauncher]'s callback with
     * the result code and data intent.
     *
     * @param resultCode The result code from the permission activity.
     * @param data The result data intent from the permission activity.
     * @return The acquired MediaProjection, or null if acquisition failed.
     */
    fun acquireProjection(resultCode: Int, data: Intent): MediaProjection? {
        if (resultCode != Activity.RESULT_OK) {
            Log.w(TAG, "Screen capture permission denied (resultCode=$resultCode)")
            return null
        }

        try {
            val projection = projectionManager.getMediaProjection(resultCode, data)
            this.mediaProjection = projection

            // Set up a callback to detect when the projection is stopped
            val callback = object : MediaProjection.Callback() {
                override fun onStop() {
                    Log.i(TAG, "MediaProjection stopped")
                    this@MediaProjectionManager.mediaProjection = null
                }
            }
            projection.registerCallback(callback, null)
            projectionCallback = callback

            Log.i(TAG, "MediaProjection acquired successfully")
            return projection
        } catch (e: SecurityException) {
            Log.e(TAG, "SecurityException acquiring MediaProjection", e)
            return null
        } catch (e: Exception) {
            Log.e(TAG, "Error acquiring MediaProjection", e)
            return null
        }
    }

    /**
     * Release the current MediaProjection.
     *
     * Should be called when screen capture is no longer needed
     * to free system resources.
     */
    fun releaseProjection() {
        mediaProjection?.let {
            try {
                projectionCallback?.let { callback -> it.unregisterCallback(callback) }
                it.stop()
            } catch (e: Exception) {
                Log.w(TAG, "Error releasing MediaProjection", e)
            }
        }
        mediaProjection = null
        projectionCallback = null
        Log.d(TAG, "MediaProjection released")
    }

    /**
     * Check whether a MediaProjection is currently active.
     *
     * @return True if an active projection is available.
     */
    fun isProjectionActive(): Boolean = mediaProjection != null
}
