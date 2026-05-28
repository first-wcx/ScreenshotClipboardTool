package com.integratedcaptureclipboard.android.ui.clipboard

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.integratedcaptureclipboard.android.data.db.ClipboardItemEntity
import com.integratedcaptureclipboard.android.data.repository.ClipboardRepository
import com.integratedcaptureclipboard.android.sync.SyncManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

/**
 * UI state for the clipboard screen.
 */
data class ClipboardUiState(
    val items: List<ClipboardItemEntity> = emptyList(),
    val filteredItems: List<ClipboardItemEntity> = emptyList(),
    val searchQuery: String = "",
    val selectedType: String? = null,
    val isLoading: Boolean = true,
    val error: String? = null,
    val connectedDeviceCount: Int = 0
)

/**
 * ViewModel for the clipboard history screen.
 *
 * Collects clipboard items from Room via [ClipboardRepository],
 * supports search filtering, type filtering, and exposes sync
 * status information from [SyncManager].
 *
 * @property clipboardRepository Repository for clipboard item data.
 * @property syncManager Sync manager for connection status.
 */
@HiltViewModel
class ClipboardViewModel @Inject constructor(
    private val clipboardRepository: ClipboardRepository,
    private val syncManager: SyncManager
) : ViewModel() {

    private val _uiState = MutableStateFlow(ClipboardUiState())
    val uiState: StateFlow<ClipboardUiState> = _uiState.asStateFlow()

    init {
        loadItems()
        observeSyncStatus()
    }

    /**
     * Load all clipboard items from the repository.
     */
    private fun loadItems() {
        viewModelScope.launch {
            try {
                clipboardRepository.getAllItems().collect { items ->
                    _uiState.value = _uiState.value.copy(
                        items = items,
                        filteredItems = applyFilter(items),
                        isLoading = false
                    )
                }
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isLoading = false,
                    error = "加载剪贴板历史失败: ${e.message}"
                )
            }
        }
    }

    /**
     * Observe the sync manager's connected device count.
     */
    private fun observeSyncStatus() {
        viewModelScope.launch {
            syncManager.connectedDevices.collect { devices ->
                _uiState.value = _uiState.value.copy(
                    connectedDeviceCount = devices.size
                )
            }
        }
    }

    /**
     * Update the search query and re-filter items.
     *
     * @param query The new search query string.
     */
    fun updateSearchQuery(query: String) {
        _uiState.value = _uiState.value.copy(
            searchQuery = query,
            filteredItems = applyFilter(_uiState.value.items, query, _uiState.value.selectedType)
        )
    }

    /**
     * Set the type filter (null for all types).
     *
     * @param type The type to filter by ("text", "image", "files"), or null for all.
     */
    fun setFilterType(type: String?) {
        _uiState.value = _uiState.value.copy(
            selectedType = type,
            filteredItems = applyFilter(_uiState.value.items, _uiState.value.searchQuery, type)
        )
    }

    /**
     * Delete a clipboard item by its ID.
     *
     * @param id The ID of the item to delete.
     */
    fun deleteItem(id: Long) {
        viewModelScope.launch {
            clipboardRepository.deleteItemById(id)
        }
    }

    /**
     * Delete all clipboard items.
     */
    fun deleteAllItems() {
        viewModelScope.launch {
            clipboardRepository.deleteAllItems()
        }
    }

    /**
     * Search clipboard items using the repository's search function.
     *
     * @param query The search query.
     */
    fun searchItems(query: String) {
        if (query.isBlank()) {
            updateSearchQuery(query)
            return
        }
        viewModelScope.launch {
            try {
                val results = clipboardRepository.searchItems(query)
                _uiState.value = _uiState.value.copy(
                    filteredItems = results
                )
            } catch (e: Exception) {
                // Fall back to local filtering
                updateSearchQuery(query)
            }
        }
    }

    /**
     * Apply search query and type filter to the item list.
     */
    private fun applyFilter(
        items: List<ClipboardItemEntity>,
        query: String = _uiState.value.searchQuery,
        type: String? = _uiState.value.selectedType
    ): List<ClipboardItemEntity> {
        var filtered = items

        // Type filter
        if (type != null) {
            filtered = filtered.filter { it.type == type }
        }

        // Search filter
        if (query.isNotBlank()) {
            val lowerQuery = query.lowercase()
            filtered = filtered.filter { item ->
                item.text?.lowercase()?.contains(lowerQuery) == true ||
                        item.preview.lowercase().contains(lowerQuery) ||
                        item.time.lowercase().contains(lowerQuery)
            }
        }

        return filtered
    }

    /**
     * Clear any error state.
     */
    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }
}
