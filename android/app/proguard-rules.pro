# Add project specific ProGuard rules here.
# You can control the set of applied configuration files using the
# proguardFiles setting in build.gradle.kts.

# Keep data models (serialized to JSON)
-keep class com.integratedcaptureclipboard.android.data.model.** { *; }

# Keep Room entities
-keep class com.integratedcaptureclipboard.android.data.db.** { *; }

# Keep sync message types
-keepclassmembers class com.integratedcaptureclipboard.android.sync.** {
    *;
}

# OkHttp
-dontwarn okhttp3.**
-dontwarn okio.**

# Kotlin Coroutines
-keepnames class kotlinx.coroutines.internal.MainDispatcherFactory {}
-keepnames class kotlinx.coroutines.CoroutineExceptionHandler {}
-keepclassmembers class kotlinx.coroutines.** {
    volatile <fields>;
}

# Hilt
-dontwarn dagger.hilt.**

# Compose
-dontwarn androidx.compose.**
