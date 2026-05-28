package com.integratedcaptureclipboard.android.ui.clipboard

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextFieldDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * A reusable search bar composable with a search icon and hint text.
 *
 * @param query The current search query text.
 * @param onQueryChange Callback invoked when the query text changes.
 * @param placeholder Optional placeholder text (default: "搜索...").
 * @param modifier Optional modifier.
 */
@Composable
fun SearchBar(
    query: String,
    onQueryChange: (String) -> Unit,
    placeholder: String = "搜索...",
    modifier: Modifier = Modifier
) {
    OutlinedTextField(
        value = query,
        onValueChange = onQueryChange,
        modifier = modifier.fillMaxWidth(),
        placeholder = { Text(placeholder) },
        leadingIcon = {
            Icon(
                imageVector = Icons.Filled.Search,
                contentDescription = "搜索"
            )
        },
        singleLine = true,
        shape = RoundedCornerShape(12.dp),
        colors = TextFieldDefaults.colors(
            unfocusedContainerColor = androidx.compose.material3.MaterialTheme.colorScheme.surfaceVariant,
            focusedContainerColor = androidx.compose.material3.MaterialTheme.colorScheme.surfaceVariant
        )
    )
}
