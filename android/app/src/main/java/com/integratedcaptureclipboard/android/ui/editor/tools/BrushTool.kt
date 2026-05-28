package com.integratedcaptureclipboard.android.ui.editor.tools

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.StrokeJoin
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import com.integratedcaptureclipboard.android.ui.editor.EditorAction

/**
 * Brush tool implementation for the image editor.
 *
 * Handles freehand drawing with configurable color and stroke width.
 * Collects touch points into a path, then renders the path as a
 * continuous stroke on the canvas.
 */
object BrushTool {

    /**
     * Render a brush stroke action on the canvas.
     *
     * @param drawScope The drawing scope.
     * @param action The brush stroke action to render.
     */
    fun renderAction(drawScope: DrawScope, action: EditorAction.BrushStroke) {
        if (action.points.size < 2) return

        val path = Path().apply {
            moveTo(action.points[0].x, action.points[0].y)
            for (i in 1 until action.points.size) {
                val prev = action.points[i - 1]
                val curr = action.points[i]
                // Smooth curve using quadratic bezier
                val midX = (prev.x + curr.x) / 2f
                val midY = (prev.y + curr.y) / 2f
                quadraticBezierTo(prev.x, prev.y, midX, midY)
            }
            // Connect to last point
            val last = action.points.last()
            lineTo(last.x, last.y)
        }

        drawScope.drawPath(
            path = path,
            color = action.color,
            style = Stroke(
                width = action.strokeWidth,
                cap = StrokeCap.Round,
                join = StrokeJoin.Round
            )
        )
    }

    /**
     * Render a preview stroke (while the user is currently drawing).
     *
     * @param drawScope The drawing scope.
     * @param points The current list of touch points.
     * @param color The stroke color.
     * @param strokeWidth The stroke width.
     */
    fun renderPreview(
        drawScope: DrawScope,
        points: List<Offset>,
        color: Color,
        strokeWidth: Float
    ) {
        if (points.size < 2) {
            // Draw a dot for single-point press
            if (points.size == 1) {
                drawScope.drawCircle(
                    color = color,
                    radius = strokeWidth / 2f,
                    center = points[0]
                )
            }
            return
        }

        val path = Path().apply {
            moveTo(points[0].x, points[0].y)
            for (i in 1 until points.size) {
                val prev = points[i - 1]
                val curr = points[i]
                val midX = (prev.x + curr.x) / 2f
                val midY = (prev.y + curr.y) / 2f
                quadraticBezierTo(prev.x, prev.y, midX, midY)
            }
            val last = points.last()
            lineTo(last.x, last.y)
        }

        drawScope.drawPath(
            path = path,
            color = color,
            style = Stroke(
                width = strokeWidth,
                cap = StrokeCap.Round,
                join = StrokeJoin.Round
            )
        )
    }
}
