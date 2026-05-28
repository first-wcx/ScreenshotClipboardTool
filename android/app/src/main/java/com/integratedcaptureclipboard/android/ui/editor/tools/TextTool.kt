package com.integratedcaptureclipboard.android.ui.editor.tools

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.graphics.drawscope.DrawScope
import com.integratedcaptureclipboard.android.ui.editor.EditorAction

/**
 * Text tool implementation for the image editor.
 *
 * Handles placing text annotations at a specific position on the canvas.
 * The user taps a location, enters text via a dialog, and the text
 * is rendered at that position.
 */
object TextTool {

    /**
     * Render a text annotation action on the canvas.
     *
     * @param drawScope The drawing scope.
     * @param action The text annotation action to render.
     */
    fun renderAction(drawScope: DrawScope, action: EditorAction.TextAnnotation) {
        drawScope.drawContext.canvas.nativeCanvas.apply {
            val paint = android.graphics.Paint().apply {
                this.color = action.color.toArgb()
                textSize = action.fontSize * drawScope.density
                isAntiAlias = true
                typeface = android.graphics.Typeface.DEFAULT_BOLD
            }
            drawText(
                action.text,
                action.position.x * drawScope.density,
                action.position.y * drawScope.density,
                paint
            )
        }
    }

    /**
     * Render a preview text placeholder (while the user is entering text).
     *
     * @param drawScope The drawing scope.
     * @param position The tap position for the text.
     * @param color The text color.
     */
    fun renderPreview(
        drawScope: DrawScope,
        position: Offset,
        color: Color
    ) {
        // Draw a small cursor indicator at the tap position
        drawScope.drawLine(
            color = color,
            start = position,
            end = Offset(position.x, position.y - 20f),
            strokeWidth = 2f
        )
    }
}
