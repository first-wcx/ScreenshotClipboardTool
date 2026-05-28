package com.integratedcaptureclipboard.android.ui.clipboard

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.integratedcaptureclipboard.android.clipboard.ClipboardHelper

/**
 * Clipboard history screen.
 *
 * Displays a searchable, filterable list of clipboard history items.
 * Supports:
 * - Search bar for text filtering
 * - Type filter chips (all, text, image, files)
 * - Tap to copy item back to clipboard
 * - Long-press to delete
 * - Sync status indicator
 *
 * @param viewModel The clipboard ViewModel.
 * @param modifier Optional modifier.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ClipboardScreen(
    viewModel: ClipboardViewModel = hiltViewModel(),
    modifier: Modifier = Modifier
) {
    val uiState by viewModel.uiState.collectAsState()
    val context = LocalContext.current
    val clipboardHelper = remember { ClipboardHelper(context) }
    var showDeleteAllDialog by remember { mutableStateOf(false) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("剪贴板历史") },
                actions = {
                    // Sync status indicator
                    if (uiState.connectedDeviceCount > 0) {
                        IconButton(onClick = { /* Navigate to sync tab */ }) {
                            Icon(
                                Icons.Filled.Sync,
                                contentDescription = "同步中",
                                tint = MaterialTheme.colorScheme.primary
                            )
                        }
                    }
                    IconButton(onClick = { showDeleteAllDialog = true }) {
                        Icon(Icons.Filled.Delete, contentDescription = "清空")
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
            // Search bar
            SearchBar(
                query = uiState.searchQuery,
                onQueryChange = { query ->
                    viewModel.updateSearchQuery(query)
                    if (query.isNotBlank()) {
                        viewModel.searchItems(query)
                    }
                },
                modifier = Modifier.padding(horizontal = 12.dp, vertical = 8.dp)
            )

            // Type filter chips
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 12.dp, vertical = 4.dp),
                horizontalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                FilterChip(
                    selected = uiState.selectedType == null,
                    onClick = { viewModel.setFilterType(null) },
                    label = { Text("全部") }
                )
                FilterChip(
                    selected = uiState.selectedType == "text",
                    onClick = { viewModel.setFilterType("text") },
                    label = { Text("文本") }
                )
                FilterChip(
                    selected = uiState.selectedType == "image",
                    onClick = { viewModel.setFilterType("image") },
                    label = { Text("图片") }
                )
                FilterChip(
                    selected = uiState.selectedType == "files",
                    onClick = { viewModel.setFilterType("files") },
                    label = { Text("文件") }
                )
            }

            Spacer(modifier = Modifier.height(4.dp))

            // Content area
            when {
                uiState.isLoading -> {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        CircularProgressIndicator()
                    }
                }
                uiState.error != null -> {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Column(horizontalAlignment = Alignment.CenterHorizontally) {
                            Text(
                                text = uiState.error ?: "未知错误",
                                style = MaterialTheme.typography.bodyLarge,
                                color = MaterialTheme.colorScheme.error
                            )
                            Spacer(modifier = Modifier.height(8.dp))
                            TextButton(onClick = { viewModel.clearError() }) {
                                Text("重试")
                            }
                        }
                    }
                }
                uiState.filteredItems.isEmpty() -> {
                    Box(
                        modifier = Modifier.fillMaxSize(),
                        contentAlignment = Alignment.Center
                    ) {
                        Text(
                            text = if (uiState.searchQuery.isNotBlank()) "没有找到匹配的记录" else "暂无剪贴板记录\n\n复制内容后会自动记录",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                else -> {
                    LazyColumn(
                        modifier = Modifier.fillMaxSize(),
                        verticalArrangement = Arrangement.spacedBy(0.dp)
                    ) {
                        items(
                            items = uiState.filteredItems,
                            key = { it.id }
                        ) { item ->
                            ClipboardItemCard(
                                item = item,
                                onCopy = {
                                    // Copy item text to system clipboard
                                    if (item.type == "text" && !item.text.isNullOrEmpty()) {
                                        clipboardHelper.writeText(item.text)
                                    }
                                },
                                onDelete = {
                                    viewModel.deleteItem(item.id)
                                }
                            )
                        }
                    }
                }
            }
        }
    }

    // Delete all confirmation dialog
    if (showDeleteAllDialog) {
        AlertDialog(
            onDismissRequest = { showDeleteAllDialog = false },
            title = { Text("清空历史") },
            text = { Text("确定要清空所有剪贴板历史记录吗？此操作不可撤销。") },
            confirmButton = {
                TextButton(
                    onClick = {
                        viewModel.deleteAllItems()
                        showDeleteAllDialog = false
                    }
                ) {
                    Text("清空")
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteAllDialog = false }) {
                    Text("取消")
                }
            }
        )
    }
}
