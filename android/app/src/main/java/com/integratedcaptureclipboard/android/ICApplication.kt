package com.integratedcaptureclipboard.android

import android.app.Application
import dagger.hilt.android.HiltAndroidApp

/**
 * Application class for Integrated Capture Clipboard.
 * Annotated with @HiltAndroidApp to trigger Hilt's code generation
 * and set up the application-wide dependency injection container.
 */
@HiltAndroidApp
class ICApplication : Application() {

    override fun onCreate() {
        super.onCreate()
        // Application-level initialization can be added here
    }
}
