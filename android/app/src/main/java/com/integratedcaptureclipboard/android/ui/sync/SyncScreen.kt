package com.integratedcaptureclipboard.android.ui.sync

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.integratedcaptureclipboard.android.data.model.DeviceInfo

/**
 * Sync management screen.
 *
 * Displays:
 * - Sync enable/disable toggle
 * - Paired devices list with online/offline status
 * - Discovered devices (nearby devices available for pairing)
 * - Pairing dialog for adding new devices
 *
 * @param viewModel The sync ViewModel.
 * @param modifier Optional modifier.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SyncScreen(
    viewModel: SyncViewModel = hiltViewModel(),
    modifier: Modifier = Modifier
) {
    val uiState by viewModel.uiState.collectAsState()

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("同步管理") }
            )
        },
        floatingActionButton = {
            if (uiState.isSyncEnabled) {
                FloatingActionButton(
                    onClick = { viewModel.showPairingDialog() }
                ) {
                    Icon(Icons.Filled.Add, contentDescription = "添加设备")
                }
            }
        },
        modifier = modifier
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
        ) {
            // Sync toggle
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 8.dp),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column {
                    Text(
                        text = "同步功能",
                        style = MaterialTheme.typography.bodyLarge
                    )
                    Text(
                        text = if (uiState.isSyncEnabled) "已启用" else "未启用",
                        style = MaterialTheme.typography.labelSmall,
                        color = if (uiState.isSyncEnabled) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.outline
                        }
                    )
                }
                Switch(
                    checked = uiState.isSyncEnabled,
                    onCheckedChange = { enabled ->
                        if (enabled) viewModel.enableSync() else viewModel.disableSync()
                    }
                )
            }

            // Connection status
            if (uiState.isSyncEnabled) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(horizontal = 16.dp, vertical = 4.dp),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = "已连接设备: ${uiState.connectedDeviceIds.size}",
                        style = MaterialTheme.typography.bodyMedium
                    )
                    if (uiState.isDiscovering) {
                        Text(
                            text = "正在搜索...",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.primary
                        )
                    }
                }
            }

            Spacer(modifier = Modifier.height(8.dp))

            if (!uiState.isSyncEnabled) {
                // Sync disabled state
                Box(
                    modifier = Modifier.fillMaxSize(),
                    contentAlignment = Alignment.Center
                ) {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(
                            text = "同步功能未启用",
                            style = MaterialTheme.typography.bodyLarge,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = "启用后可在局域网内同步剪贴板内容",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.outline
                        )
                    }
                }
            } else {
                // Paired devices section
                Text(
                    text = "已配对设备",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                )

                if (uiState.pairedDevices.isEmpty()) {
                    Text(
                        text = "暂无配对设备，点击右下角 + 添加",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.outline,
                        modifier = Modifier.padding(horizontal = 16.dp)
                    )
                } else {
                    LazyColumn(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(0.dp)
                    ) {
                        items(
                            items = uiState.pairedDevices,
                            key = { it.deviceId }
                        ) { device ->
                            DeviceCard(
                                device = device,
                                isOnline = device.deviceId in uiState.connectedDeviceIds,
                                onDisconnect = { viewModel.disconnectDevice(device.deviceId) }
                            )
                        }
                    }
                }

                // Discovered devices section
                if (uiState.discoveredDevices.isNotEmpty()) {
                    Spacer(modifier = Modifier.height(16.dp))
                    Text(
                        text = "附近设备",
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp)
                    )

                    LazyColumn(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(0.dp)
                    ) {
                        items(
                            items = uiState.discoveredDevices,
                            key = { it.host + it.port }
                        ) { device ->
                            DeviceCard(
                                device = DeviceInfo(
                                    deviceId = device.deviceId,
                                    deviceName = device.deviceName.ifEmpty { device.serviceName },
                                    deviceType = device.deviceType,
                                    ipAddress = device.host,
                                    port = device.port,
                                    platform = device.platform,
                                    pairedAt = "",
                                    lastSeen = ""
                                ),
                                isOnline = false,
                                onDisconnect = { viewModel.connectToDiscoveredDevice(device) }
                            )
                        }
                    }
                }
            }
        }
    }

    // Pairing dialog
    if (uiState.showPairingDialog) {
        PairingDialog(
            discoveredDevices = uiState.discoveredDevices,
            isPairing = uiState.isPairing,
            onPairWithQr = { qrText ->
                viewModel.pairWithQr(qrText)
            },
            onPairWithPin = { pin ->
                viewModel.pairWithPin(pin)
            },
            onPairWithDiscovered = { device ->
                viewModel.connectToDiscoveredDevice(device)
                viewModel.hidePairingDialog()
            },
            onDismiss = { viewModel.hidePairingDialog() }
        )
    }
}
