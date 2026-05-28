package com.integratedcaptureclipboard.android.ui.screenshot

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.media.projection.MediaProjection
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.integratedcaptureclipboard.android.screenshot.ImageSaver
import com.integratedcaptureclipboard.android.screenshot.MediaProjectionManager
import com.integratedcaptureclipboard.android.screenshot.ScreenCapturer
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject

/**
 * UI state for the screenshot screen.
 */
data class ScreenshotUiState(
    val isCapturing: Boolean = false,
    val hasProjectionPermission: Boolean = false,
    val lastScreenshotPath: String? = null,
    val screenshotPaths: List<String> = emptyList(),
    val error: String? = null
)

/**
 * ViewModel for the screenshot screen.
 *
 * Manages the screen capture lifecycle using [MediaProjectionManager]
 * and [ScreenCapturer], and saves captured screenshots via [ImageSaver].
 *
 * @property context Application context.
 * @property imageSaver Image saver utility.
 */
@HiltViewModel
class ScreenshotViewModel @Inject constructor(
    @ApplicationContext private val context: Context,
    private val imageSaver: ImageSaver
) : ViewModel() {

    private val _uiState = MutableStateFlow(ScreenshotUiState())
    val uiState: StateFlow<ScreenshotUiState> = _uiState.asStateFlow()

    /** Manages the MediaProjection lifecycle. */
    private val mediaProjectionManager = MediaProjectionManager(context)

    /** The current screen capturer, if active. */
    private var screenCapturer: ScreenCapturer? = null

    /**
     * Request screen capture permission.
     *
     * Returns the intent that must be launched via ActivityResultLauncher.
     *
     * @return The screen capture permission intent.
     */
    fun getScreenCaptureIntent(): Intent {
        return mediaProjectionManager.createScreenCaptureIntent()
    }

    /**
     * Handle the result of the screen capture permission request.
     *
     * @param resultCode The result code from the permission activity.
     * @param data The result data intent.
     */
    fun onCapturePermissionResult(resultCode: Int, data: Intent) {
        val projection = mediaProjectionManager.acquireProjection(resultCode, data)
        if (projection != null) {
            _uiState.value = _uiState.value.copy(
                hasProjectionPermission = true,
                error = null
            )
        } else {
            _uiState.value = _uiState.value.copy(
                error = "截屏权限被拒绝"
            )
        }
    }

    /**
     * Take a screenshot using the current MediaProjection.
     *
     * Initializes a [ScreenCapturer], captures the screen, saves
     * the bitmap, and updates the UI state.
     */
    fun takeScreenshot() {
        val projection = mediaProjectionManager.mediaProjection
        if (projection == null) {
            _uiState.value = _uiState.value.copy(
                error = "未获取截屏权限，请先授权"
            )
            return
        }

        _uiState.value = _uiState.value.copy(isCapturing = true, error = null)

        viewModelScope.launch(Dispatchers.IO) {
            try {
                val (width, height, density) = ScreenCapturer.getScreenDimensions(context)
                val capturer = ScreenCapturer(projection)
                capturer.initialize(width, height, density)
                screenCapturer = capturer

                val bitmap = capturer.captureScreen(timeoutMs = 5000L)

                if (bitmap != null) {
                    val path = imageSaver.saveToPrivateDir(bitmap)
                    if (path != null) {
                        val currentPaths = _uiState.value.screenshotPaths.toMutableList()
                        currentPaths.add(0, path)

                        _uiState.value = _uiState.value.copy(
                            isCapturing = false,
                            lastScreenshotPath = path,
                            screenshotPaths = currentPaths,
                            error = null
                        )
                    } else {
                        _uiState.value = _uiState.value.copy(
                            isCapturing = false,
                            error = "保存截图失败"
                        )
                    }
                    bitmap.recycle()
                } else {
                    _uiState.value = _uiState.value.copy(
                        isCapturing = false,
                        error = "截屏失败：无法获取屏幕画面"
                    )
                }

                capturer.release()
                screenCapturer = null
            } catch (e: Exception) {
                _uiState.value = _uiState.value.copy(
                    isCapturing = false,
                    error = "截屏出错: ${e.message}"
                )
                screenCapturer?.release()
                screenCapturer = null
            }
        }
    }

    /**
     * Release the MediaProjection when it's no longer needed.
     */
    fun releaseProjection() {
        screenCapturer?.release()
        screenCapturer = null
        mediaProjectionManager.releaseProjection()
        _uiState.value = _uiState.value.copy(hasProjectionPermission = false)
    }

    /**
     * Clear any error state.
     */
    fun clearError() {
        _uiState.value = _uiState.value.copy(error = null)
    }

    override fun onCleared() {
        super.onCleared()
        screenCapturer?.release()
        mediaProjectionManager.releaseProjection()
    }
}
