package com.integratedcaptureclipboard.android.ui.editor.tools

import android.graphics.Bitmap
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import com.integratedcaptureclipboard.android.ui.editor.EditorAction

/**
 * Mosaic (pixelation) tool implementation for the image editor.
 *
 * Applies a pixelation effect to a selected rectangular region.
 * The pixelation works by:
 * 1. Dividing the region into blocks of [blockSize] x [blockSize] pixels
 * 2. Computing the average color of each block
 * 3. Filling each block with its average color
 *
 * This provides a visual "censorship" effect commonly used to
 * obscure sensitive information in images.
 */
object MosaicTool {

    /**
     * Render a mosaic region action on the canvas.
     *
     * This requires access to the original image bitmap to compute
     * block colors. The mosaic effect is applied directly to the
     * bitmap and then drawn.
     *
     * @param drawScope The drawing scope.
     * @param action The mosaic region action to render.
     * @param sourceBitmap The original source image bitmap for color sampling.
     */
    fun renderAction(
        drawScope: DrawScope,
        action: EditorAction.MosaicRegion,
        sourceBitmap: ImageBitmap?
    ) {
        if (sourceBitmap == null) return

        val androidBitmap = sourceBitmap.asAndroidBitmap()
        val mosaicBitmap = applyMosaic(
            androidBitmap,
            action.topLeft,
            action.bottomRight,
            action.blockSize
        )

        drawScope.drawImage(
            image = mosaicBitmap.asImageBitmap()
        )
    }

    /**
     * Render a preview of the mosaic region (selection rectangle while dragging).
     *
     * @param drawScope The drawing scope.
     * @param start The drag start point.
     * @param end The current drag end point.
     */
    fun renderPreview(
        drawScope: DrawScope,
        start: Offset,
        end: Offset
    ) {
        val topLeft = Offset(minOf(start.x, end.x), minOf(start.y, end.y))
        val bottomRight = Offset(maxOf(start.x, end.x), maxOf(start.y, end.y))
        val width = bottomRight.x - topLeft.x
        val height = bottomRight.y - topLeft.y

        if (width <= 0f || height <= 0f) return

        // Draw a semi-transparent overlay to indicate the selection area
        drawScope.drawRect(
            color = Color.Gray.copy(alpha = 0.3f),
            topLeft = topLeft,
            size = androidx.compose.ui.geometry.Size(width, height)
        )

        // Draw a dashed-style border
        drawScope.drawRect(
            color = Color.White,
            topLeft = topLeft,
            size = androidx.compose.ui.geometry.Size(width, height),
            style = androidx.compose.ui.graphics.drawscope.Stroke(width = 2f)
        )
    }

    /**
     * Apply mosaic pixelation to a region of the bitmap.
     *
     * @param source The source bitmap (will be copied, not modified in place).
     * @param topLeft The top-left corner of the mosaic region.
     * @param bottomRight The bottom-right corner of the mosaic region.
     * @param blockSize The size of each mosaic block in pixels.
     * @return A new bitmap with the mosaic effect applied.
     */
    private fun applyMosaic(
        source: Bitmap,
        topLeft: Offset,
        bottomRight: Offset,
        blockSize: Int
    ): Bitmap {
        val result = source.copy(Bitmap.Config.ARGB_8888, true) ?: return source

        val startX = topLeft.x.toInt().coerceAtLeast(0).coerceAtMost(result.width - 1)
        val startY = topLeft.y.toInt().coerceAtLeast(0).coerceAtMost(result.height - 1)
        val endX = bottomRight.x.toInt().coerceAtLeast(0).coerceAtMost(result.width)
        val endY = bottomRight.y.toInt().coerceAtLeast(0).coerceAtMost(result.height)

        val effectiveBlockSize = blockSize.coerceAtLeast(2)

        for (blockY in startY until endY step effectiveBlockSize) {
            for (blockX in startX until endX step effectiveBlockSize) {
                // Compute the average color of this block
                var totalR = 0L
                var totalG = 0L
                var totalB = 0L
                var count = 0

                val blockEndX = (blockX + effectiveBlockSize).coerceAtMost(endX)
                val blockEndY = (blockY + effectiveBlockSize).coerceAtMost(endY)

                for (y in blockY until blockEndY) {
                    for (x in blockX until blockEndX) {
                        val pixel = result.getPixel(x, y)
                        totalR += (pixel shr 16) and 0xFF
                        totalG += (pixel shr 8) and 0xFF
                        totalB += pixel and 0xFF
                        count++
                    }
                }

                if (count > 0) {
                    val avgR = (totalR / count).toInt()
                    val avgG = (totalG / count).toInt()
                    val avgB = (totalB / count).toInt()
                    val avgColor = (0xFF shl 24) or (avgR shl 16) or (avgG shl 8) or avgB

                    // Fill the block with the average color
                    for (y in blockY until blockEndY) {
                        for (x in blockX until blockEndX) {
                            result.setPixel(x, y, avgColor)
                        }
                    }
                }
            }
        }

        return result
    }

    /**
     * Apply mosaic to a Bitmap directly (for saving the result).
     *
     * @param bitmap The bitmap to modify.
     * @param actions List of mosaic actions to apply.
     * @return The modified bitmap.
     */
    fun applyMosaicActions(bitmap: Bitmap, actions: List<EditorAction.MosaicRegion>): Bitmap {
        var result = bitmap.copy(Bitmap.Config.ARGB_8888, true) ?: return bitmap
        for (action in actions) {
            result = applyMosaic(result, action.topLeft, action.bottomRight, action.blockSize)
        }
        return result
    }
}
