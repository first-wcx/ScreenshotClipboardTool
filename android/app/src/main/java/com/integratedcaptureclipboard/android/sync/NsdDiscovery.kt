package com.integratedcaptureclipboard.android.sync

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton

/**
 * mDNS service discovery for the ICC multi-device sync system.
 *
 * Uses Android's NsdManager to discover desktop devices broadcasting
 * the "_icc_sync._tcp" mDNS service on the local network.
 *
 * Discovery flow:
 * 1. Start discovery for service type "_icc_sync._tcp"
 * 2. On service found, resolve the service to get host and port
 * 3. Notify listener with the discovered device info
 */
@Singleton
class NsdDiscovery @Inject constructor(
    @ApplicationContext private val context: Context
) {

    companion object {
        private const val TAG = "NsdDiscovery"
        /** mDNS service type for ICC sync, consistent with desktop zeroconf broadcaster. */
        const val SERVICE_TYPE = "_icc_sync._tcp"
    }

    /** Android NsdManager instance. */
    private val nsdManager: NsdManager by lazy {
        context.getSystemService(Context.NSD_SERVICE) as NsdManager
    }

    /** Current discovery listener, if discovery is active. */
    private var discoveryListener: NsdManager.DiscoveryListener? = null

    /** Whether discovery is currently active. */
    @Volatile
    private var isDiscovering = false

    /** Listener for discovered device events. */
    private var onDeviceFoundListener: OnDeviceFoundListener? = null

    /**
     * Set the listener for discovered device events.
     *
     * @param listener The listener to receive discovery callbacks.
     */
    fun setOnDeviceFoundListener(listener: OnDeviceFoundListener) {
        onDeviceFoundListener = listener
    }

    /**
     * Start discovering ICC sync services on the local network.
     *
     * If discovery is already active, this is a no-op.
     */
    fun startDiscovery() {
        if (isDiscovering) {
            Log.d(TAG, "Discovery already active")
            return
        }

        val listener = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {
                Log.d(TAG, "Discovery started for service type: $serviceType")
                isDiscovering = true
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                Log.d(TAG, "Service found: ${serviceInfo.serviceName}")
                resolveService(serviceInfo)
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                Log.d(TAG, "Service lost: ${serviceInfo.serviceName}")
                onDeviceFoundListener?.onDeviceLost(serviceInfo.serviceName)
            }

            override fun onDiscoveryStopped(serviceType: String) {
                Log.d(TAG, "Discovery stopped for service type: $serviceType")
                isDiscovering = false
            }

            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "Discovery start failed: error $errorCode")
                isDiscovering = false
            }

            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {
                Log.e(TAG, "Discovery stop failed: error $errorCode")
                isDiscovering = false
            }
        }

        discoveryListener = listener

        try {
            nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, listener)
        } catch (e: Exception) {
            Log.e(TAG, "Failed to start NSD discovery", e)
            isDiscovering = false
        }
    }

    /**
     * Stop discovering ICC sync services.
     */
    fun stopDiscovery() {
        if (!isDiscovering) {
            return
        }

        try {
            discoveryListener?.let { nsdManager.stopServiceDiscovery(it) }
        } catch (e: Exception) {
            Log.e(TAG, "Failed to stop NSD discovery", e)
        }

        isDiscovering = false
        discoveryListener = null
    }

    /**
     * Resolve a discovered service to obtain host and port details.
     *
     * @param serviceInfo The discovered service info to resolve.
     */
    private fun resolveService(serviceInfo: NsdServiceInfo) {
        try {
            nsdManager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) {
                    Log.e(TAG, "Resolve failed for ${serviceInfo.serviceName}: error $errorCode")
                }

                override fun onServiceResolved(resolvedInfo: NsdServiceInfo) {
                    val host = resolvedInfo.host?.hostAddress ?: return
                    val port = resolvedInfo.port
                    val serviceName = resolvedInfo.serviceName

                    Log.d(TAG, "Service resolved: $serviceName at $host:$port")

                    // Extract device info from service attributes if available
                    val attributes = resolvedInfo.attributes
                    val deviceId = attributes["device_id"]?.let { String(it) } ?: ""
                    val deviceName = attributes["device_name"]?.let { String(it) } ?: serviceName
                    val deviceType = attributes["device_type"]?.let { String(it) } ?: "desktop"
                    val platform = attributes["platform"]?.let { String(it) } ?: ""

                    val discoveredDevice = DiscoveredDevice(
                        serviceName = serviceName,
                        host = host,
                        port = port,
                        deviceId = deviceId,
                        deviceName = deviceName,
                        deviceType = deviceType,
                        platform = platform
                    )

                    onDeviceFoundListener?.onDeviceFound(discoveredDevice)
                }
            })
        } catch (e: Exception) {
            Log.e(TAG, "Failed to resolve service", e)
        }
    }

    /**
     * Callback interface for device discovery events.
     */
    interface OnDeviceFoundListener {
        /**
         * Called when a new ICC sync device is discovered on the network.
         *
         * @param device Information about the discovered device.
         */
        fun onDeviceFound(device: DiscoveredDevice)

        /**
         * Called when a previously discovered device is no longer available.
         *
         * @param serviceName The service name of the lost device.
         */
        fun onDeviceLost(serviceName: String)
    }

    /**
     * Represents a device discovered via mDNS on the local network.
     *
     * @property serviceName The mDNS service name.
     * @property host The resolved IP address.
     * @property port The resolved port number.
     * @property deviceId Device ID extracted from service attributes (may be empty).
     * @property deviceName Human-readable device name.
     * @property deviceType Device type (e.g. "desktop").
     * @property platform Platform string (e.g. "windows_11").
     */
    data class DiscoveredDevice(
        val serviceName: String,
        val host: String,
        val port: Int,
        val deviceId: String,
        val deviceName: String,
        val deviceType: String,
        val platform: String
    )
}
