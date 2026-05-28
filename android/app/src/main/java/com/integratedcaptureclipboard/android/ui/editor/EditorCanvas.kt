package com.integratedcaptureclipboard.android.ui.editor

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.gestures.detectDragGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.IntSize
import com.integratedcaptureclipboard.android.ui.editor.tools.ArrowTool
import com.integratedcaptureclipboard.android.ui.editor.tools.BrushTool
import com.integratedcaptureclipboard.android.ui.editor.tools.CropTool
import com.integratedcaptureclipboard.android.ui.editor.tools.MosaicTool
import com.integratedcaptureclipboard.android.ui.editor.tools.RectTool
import com.integratedcaptureclipboard.android.ui.editor.tools.TextTool

/**
 * Custom Compose Canvas for the image editor.
 *
 * Renders the source image, all committed editor actions, and
 * the current in-progress drawing preview. Handles touch/drag
 * input for all editor tools.
 *
 * @param sourceBitmap The original image bitmap being edited.
 * @param state The current editor state.
 * @param onAction Callback invoked when a drawing action is committed.
 * @param onStateUpdate Callback invoked when the editor state needs updating.
 * @param onTextPlacement Callback invoked when the user taps to place text.
 * @param modifier Optional modifier.
 */
@Composable
fun EditorCanvas(
    sourceBitmap: ImageBitmap?,
    state: EditorState,
    onAction: (EditorAction) -> Unit,
    onStateUpdate: (EditorState) -> Unit,
    onTextPlacement: (Offset) -> Unit,
    modifier: Modifier = Modifier
) {
    var dragStart by remember { mutableStateOf<Offset?>(null) }
    var currentDragPoint by remember { mutableStateOf<Offset?>(null) }
    var currentBrushPoints by remember { mutableStateOf<List<Offset>>(emptyList()) }

    Canvas(
        modifier = modifier
            .fillMaxSize()
            .pointerInput(state.currentTool) {
                when (state.currentTool) {
                    EditorTool.BRUSH -> {
                        detectDragGestures(
                            onDragStart = { offset ->
                                dragStart = offset
                                currentBrushPoints = listOf(offset)
                            },
                            onDrag = { change, _ ->
                                change.consume()
                                currentBrushPoints = currentBrushPoints + change.position
                            },
                            onDragEnd = {
                                if (currentBrushPoints.isNotEmpty()) {
                                    onAction(
                                        EditorAction.BrushStroke(
                                            points = currentBrushPoints,
                                            color = state.strokeColor,
                                            strokeWidth = state.strokeWidth
                                        )
                                    )
                                }
                                dragStart = null
                                currentBrushPoints = emptyList()
                            },
                            onDragCancel = {
                                dragStart = null
                                currentBrushPoints = emptyList()
                            }
                        )
                    }
                    EditorTool.TEXT -> {
                        detectTapGestures { offset ->
                            onTextPlacement(offset)
                        }
                    }
                    EditorTool.ARROW, EditorTool.RECT, EditorTool.MOSAIC, EditorTool.CROP -> {
                        detectDragGestures(
                            onDragStart = { offset ->
                                dragStart = offset
                                currentDragPoint = offset
                            },
                            onDrag = { change, _ ->
                                change.consume()
                                currentDragPoint = change.position
                            },
                            onDragEnd = {
                                val start = dragStart
                                val end = currentDragPoint
                                if (start != null && end != null) {
                                    when (state.currentTool) {
                                        EditorTool.ARROW -> {
                                            onAction(
                                                EditorAction.ArrowDraw(
                                                    start = start,
                                                    end = end,
                                                    color = state.strokeColor,
                                                    strokeWidth = state.strokeWidth
                                                )
                                            )
                                        }
                                        EditorTool.RECT -> {
                                            onAction(
                                                EditorAction.RectDraw(
                                                    topLeft = Offset(
                                                        minOf(start.x, end.x),
                                                        minOf(start.y, end.y)
                                                    ),
                                                    bottomRight = Offset(
                                                        maxOf(start.x, end.x),
                                                        maxOf(start.y, end.y)
                                                    ),
                                                    color = state.strokeColor,
                                                    strokeWidth = state.strokeWidth
                                                )
                                            )
                                        }
                                        EditorTool.MOSAIC -> {
                                            onAction(
                                                EditorAction.MosaicRegion(
                                                    topLeft = Offset(
                                                        minOf(start.x, end.x),
                                                        minOf(start.y, end.y)
                                                    ),
                                                    bottomRight = Offset(
                                                        maxOf(start.x, end.x),
                                                        maxOf(start.y, end.y)
                                                    ),
                                                    blockSize = state.mosaicBlockSize
                                                )
                                            )
                                        }
                                        EditorTool.CROP -> {
                                            onAction(
                                                EditorAction.CropAction(
                                                    cropRect = CropRect(
                                                        left = minOf(start.x, end.x).toInt(),
                                                        top = minOf(start.y, end.y).toInt(),
                                                        right = maxOf(start.x, end.x).toInt(),
                                                        bottom = maxOf(start.y, end.y).toInt()
                                                    )
                                                )
                                            )
                                        }
                                        else -> { /* no-op */ }
                                    }
                                }
                                dragStart = null
                                currentDragPoint = null
                            },
                            onDragCancel = {
                                dragStart = null
                                currentDragPoint = null
                            }
                        )
                    }
                }
            }
    ) {
        // Draw the source image
        sourceBitmap?.let {
            drawImage(it)
        }

        // Render all committed actions
        for (action in state.undoStack) {
            renderAction(this, action, sourceBitmap, size)
        }

        // Render current in-progress preview
        val start = dragStart
        val end = currentDragPoint

        when (state.currentTool) {
            EditorTool.BRUSH -> {
                if (currentBrushPoints.isNotEmpty()) {
                    BrushTool.renderPreview(
                        this,
                        currentBrushPoints,
                        state.strokeColor,
                        state.strokeWidth
                    )
                }
            }
            EditorTool.ARROW -> {
                if (start != null && end != null) {
                    ArrowTool.renderPreview(this, start, end, state.strokeColor, state.strokeWidth)
                }
            }
            EditorTool.RECT -> {
                if (start != null && end != null) {
                    RectTool.renderPreview(this, start, end, state.strokeColor, state.strokeWidth)
                }
            }
            EditorTool.MOSAIC -> {
                if (start != null && end != null) {
                    MosaicTool.renderPreview(this, start, end)
                }
            }
            EditorTool.CROP -> {
                if (start != null && end != null) {
                    CropTool.renderPreview(this, start, end, size.width, size.height)
                }
            }
            EditorTool.TEXT -> {
                state.pendingTextOffset?.let { pos ->
                    TextTool.renderPreview(this, pos, state.strokeColor)
                }
            }
        }
    }
}

/**
 * Render a single committed editor action on the canvas.
 */
private fun renderAction(
    drawScope: DrawScope,
    action: EditorAction,
    sourceBitmap: ImageBitmap?,
    canvasSize: androidx.compose.ui.geometry.Size
) {
    when (action) {
        is EditorAction.BrushStroke -> BrushTool.renderAction(drawScope, action)
        is EditorAction.TextAnnotation -> TextTool.renderAction(drawScope, action)
        is EditorAction.ArrowDraw -> ArrowTool.renderAction(drawScope, action)
        is EditorAction.RectDraw -> RectTool.renderAction(drawScope, action)
        is EditorAction.MosaicRegion -> MosaicTool.renderAction(drawScope, action, sourceBitmap)
        is EditorAction.CropAction -> CropTool.renderAction(
            drawScope, action, canvasSize.width, canvasSize.height
        )
    }
}
