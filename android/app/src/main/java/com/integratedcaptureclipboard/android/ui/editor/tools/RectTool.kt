package com.integratedcaptureclipboard.android.ui.editor.tools

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import com.integratedcaptureclipboard.android.ui.editor.EditorAction

/**
 * Rectangle tool implementation for the image editor.
 *
 * Handles drawing rectangular frames between two corner points.
 * The user drags from one corner to the opposite corner to
 * define the rectangle.
 */
object RectTool {

    /**
     * Render a rectangle action on the canvas.
     *
     * @param drawScope The drawing scope.
     * @param action The rectangle action to render.
     */
    fun renderAction(drawScope: DrawScope, action: EditorAction.RectDraw) {
        renderRect(drawScope, action.topLeft, action.bottomRight, action.color, action.strokeWidth)
    }

    /**
     * Render a preview rectangle (while the user is dragging).
     *
     * @param drawScope The drawing scope.
     * @param start The first corner (drag start).
     * @param end The opposite corner (drag end).
     * @param color The stroke color.
     * @param strokeWidth The stroke width.
     */
    fun renderPreview(
        drawScope: DrawScope,
        start: Offset,
        end: Offset,
        color: Color,
        strokeWidth: Float
    ) {
        val topLeft = Offset(minOf(start.x, end.x), minOf(start.y, end.y))
        val bottomRight = Offset(maxOf(start.x, end.x), maxOf(start.y, end.y))
        renderRect(drawScope, topLeft, bottomRight, color, strokeWidth)
    }

    /**
     * Draw a rectangle outline between two corner points.
     */
    private fun renderRect(
        drawScope: DrawScope,
        topLeft: Offset,
        bottomRight: Offset,
        color: Color,
        strokeWidth: Float
    ) {
        val width = bottomRight.x - topLeft.x
        val height = bottomRight.y - topLeft.y

        if (width <= 0f || height <= 0f) return

        drawScope.drawRect(
            color = color,
            topLeft = topLeft,
            size = androidx.compose.ui.geometry.Size(width, height),
            style = Stroke(width = strokeWidth)
        )
    }
}
