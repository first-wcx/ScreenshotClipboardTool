package com.integratedcaptureclipboard.android.ui.sync

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.integratedcaptureclipboard.android.data.model.DeviceInfo
import com.integratedcaptureclipboard.android.data.model.PairingInfo
import com.integratedcaptureclipboard.android.data.repository.DeviceRepository
import com.integratedcaptureclipboard.android.sync.NsdDiscovery
import com.integratedcaptureclipboard.android.sync.SyncConfig
import com.integratedcaptureclipboard.android.sync.SyncManager
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.format.DateTimeFormatter
import javax.inject.Inject

/**
 * UI state for the sync management screen.
 */
data class SyncUiState(
    val pairedDevices: List<DeviceInfo> = emptyList(),
    val connectedDeviceIds: Set<String> = emptySet(),
    val discoveredDevices: List<NsdDiscovery.DiscoveredDevice> = emptyList(),
    val isDiscovering: Boolean = false,
    val isPairing: Boolean = false,
    val isSyncEnabled: Boolean = false,
    val showPairingDialog: Boolean = false,
    val pairingError: String? = null,
    val error: String? = null
)

/**
 * ViewModel for the sync management screen.
 *
 * Manages device pairing, discovery, and connection state
 * using [SyncManager] and [DeviceRepository].
 *
 * @property syncManager The sync manager for device connections.
 * @property deviceRepository Repository for paired device data.
 */
@HiltViewModel
class SyncViewModel @Inject constructor(
    private val syncManager: SyncManager,
    private val deviceRepository: DeviceRepository
) : ViewModel() {

    private val _uiState = MutableStateFlow(SyncUiState())
    val uiState: StateFlow<SyncUiState> = _uiState.asStateFlow()

    init {
        loadPairedDevices()
        observeSyncStatus()
    }

    /**
     * Load all paired devices from the repository.
     */
    private fun loadPairedDevices() {
        viewModelScope.launch {
            deviceRepository.getAllDevices().collect { devices ->
                _uiState.value = _uiState.value.copy(
                    pairedDevices = devices
                )
            }
        }
    }

    /**
     * Observe sync manager's connected devices and discovered devices.
     */
    private fun observeSyncStatus() {
        viewModelScope.launch {
            syncManager.connectedDevices.collect { devices ->
                val connectedIds = devices.map { it.deviceId }.toSet()
                _uiState.value = _uiState.value.copy(
                    connectedDeviceIds = connectedIds
                )
            }
        }

        viewModelScope.launch {
            syncManager.discoveredDevices.collect { devices ->
                _uiState.value = _uiState.value.copy(
                    discoveredDevices = devices,
                    isDiscovering = devices.isNotEmpty() || _uiState.value.isDiscovering
                )
            }
        }
    }

    /**
     * Enable sync and start device discovery.
     */
    fun enableSync() {
        val config = SyncConfig(
            enabled = true,
            nodeId = syncManager.nodeId,
            syncText = true,
            syncImages = true,
            syncFiles = false
        )
        syncManager.start(config)
        _uiState.value = _uiState.value.copy(isSyncEnabled = true, isDiscovering = true)
    }

    /**
     * Disable sync and stop all connections.
     */
    fun disableSync() {
        syncManager.stop()
        _uiState.value = _uiState.value.copy(
            isSyncEnabled = false,
            isDiscovering = false,
            connectedDeviceIds = emptySet(),
            discoveredDevices = emptyList()
        )
    }

    /**
     * Connect to a discovered device.
     *
     * @param device The discovered device to connect to.
     */
    fun connectToDiscoveredDevice(device: NsdDiscovery.DiscoveredDevice) {
        syncManager.connectToDiscoveredDevice(device)
    }

    /**
     * Disconnect from a specific device.
     *
     * @param deviceId The ID of the device to disconnect.
     */
    fun disconnectDevice(deviceId: String) {
        syncManager.disconnectDevice(deviceId)
    }

    /**
     * Unpair (remove) a device from the paired devices list.
     *
     * @param deviceId The ID of the device to unpair.
     */
    fun unpairDevice(deviceId: String) {
        viewModelScope.launch {
            syncManager.disconnectDevice(deviceId)
            deviceRepository.removeDevice(deviceId)
        }
    }

    /**
     * Initiate pairing via QR code content.
     *
     * @param qrText The QR code content string (format: icc://pair?...).
     */
    fun pairWithQr(qrText: String) {
        val pairingInfo = PairingInfo.fromQrText(qrText)
        if (pairingInfo == null) {
            _uiState.value = _uiState.value.copy(
                pairingError = "无效的二维码内容"
            )
            return
        }

        _uiState.value = _uiState.value.copy(isPairing = true, pairingError = null)
        syncManager.initiatePairing(pairingInfo)

        // Listen for pairing confirmation
        syncManager.setOnPairingRequestListener(object : SyncManager.OnPairingRequestListener {
            override fun onPairingConfirmed(deviceInfo: DeviceInfo) {
                _uiState.value = _uiState.value.copy(
                    isPairing = false,
                    showPairingDialog = false,
                    pairingError = null
                )
                loadPairedDevices()
            }
        })

        // Auto-dismiss pairing state after timeout
        viewModelScope.launch {
            kotlinx.coroutines.delay(30000)
            if (_uiState.value.isPairing) {
                _uiState.value = _uiState.value.copy(
                    isPairing = false,
                    pairingError = "配对超时，请重试"
                )
            }
        }
    }

    /**
     * Initiate pairing via PIN code.
     * Constructs a pairing info from the current sync configuration.
     *
     * @param pin The 6-digit PIN code.
     */
    fun pairWithPin(pin: String) {
        if (pin.length != 6 || !pin.all { it.isDigit() }) {
            _uiState.value = _uiState.value.copy(
                pairingError = "PIN 码必须是 6 位数字"
            )
            return
        }

        // Use the first discovered device or prompt for manual input
        val discovered = _uiState.value.discoveredDevices.firstOrNull()
        if (discovered != null) {
            val pairingInfo = PairingInfo(
                pairingId = "",
                host = discovered.host,
                port = discovered.port,
                token = pin,
                expiresAt = System.currentTimeMillis() / 1000 + 300
            )
            _uiState.value = _uiState.value.copy(isPairing = true, pairingError = null)
            syncManager.initiatePairing(pairingInfo)

            syncManager.setOnPairingRequestListener(object : SyncManager.OnPairingRequestListener {
                override fun onPairingConfirmed(deviceInfo: DeviceInfo) {
                    _uiState.value = _uiState.value.copy(
                        isPairing = false,
                        showPairingDialog = false,
                        pairingError = null
                    )
                    loadPairedDevices()
                }
            })

            viewModelScope.launch {
                kotlinx.coroutines.delay(30000)
                if (_uiState.value.isPairing) {
                    _uiState.value = _uiState.value.copy(
                        isPairing = false,
                        pairingError = "配对超时，请重试"
                    )
                }
            }
        } else {
            _uiState.value = _uiState.value.copy(
                pairingError = "未发现附近设备，请确保桌面端已启动同步服务"
            )
        }
    }

    /**
     * Show the pairing dialog.
     */
    fun showPairingDialog() {
        _uiState.value = _uiState.value.copy(
            showPairingDialog = true,
            pairingError = null
        )
    }

    /**
     * Hide the pairing dialog.
     */
    fun hidePairingDialog() {
        _uiState.value = _uiState.value.copy(
            showPairingDialog = false,
            pairingError = null
        )
    }

    /**
     * Clear any error state.
     */
    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null, pairingError = null)
    }

    override fun onCleared() {
        super.onCleared()
        // Don't stop sync on ViewModel clear — the SyncService manages the lifecycle
    }
}
