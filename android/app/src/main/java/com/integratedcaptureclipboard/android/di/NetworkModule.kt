package com.integratedcaptureclipboard.android.di

import com.integratedcaptureclipboard.android.sync.WebSocketClient
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import okhttp3.OkHttpClient
import java.util.concurrent.TimeUnit
import javax.inject.Singleton

/**
 * DI module for network-related dependencies.
 *
 * Provides:
 * - [OkHttpClient] for WebSocket connections with appropriate timeouts
 * - [WebSocketClient] for managing multiple WebSocket connections
 *
 * Note: [com.integratedcaptureclipboard.android.sync.NsdDiscovery] is provided
 * by Hilt automatically via its @Inject constructor with @ApplicationContext.
 */
@Module
@InstallIn(SingletonComponent::class)
object NetworkModule {

    /**
     * Provide a singleton [OkHttpClient] instance configured for
     * WebSocket connections with appropriate timeouts.
     *
     * Ping interval is set to 30 seconds for heartbeat keep-alive,
     * consistent with the protocol design (ping/pong every 30s).
     */
    @Provides
    @Singleton
    fun provideOkHttpClient(): OkHttpClient {
        return OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS) // No read timeout for persistent WebSocket connections
            .writeTimeout(30, TimeUnit.SECONDS)
            .pingInterval(30, TimeUnit.SECONDS) // Heartbeat every 30 seconds
            .retryOnConnectionFailure(true)
            .build()
    }

    /**
     * Provide a singleton [WebSocketClient] for managing multiple
     * WebSocket connections to sync peers.
     *
     * @param okHttpClient The OkHttpClient instance to use for WebSocket connections.
     */
    @Provides
    @Singleton
    fun provideWebSocketClient(okHttpClient: OkHttpClient): WebSocketClient {
        return WebSocketClient(okHttpClient)
    }
}
