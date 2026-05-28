package com.integratedcaptureclipboard.android.ui.editor

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Redo
import androidx.compose.material.icons.filled.Save
import androidx.compose.material.icons.filled.Undo
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Slider
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import com.integratedcaptureclipboard.android.screenshot.ImageSaver
import java.io.File

/**
 * Image editor screen.
 *
 * Provides a toolbar with editing tools, color picker, stroke width
 * slider, and an [EditorCanvas] for drawing on the image.
 *
 * @param imagePath The path of the image to edit.
 * @param onBack Callback invoked when the user navigates back.
 * @param modifier Optional modifier.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ImageEditorScreen(
    imagePath: String,
    onBack: () -> Unit,
    modifier: Modifier = Modifier
) {
    val context = LocalContext.current
    val imageSaver = remember { ImageSaver(context) }

    // Load the image bitmap
    var sourceBitmap by remember {
        mutableStateOf<ImageBitmap?>(null)
    }

    // Editor state
    var editorState by remember { mutableStateOf(EditorState()) }
    var showTextDialog by remember { mutableStateOf(false) }
    var textInput by remember { mutableStateOf("") }

    // Load image on first composition
    remember(imagePath) {
        try {
            val file = File(imagePath)
            if (file.exists()) {
                val options = android.graphics.BitmapFactory.Options().apply {
                    inPreferredConfig = android.graphics.Bitmap.Config.ARGB_8888
                }
                val bitmap = android.graphics.BitmapFactory.decodeFile(imagePath, options)
                sourceBitmap = bitmap?.asImageBitmap()
            }
        } catch (e: Exception) {
            // Image loading failed
        }
        true
    }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("图片编辑") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    // Undo
                    IconButton(
                        onClick = { editorState = editorState.undo() },
                        enabled = editorState.canUndo
                    ) {
                        Icon(Icons.Filled.Undo, contentDescription = "撤销")
                    }
                    // Redo
                    IconButton(
                        onClick = { editorState = editorState.redo() },
                        enabled = editorState.canRedo
                    ) {
                        Icon(Icons.Filled.Redo, contentDescription = "重做")
                    }
                    // Save
                    IconButton(
                        onClick = {
                            sourceBitmap?.let { bitmap ->
                                // Apply all actions and save
                                val resultBitmap = applyActionsToBitmap(
                                    bitmap.asAndroidBitmap(),
                                    editorState.undoStack
                                )
                                imageSaver.saveToPrivateDir(resultBitmap)
                            }
                        }
                    ) {
                        Icon(Icons.Filled.Save, contentDescription = "保存")
                    }
                }
            )
        },
        modifier = modifier
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // Tool selection row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .horizontalScroll(rememberScrollState())
                    .padding(horizontal = 8.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                EditorTool.entries.forEach { tool ->
                    TextButton(
                        onClick = {
                            editorState = editorState.copy(currentTool = tool)
                        },
                        modifier = Modifier.padding(horizontal = 4.dp)
                    ) {
                        Text(
                            text = tool.displayName,
                            color = if (editorState.currentTool == tool) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.onSurface
                            }
                        )
                    }
                }
            }

            // Color picker row
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("颜色", style = MaterialTheme.typography.labelMedium)
                val colors = listOf(Color.Red, Color.Blue, Color.Green, Color.Yellow, Color.White, Color.Black)
                colors.forEach { color ->
                    Box(
                        modifier = Modifier
                            .size(28.dp)
                            .clip(CircleShape)
                            .background(color)
                            .border(
                                width = if (editorState.strokeColor == color) 2.dp else 1.dp,
                                color = if (editorState.strokeColor == color) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.outline
                                },
                                shape = CircleShape
                            )
                            .clickable {
                                editorState = editorState.copy(strokeColor = color)
                            }
                    )
                }
            }

            // Stroke width slider
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text("粗细", style = MaterialTheme.typography.labelMedium)
                Spacer(modifier = Modifier.width(8.dp))
                Slider(
                    value = editorState.strokeWidth,
                    onValueChange = { editorState = editorState.copy(strokeWidth = it) },
                    valueRange = 1f..30f,
                    modifier = Modifier.weight(1f)
                )
                Text(
                    text = "${editorState.strokeWidth.toInt()}",
                    style = MaterialTheme.typography.labelSmall
                )
            }

            Spacer(modifier = Modifier.height(4.dp))

            // Canvas area
            EditorCanvas(
                sourceBitmap = sourceBitmap,
                state = editorState,
                onAction = { action ->
                    editorState = editorState.pushAction(action)
                },
                onStateUpdate = { editorState = it },
                onTextPlacement = { offset ->
                    editorState = editorState.copy(pendingTextOffset = offset)
                    showTextDialog = true
                },
                modifier = Modifier
                    .fillMaxWidth()
                    .weight(1f)
            )
        }
    }

    // Text input dialog
    if (showTextDialog) {
        AlertDialog(
            onDismissRequest = {
                showTextDialog = false
                editorState = editorState.copy(pendingTextOffset = null)
            },
            title = { Text("输入文字") },
            text = {
                OutlinedTextField(
                    value = textInput,
                    onValueChange = { textInput = it },
                    label = { Text("文字内容") },
                    singleLine = true
                )
            },
            confirmButton = {
                TextButton(
                    onClick = {
                        val offset = editorState.pendingTextOffset
                        if (offset != null && textInput.isNotBlank()) {
                            editorState = editorState.pushAction(
                                EditorAction.TextAnnotation(
                                    text = textInput,
                                    position = offset,
                                    color = editorState.strokeColor,
                                    fontSize = 24f
                                )
                            )
                        }
                        textInput = ""
                        showTextDialog = false
                        editorState = editorState.copy(pendingTextOffset = null)
                    }
                ) {
                    Text("确认")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = {
                        textInput = ""
                        showTextDialog = false
                        editorState = editorState.copy(pendingTextOffset = null)
                    }
                ) {
                    Text("取消")
                }
            }
        )
    }
}

/**
 * Apply all editor actions to a source bitmap and return the result.
 */
private fun applyActionsToBitmap(
    source: android.graphics.Bitmap,
    actions: List<EditorAction>
): android.graphics.Bitmap {
    var result = source.copy(android.graphics.Bitmap.Config.ARGB_8888, true) ?: return source

    for (action in actions) {
        when (action) {
            is EditorAction.MosaicRegion -> {
                val offset = androidx.compose.ui.geometry.Offset(action.topLeft.x, action.topLeft.y)
                val offset2 = androidx.compose.ui.geometry.Offset(action.bottomRight.x, action.bottomRight.y)
                result = com.integratedcaptureclipboard.android.ui.editor.tools.MosaicTool.applyMosaicActions(
                    result, listOf(action.copy(topLeft = offset, bottomRight = offset2))
                )
            }
            is EditorAction.CropAction -> {
                result = com.integratedcaptureclipboard.android.ui.editor.tools.CropTool.applyCrop(result, action.cropRect)
            }
            else -> {
                // Brush, text, arrow, rect are rendered via Canvas, not bitmap manipulation
                // They will be applied during the final render pass
            }
        }
    }

    return result
}
