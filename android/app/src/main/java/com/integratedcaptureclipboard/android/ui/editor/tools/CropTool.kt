package com.integratedcaptureclipboard.android.ui.editor.tools

import android.graphics.Bitmap
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import com.integratedcaptureclipboard.android.ui.editor.CropRect
import com.integratedcaptureclipboard.android.ui.editor.EditorAction

/**
 * Crop tool implementation for the image editor.
 *
 * Allows the user to select a rectangular region and crop the image
 * to that region. The crop region is displayed as a highlighted
 * rectangle with semi-transparent overlay outside the selection.
 */
object CropTool {

    /** Color of the crop overlay outside the selected region. */
    private val OVERLAY_COLOR = Color.Black.copy(alpha = 0.5f)

    /** Color of the crop selection border. */
    private val BORDER_COLOR = Color.White

    /**
     * Render a crop action's selection rectangle on the canvas.
     *
     * @param drawScope The drawing scope.
     * @param action The crop action to render.
     * @param canvasWidth The canvas width for overlay calculation.
     * @param canvasHeight The canvas height for overlay calculation.
     */
    fun renderAction(
        drawScope: DrawScope,
        action: EditorAction.CropAction,
        canvasWidth: Float,
        canvasHeight: Float
    ) {
        val cropRect = action.cropRect
        renderCropOverlay(
            drawScope,
            cropRect = CropRect(
                left = cropRect.left,
                top = cropRect.top,
                right = cropRect.right,
                bottom = cropRect.bottom
            ),
            canvasWidth = canvasWidth,
            canvasHeight = canvasHeight
        )
    }

    /**
     * Render a crop preview (selection rectangle while dragging).
     *
     * @param drawScope The drawing scope.
     * @param start The drag start point.
     * @param end The current drag end point.
     * @param canvasWidth The canvas width.
     * @param canvasHeight The canvas height.
     */
    fun renderPreview(
        drawScope: DrawScope,
        start: Offset,
        end: Offset,
        canvasWidth: Float,
        canvasHeight: Float
    ) {
        val left = minOf(start.x, end.x).toInt()
        val top = minOf(start.y, end.y).toInt()
        val right = maxOf(start.x, end.x).toInt()
        val bottom = maxOf(start.y, end.y).toInt()

        renderCropOverlay(
            drawScope,
            cropRect = CropRect(left, top, right, bottom),
            canvasWidth = canvasWidth,
            canvasHeight = canvasHeight
        )
    }

    /**
     * Draw the crop overlay: darken areas outside the selection
     * and highlight the selection border.
     */
    private fun renderCropOverlay(
        drawScope: DrawScope,
        cropRect: CropRect,
        canvasWidth: Float,
        canvasHeight: Float
    ) {
        // Top overlay
        if (cropRect.top > 0) {
            drawScope.drawRect(
                color = OVERLAY_COLOR,
                topLeft = Offset(0f, 0f),
                size = androidx.compose.ui.geometry.Size(canvasWidth, cropRect.top.toFloat())
            )
        }

        // Bottom overlay
        if (cropRect.bottom < canvasHeight) {
            drawScope.drawRect(
                color = OVERLAY_COLOR,
                topLeft = Offset(0f, cropRect.bottom.toFloat()),
                size = androidx.compose.ui.geometry.Size(canvasWidth, canvasHeight - cropRect.bottom)
            )
        }

        // Left overlay
        if (cropRect.left > 0) {
            drawScope.drawRect(
                color = OVERLAY_COLOR,
                topLeft = Offset(0f, cropRect.top.toFloat()),
                size = androidx.compose.ui.geometry.Size(cropRect.left.toFloat(), cropRect.height.toFloat())
            )
        }

        // Right overlay
        if (cropRect.right < canvasWidth) {
            drawScope.drawRect(
                color = OVERLAY_COLOR,
                topLeft = Offset(cropRect.right.toFloat(), cropRect.top.toFloat()),
                size = androidx.compose.ui.geometry.Size(canvasWidth - cropRect.right, cropRect.height.toFloat())
            )
        }

        // Selection border
        drawScope.drawRect(
            color = BORDER_COLOR,
            topLeft = Offset(cropRect.left.toFloat(), cropRect.top.toFloat()),
            size = androidx.compose.ui.geometry.Size(cropRect.width.toFloat(), cropRect.height.toFloat()),
            style = Stroke(width = 2f)
        )

        // Corner handles
        val handleSize = 12f
        val corners = listOf(
            Offset(cropRect.left.toFloat(), cropRect.top.toFloat()),
            Offset(cropRect.right.toFloat(), cropRect.top.toFloat()),
            Offset(cropRect.left.toFloat(), cropRect.bottom.toFloat()),
            Offset(cropRect.right.toFloat(), cropRect.bottom.toFloat())
        )
        for (corner in corners) {
            drawScope.drawRect(
                color = BORDER_COLOR,
                topLeft = Offset(corner.x - handleSize / 2, corner.y - handleSize / 2),
                size = androidx.compose.ui.geometry.Size(handleSize, handleSize)
            )
        }
    }

    /**
     * Apply a crop action to a bitmap, returning a new cropped bitmap.
     *
     * @param bitmap The source bitmap.
     * @param cropRect The crop region.
     * @return A new bitmap containing only the cropped region.
     */
    fun applyCrop(bitmap: Bitmap, cropRect: CropRect): Bitmap {
        val x = cropRect.left.coerceAtLeast(0)
        val y = cropRect.top.coerceAtLeast(0)
        val width = cropRect.width.coerceAtLeast(1).coerceAtMost(bitmap.width - x)
        val height = cropRect.height.coerceAtLeast(1).coerceAtMost(bitmap.height - y)

        return Bitmap.createBitmap(bitmap, x, y, width, height)
    }
}
