package com.integratedcaptureclipboard.android.screenshot

import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.Image
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.util.DisplayMetrics
import android.util.Log
import android.view.WindowManager

/**
 * Performs screen capture using MediaProjection + VirtualDisplay + ImageReader.
 *
 * After a [MediaProjection] is acquired (via [MediaProjectionManager]),
 * this class creates a VirtualDisplay and ImageReader to capture the
 * screen content as a [Bitmap].
 *
 * Usage:
 * 1. Create instance with a [MediaProjection]
 * 2. Call [captureScreen] to get a screenshot bitmap
 * 3. Call [release] when done to free resources
 *
 * @property mediaProjection The active MediaProjection for screen capture.
 */
class ScreenCapturer(
    private val mediaProjection: MediaProjection
) {
    companion object {
        private const val TAG = "ScreenCapturer"
        private const val VIRTUAL_DISPLAY_NAME = "ICC ScreenCapture"
        private const val SCREEN_DPI = 160

        /**
         * Utility: Get the screen dimensions from the window manager.
         *
         * @param context Application context.
         * @return A triple of (width, height, densityDpi).
         */
        fun getScreenDimensions(context: android.content.Context): Triple<Int, Int, Int> {
            val windowManager = context.getSystemService(android.content.Context.WINDOW_SERVICE) as WindowManager
            val metrics = DisplayMetrics()
            @Suppress("DEPRECATION")
            windowManager.defaultDisplay.getRealMetrics(metrics)
            return Triple(metrics.widthPixels, metrics.heightPixels, metrics.densityDpi)
        }
    }

    /** The ImageReader used to capture screen frames. */
    private var imageReader: ImageReader? = null

    /** The VirtualDisplay used to mirror the screen. */
    private var virtualDisplay: VirtualDisplay? = null

    /** Screen dimensions. */
    private var screenWidth: Int = 0
    private var screenHeight: Int = 0
    private var screenDensity: Int = SCREEN_DPI

    /**
     * Initialize the screen capturer, creating the VirtualDisplay
     * and ImageReader with the given screen dimensions.
     *
     * @param width Screen width in pixels.
     * @param height Screen height in pixels.
     * @param density Screen density DPI.
     */
    fun initialize(width: Int, height: Int, density: Int = SCREEN_DPI) {
        screenWidth = width
        screenHeight = height
        screenDensity = density

        imageReader = ImageReader.newInstance(
            screenWidth,
            screenHeight,
            PixelFormat.RGBA_8888,
            2
        )

        virtualDisplay = mediaProjection.createVirtualDisplay(
            VIRTUAL_DISPLAY_NAME,
            screenWidth,
            screenHeight,
            screenDensity,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader?.surface,
            null,
            null
        )

        Log.d(TAG, "ScreenCapturer initialized: ${screenWidth}x${screenHeight}@${screenDensity}dpi")
    }

    /**
     * Capture the current screen content as a Bitmap.
     *
     * Waits for the next available frame from the ImageReader
     * and converts it to a Bitmap.
     *
     * @param timeoutMs Maximum time to wait for a frame in milliseconds.
     * @return The captured bitmap, or null if capture failed.
     */
    fun captureScreen(timeoutMs: Long = 3000L): Bitmap? {
        val reader = imageReader ?: run {
            Log.w(TAG, "ImageReader not initialized")
            return null
        }

        // Wait for a new frame
        var image: Image? = null
        try {
            val startTime = System.currentTimeMillis()
            while (image == null && (System.currentTimeMillis() - startTime) < timeoutMs) {
                image = reader.acquireLatestImage()
                if (image == null) {
                    Thread.sleep(50)
                }
            }

            if (image == null) {
                Log.w(TAG, "Timeout waiting for screen capture frame")
                return null
            }

            val planes = image.planes
            if (planes.isEmpty()) {
                Log.w(TAG, "No planes in captured image")
                return null
            }

            val plane = planes[0]
            val buffer = plane.buffer
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - pixelStride * screenWidth

            val bitmapWidth = screenWidth + rowPadding / pixelStride
            val bitmap = Bitmap.createBitmap(
                bitmapWidth,
                screenHeight,
                Bitmap.Config.ARGB_8888
            )

            buffer.rewind()
            bitmap.copyPixelsFromBuffer(buffer)

            // Crop the padding if present
            return if (rowPadding == 0) {
                bitmap
            } else {
                val cropped = Bitmap.createBitmap(bitmap, 0, 0, screenWidth, screenHeight)
                bitmap.recycle()
                cropped
            }
        } catch (e: Exception) {
            Log.e(TAG, "Error capturing screen", e)
            return null
        } finally {
            image?.close()
        }
    }

    /**
     * Release all resources held by this capturer.
     * Must be called when screen capture is no longer needed.
     */
    fun release() {
        try {
            virtualDisplay?.release()
        } catch (e: Exception) {
            Log.w(TAG, "Error releasing VirtualDisplay", e)
        }
        virtualDisplay = null

        try {
            imageReader?.close()
        } catch (e: Exception) {
            Log.w(TAG, "Error closing ImageReader", e)
        }
        imageReader = null

        Log.d(TAG, "ScreenCapturer released")
    }

}
