package com.integratedcaptureclipboard.android.ui.editor

import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.IntSize

/**
 * Manages the state of the image editor, including the current tool,
 * drawing parameters, and undo/redo stacks.
 *
 * @property currentTool The currently selected editing tool.
 * @property strokeColor The current drawing color.
 * @property strokeWidth The current stroke width in pixels.
 * @property mosaicBlockSize The block size for mosaic pixelation.
 */
data class EditorState(
    val currentTool: EditorTool = EditorTool.BRUSH,
    val strokeColor: Color = Color.Red,
    val strokeWidth: Float = 4f,
    val mosaicBlockSize: Int = 16,
    val canvasSize: IntSize = IntSize.Zero,
    val undoStack: List<EditorAction> = emptyList(),
    val redoStack: List<EditorAction> = emptyList(),
    val isCropMode: Boolean = false,
    val cropRect: CropRect? = null,
    val pendingTextOffset: Offset? = null
) {
    /** Whether undo is available. */
    val canUndo: Boolean get() = undoStack.isNotEmpty()

    /** Whether redo is available. */
    val canRedo: Boolean get() = redoStack.isNotEmpty()

    /**
     * Apply an editor action, pushing it onto the undo stack
     * and clearing the redo stack.
     */
    fun pushAction(action: EditorAction): EditorState {
        return copy(
            undoStack = undoStack + action,
            redoStack = emptyList()
        )
    }

    /** Undo the last action, moving it to the redo stack. */
    fun undo(): EditorState {
        if (undoStack.isEmpty()) return this
        val last = undoStack.last()
        return copy(
            undoStack = undoStack.dropLast(1),
            redoStack = redoStack + last
        )
    }

    /** Redo the last undone action, moving it back to the undo stack. */
    fun redo(): EditorState {
        if (redoStack.isEmpty()) return this
        val last = redoStack.last()
        return copy(
            undoStack = undoStack + last,
            redoStack = redoStack.dropLast(1)
        )
    }
}

/**
 * Represents a single editing action that can be rendered on the canvas.
 */
sealed class EditorAction {
    /** A freehand brush stroke. */
    data class BrushStroke(
        val points: List<Offset>,
        val color: Color,
        val strokeWidth: Float
    ) : EditorAction()

    /** A text annotation at a specific position. */
    data class TextAnnotation(
        val text: String,
        val position: Offset,
        val color: Color,
        val fontSize: Float = 24f
    ) : EditorAction()

    /** An arrow drawn between two points. */
    data class ArrowDraw(
        val start: Offset,
        val end: Offset,
        val color: Color,
        val strokeWidth: Float
    ) : EditorAction()

    /** A rectangle drawn between two corner points. */
    data class RectDraw(
        val topLeft: Offset,
        val bottomRight: Offset,
        val color: Color,
        val strokeWidth: Float
    ) : EditorAction()

    /** A mosaic region defined by a bounding rectangle. */
    data class MosaicRegion(
        val topLeft: Offset,
        val bottomRight: Offset,
        val blockSize: Int
    ) : EditorAction()

    /** A crop operation. */
    data class CropAction(
        val cropRect: CropRect
    ) : EditorAction()
}

/**
 * Defines a rectangular crop region.
 */
data class CropRect(
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int
) {
    val width: Int get() = right - left
    val height: Int get() = bottom - top
    val isValid: Boolean get() = width > 0 && height > 0
}
