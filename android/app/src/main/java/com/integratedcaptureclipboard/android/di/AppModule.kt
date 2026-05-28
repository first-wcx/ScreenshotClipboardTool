package com.integratedcaptureclipboard.android.di

import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import javax.inject.Qualifier
import javax.inject.Singleton

/**
 * Qualifier annotation for the application-scoped CoroutineScope.
 */
@Qualifier
@Retention(AnnotationRetention.BINARY)
annotation class ApplicationScope

/**
 * Global DI module providing application-wide dependencies.
 * Installed in [SingletonComponent] to ensure singletons live
 * as long as the application.
 */
@Module
@InstallIn(SingletonComponent::class)
object AppModule {

    /**
     * Provide an application-scoped CoroutineScope tied to the application lifecycle.
     * Uses SupervisorJob so that failure of one child coroutine does not cancel others.
     */
    @Provides
    @Singleton
    @ApplicationScope
    fun provideApplicationScope(): CoroutineScope {
        return CoroutineScope(SupervisorJob() + Dispatchers.Default)
    }
}
