package com.integratedcaptureclipboard.android.ui.editor

/**
 * Defines the available editing tools in the image editor.
 *
 * Each tool corresponds to a specific drawing or annotation action
 * that can be performed on the editor canvas.
 */
enum class EditorTool(
    val displayName: String,
    val icon: String
) {
    /** Free-draw brush with configurable color and stroke width. */
    BRUSH("画笔", "brush"),

    /** Text annotation tool — tap to place, type to enter. */
    TEXT("文字", "text"),

    /** Arrow tool — drag to draw a directional arrow. */
    ARROW("箭头", "arrow"),

    /** Rectangle tool — drag to draw a rectangular frame. */
    RECT("矩形", "rect"),

    /** Mosaic / pixelation tool — drag over an area to pixelate. */
    MOSAIC("马赛克", "mosaic"),

    /** Crop tool — drag to select a region, confirm to crop. */
    CROP("裁剪", "crop")
}
