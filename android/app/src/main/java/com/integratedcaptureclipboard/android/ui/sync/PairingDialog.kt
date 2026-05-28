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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.integratedcaptureclipboard.android.data.model.DeviceInfo
import com.integratedcaptureclipboard.android.data.model.PairingInfo
import com.integratedcaptureclipboard.android.sync.NsdDiscovery

/**
 * Pairing dialog for connecting to a new device.
 *
 * Supports two pairing methods:
 * 1. QR code scanning — the user scans a QR code displayed on the desktop app
 * 2. PIN code entry — the user enters a PIN shown on the desktop app
 *
 * @param discoveredDevices List of discovered devices available for pairing.
 * @param isPairing Whether a pairing operation is in progress.
 * @param onPairWithQr Callback invoked when the user submits a QR code content string.
 * @param onPairWithPin Callback invoked when the user submits a PIN code.
 * @param onPairWithDiscovered Callback invoked when the user selects a discovered device.
 * @param onDismiss Callback invoked when the dialog is dismissed.
 * @param modifier Optional modifier.
 */
@Composable
fun PairingDialog(
    discoveredDevices: List<NsdDiscovery.DiscoveredDevice>,
    isPairing: Boolean,
    onPairWithQr: (String) -> Unit,
    onPairWithPin: (String) -> Unit,
    onPairWithDiscovered: (NsdDiscovery.DiscoveredDevice) -> Unit,
    onDismiss: () -> Unit,
    modifier: Modifier = Modifier
) {
    var pairingMode by remember { mutableStateOf<PairingMode>(PairingMode.DISCOVER) }
    var qrText by remember { mutableStateOf("") }
    var pinCode by remember { mutableStateOf("") }

    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                when (pairingMode) {
                    PairingMode.DISCOVER -> "添加设备"
                    PairingMode.QR -> "扫码配对"
                    PairingMode.PIN -> "PIN 码配对"
                }
            )
        },
        text = {
            when (pairingMode) {
                PairingMode.DISCOVER -> {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Text(
                            text = "选择配对方式：",
                            style = MaterialTheme.typography.bodyMedium
                        )

                        // Discovered devices
                        if (discoveredDevices.isNotEmpty()) {
                            Text(
                                text = "发现的设备：",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.primary
                            )
                            discoveredDevices.forEach { device ->
                                DiscoveredDeviceItem(
                                    device = device,
                                    onConnect = { onPairWithDiscovered(device) }
                                )
                            }
                            Spacer(modifier = Modifier.height(4.dp))
                        } else {
                            Text(
                                text = "正在搜索附近设备...",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }

                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp)
                        ) {
                            OutlinedButton(
                                onClick = { pairingMode = PairingMode.QR },
                                modifier = Modifier.weight(1f)
                            ) {
                                Text("扫码配对")
                            }
                            OutlinedButton(
                                onClick = { pairingMode = PairingMode.PIN },
                                modifier = Modifier.weight(1f)
                            ) {
                                Text("PIN 配对")
                            }
                        }
                    }
                }
                PairingMode.QR -> {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Text(
                            text = "请输入扫描到的二维码内容（格式：icc://pair?...）",
                            style = MaterialTheme.typography.bodySmall
                        )
                        OutlinedTextField(
                            value = qrText,
                            onValueChange = { qrText = it },
                            label = { Text("二维码内容") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true
                        )
                    }
                }
                PairingMode.PIN -> {
                    Column(
                        modifier = Modifier.fillMaxWidth(),
                        verticalArrangement = Arrangement.spacedBy(12.dp)
                    ) {
                        Text(
                            text = "请输入桌面端显示的 6 位 PIN 码",
                            style = MaterialTheme.typography.bodySmall
                        )
                        OutlinedTextField(
                            value = pinCode,
                            onValueChange = {
                                if (it.length <= 6 && it.all { c -> c.isDigit() }) {
                                    pinCode = it
                                }
                            },
                            label = { Text("PIN 码") },
                            modifier = Modifier.fillMaxWidth(),
                            singleLine = true
                        )
                    }
                }
            }
        },
        confirmButton = {
            when (pairingMode) {
                PairingMode.DISCOVER -> {
                    TextButton(onClick = onDismiss) {
                        Text("关闭")
                    }
                }
                PairingMode.QR -> {
                    if (isPairing) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp))
                    } else {
                        Button(
                            onClick = { onPairWithQr(qrText) },
                            enabled = qrText.startsWith("icc://pair")
                        ) {
                            Text("配对")
                        }
                    }
                }
                PairingMode.PIN -> {
                    if (isPairing) {
                        CircularProgressIndicator(modifier = Modifier.size(24.dp))
                    } else {
                        Button(
                            onClick = { onPairWithPin(pinCode) },
                            enabled = pinCode.length == 6
                        ) {
                            Text("配对")
                        }
                    }
                }
            }
        },
        dismissButton = {
            if (pairingMode != PairingMode.DISCOVER) {
                TextButton(onClick = { pairingMode = PairingMode.DISCOVER }) {
                    Text("返回")
                }
            }
        },
        modifier = modifier
    )
}

/**
 * A row item for a discovered device in the pairing dialog.
 */
@Composable
private fun DiscoveredDeviceItem(
    device: NsdDiscovery.DiscoveredDevice,
    onConnect: () -> Unit
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = if (device.deviceType == "android") Icons.Filled.PhoneAndroid else Icons.Filled.Computer,
                contentDescription = null,
                modifier = Modifier.size(20.dp),
                tint = MaterialTheme.colorScheme.primary
            )
            Spacer(modifier = Modifier.width(8.dp))
            Text(
                text = device.deviceName.ifEmpty { device.serviceName },
                style = MaterialTheme.typography.bodyMedium
            )
        }
        OutlinedButton(onClick = onConnect) {
            Text("连接")
        }
    }
}

/**
 * Pairing mode enum for the dialog.
 */
private enum class PairingMode {
    DISCOVER,
    QR,
    PIN
}
