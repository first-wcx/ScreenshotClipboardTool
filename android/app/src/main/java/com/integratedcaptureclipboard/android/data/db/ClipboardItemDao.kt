package com.integratedcaptureclipboard.android.data.db

import androidx.room.Dao
import androidx.room.Delete
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

/**
 * Data Access Object for [ClipboardItemEntity].
 * Provides CRUD operations and queries for clipboard history items.
 */
@Dao
interface ClipboardItemDao {

    /**
     * Query all clipboard items ordered by time descending (newest first).
     */
    @Query("SELECT * FROM clipboard_items ORDER BY time DESC")
    suspend fun getAll(): List<ClipboardItemEntity>

    /**
     * Query clipboard items filtered by type, ordered by time descending.
     *
     * @param type The item type to filter by ("text", "image", or "files").
     */
    @Query("SELECT * FROM clipboard_items WHERE type = :type ORDER BY time DESC")
    suspend fun getByType(type: String): List<ClipboardItemEntity>

    /**
     * Find a clipboard item by its digest string.
     * Used for deduplication — if a matching digest exists, skip insertion.
     *
     * @param digest The digest string to search for.
     * @return The matching entity, or null if not found.
     */
    @Query("SELECT * FROM clipboard_items WHERE digest = :digest LIMIT 1")
    suspend fun getByDigest(digest: String): ClipboardItemEntity?

    /**
     * Search clipboard items by text content, ordered by time descending.
     * Uses LIKE for partial matching.
     *
     * @param query The search query string.
     */
    @Query("SELECT * FROM clipboard_items WHERE text LIKE '%' || :query || '%' OR preview LIKE '%' || :query || '%' ORDER BY time DESC")
    suspend fun search(query: String): List<ClipboardItemEntity>

    /**
     * Insert a clipboard item. If a conflict occurs on the primary key,
     * replace the existing entry.
     *
     * @param item The clipboard item entity to insert.
     * @return The row ID of the inserted item.
     */
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(item: ClipboardItemEntity): Long

    /**
     * Delete a specific clipboard item.
     *
     * @param item The clipboard item entity to delete.
     */
    @Delete
    suspend fun delete(item: ClipboardItemEntity)

    /**
     * Delete a clipboard item by its ID.
     *
     * @param id The ID of the clipboard item to delete.
     */
    @Query("DELETE FROM clipboard_items WHERE id = :id")
    suspend fun deleteById(id: Long)

    /**
     * Delete all clipboard items.
     */
    @Query("DELETE FROM clipboard_items")
    suspend fun deleteAll()

    /**
     * Count the total number of clipboard items.
     */
    @Query("SELECT COUNT(*) FROM clipboard_items")
    suspend fun count(): Int
}
