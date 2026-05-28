package com.integratedcaptureclipboard.android.ui.sync

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Computer
import androidx.compose.material.icons.filled.PhoneAndroid
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.integratedcaptureclipboard.android.data.model.DeviceInfo

/**
 * A composable card representing a paired or connected device.
 *
 * Displays the device name, type icon, online/offline status,
 * and a disconnect button if the device is currently connected.
 *
 * @param device The device info to display.
 * @param isOnline Whether the device is currently connected.
 * @param onDisconnect Callback invoked when the disconnect button is pressed.
 * @param modifier Optional modifier.
 */
@Composable
fun DeviceCard(
    device: DeviceInfo,
    isOnline: Boolean,
    onDisconnect: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = 12.dp, vertical = 4.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isOnline) {
                MaterialTheme.colorScheme.surfaceVariant
            } else {
                MaterialTheme.colorScheme.surface
            }
        ),
        elevation = CardDefaults.cardElevation(defaultElevation = if (isOnline) 2.dp else 1.dp)
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            // Device icon and info
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = if (device.deviceType == "android") {
                        Icons.Filled.PhoneAndroid
                    } else {
                        Icons.Filled.Computer
                    },
                    contentDescription = device.deviceType,
                    tint = if (isOnline) {
                        MaterialTheme.colorScheme.primary
                    } else {
                        MaterialTheme.colorScheme.outline
                    },
                    modifier = Modifier.size(28.dp)
                )

                Spacer(modifier = Modifier.width(12.dp))

                Column {
                    Text(
                        text = device.deviceName,
                        style = MaterialTheme.typography.bodyLarge,
                        color = MaterialTheme.colorScheme.onSurface
                    )

                    Row(
                        horizontalArrangement = Arrangement.spacedBy(8.dp)
                    ) {
                        // Online status indicator
                        Text(
                            text = if (isOnline) "在线" else "离线",
                            style = MaterialTheme.typography.labelSmall,
                            color = if (isOnline) {
                                MaterialTheme.colorScheme.primary
                            } else {
                                MaterialTheme.colorScheme.outline
                            }
                        )

                        // Platform info
                        if (device.platform.isNotEmpty()) {
                            Text(
                                text = device.platform,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline
                            )
                        }

                        // IP address
                        if (device.ipAddress.isNotEmpty()) {
                            Text(
                                text = device.ipAddress,
                                style = MaterialTheme.typography.labelSmall,
                                color = MaterialTheme.colorScheme.outline
                            )
                        }
                    }
                }
            }

            // Disconnect button (only shown when online)
            if (isOnline) {
                OutlinedButton(
                    onClick = onDisconnect,
                    content = { Text("断开") }
                )
            }
        }
    }
}
