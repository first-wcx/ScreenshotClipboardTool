package com.integratedcaptureclipboard.android.ui.editor.tools

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import com.integratedcaptureclipboard.android.ui.editor.EditorAction
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.sin

/**
 * Arrow tool implementation for the image editor.
 *
 * Handles drawing a directional arrow between two points.
 * The arrow consists of a line from start to end, with an
 * arrowhead at the end point.
 */
object ArrowTool {

    /** Length of the arrowhead lines relative to the shaft. */
    private const val ARROW_HEAD_LENGTH = 24f
    private const val ARROW_HEAD_ANGLE = Math.PI / 6.0 // 30 degrees

    /**
     * Render an arrow action on the canvas.
     *
     * @param drawScope The drawing scope.
     * @param action The arrow action to render.
     */
    fun renderAction(drawScope: DrawScope, action: EditorAction.ArrowDraw) {
        renderArrow(drawScope, action.start, action.end, action.color, action.strokeWidth)
    }

    /**
     * Render a preview arrow (while the user is dragging).
     *
     * @param drawScope The drawing scope.
     * @param start The start point of the arrow.
     * @param end The current end point.
     * @param color The arrow color.
     * @param strokeWidth The stroke width.
     */
    fun renderPreview(
        drawScope: DrawScope,
        start: Offset,
        end: Offset,
        color: Color,
        strokeWidth: Float
    ) {
        renderArrow(drawScope, start, end, color, strokeWidth)
    }

    /**
     * Draw an arrow from start to end with an arrowhead.
     */
    private fun renderArrow(
        drawScope: DrawScope,
        start: Offset,
        end: Offset,
        color: Color,
        strokeWidth: Float
    ) {
        // Draw the main shaft line
        drawScope.drawLine(
            color = color,
            start = start,
            end = end,
            strokeWidth = strokeWidth,
            cap = StrokeCap.Round
        )

        // Calculate arrowhead
        val dx = end.x - start.x
        val dy = end.y - start.y
        val angle = atan2(dy.toDouble(), dx.toDouble())

        // Arrowhead line 1
        val headEnd1 = Offset(
            x = end.x - ARROW_HEAD_LENGTH * cos(angle + ARROW_HEAD_ANGLE).toFloat(),
            y = end.y - ARROW_HEAD_LENGTH * sin(angle + ARROW_HEAD_ANGLE).toFloat()
        )

        // Arrowhead line 2
        val headEnd2 = Offset(
            x = end.x - ARROW_HEAD_LENGTH * cos(angle - ARROW_HEAD_ANGLE).toFloat(),
            y = end.y - ARROW_HEAD_LENGTH * sin(angle - ARROW_HEAD_ANGLE).toFloat()
        )

        drawScope.drawLine(
            color = color,
            start = end,
            end = headEnd1,
            strokeWidth = strokeWidth,
            cap = StrokeCap.Round
        )

        drawScope.drawLine(
            color = color,
            start = end,
            end = headEnd2,
            strokeWidth = strokeWidth,
            cap = StrokeCap.Round
        )
    }
}
