package com.integratedcaptureclipboard.android.data.repository

import com.integratedcaptureclipboard.android.data.db.ClipboardItemDao
import com.integratedcaptureclipboard.android.data.db.ClipboardItemEntity
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Repository for clipboard history data.
 * Encapsulates [ClipboardItemDao] operations and provides
 * a clean API for the ViewModel layer.
 */
@Singleton
class ClipboardRepository @Inject constructor(
    private val clipboardItemDao: ClipboardItemDao
) {

    /**
     * Get all clipboard items as a Flow, ordered by time descending.
     */
    fun getAllItems(): Flow<List<ClipboardItemEntity>> = flow {
        emit(clipboardItemDao.getAll())
    }

    /**
     * Get clipboard items filtered by type as a Flow.
     *
     * @param type The item type to filter by ("text", "image", or "files").
     */
    fun getItemsByType(type: String): Flow<List<ClipboardItemEntity>> = flow {
        emit(clipboardItemDao.getByType(type))
    }

    /**
     * Find a clipboard item by its digest for deduplication.
     *
     * @param digest The digest string to search for.
     * @return The matching entity, or null if not found.
     */
    suspend fun getItemByDigest(digest: String): ClipboardItemEntity? {
        return clipboardItemDao.getByDigest(digest)
    }

    /**
     * Search clipboard items by text content.
     *
     * @param query The search query string.
     * @return List of matching clipboard items.
     */
    suspend fun searchItems(query: String): List<ClipboardItemEntity> {
        return clipboardItemDao.search(query)
    }

    /**
     * Insert a clipboard item. Before insertion, checks for duplicate digest
     * to prevent duplicate entries.
     *
     * @param item The clipboard item to insert.
     * @return The row ID of the inserted item, or -1 if duplicate was found.
     */
    suspend fun insertItem(item: ClipboardItemEntity): Long {
        // Deduplication: skip if digest already exists
        if (item.digest.isNotEmpty()) {
            val existing = clipboardItemDao.getByDigest(item.digest)
            if (existing != null) {
                return -1L
            }
        }
        return clipboardItemDao.insert(item)
    }

    /**
     * Delete a specific clipboard item.
     *
     * @param item The clipboard item to delete.
     */
    suspend fun deleteItem(item: ClipboardItemEntity) {
        clipboardItemDao.delete(item)
    }

    /**
     * Delete a clipboard item by its ID.
     *
     * @param id The ID of the clipboard item to delete.
     */
    suspend fun deleteItemById(id: Long) {
        clipboardItemDao.deleteById(id)
    }

    /**
     * Delete all clipboard items.
     */
    suspend fun deleteAllItems() {
        clipboardItemDao.deleteAll()
    }

    /**
     * Get the total count of clipboard items.
     */
    suspend fun getItemCount(): Int {
        return clipboardItemDao.count()
    }
}
