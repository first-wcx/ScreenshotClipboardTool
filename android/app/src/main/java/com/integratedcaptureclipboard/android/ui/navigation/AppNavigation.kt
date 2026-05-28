package com.integratedcaptureclipboard.android.ui.navigation

import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ContentCopy
import androidx.compose.material.icons.filled.Screenshot
import androidx.compose.material.icons.filled.Sync
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.navArgument
import com.integratedcaptureclipboard.android.ui.clipboard.ClipboardScreen
import com.integratedcaptureclipboard.android.ui.editor.ImageEditorScreen
import com.integratedcaptureclipboard.android.ui.screenshot.ScreenshotScreen
import com.integratedcaptureclipboard.android.ui.sync.SyncScreen

/** Route constants for the three main tabs and the editor route. */
object Routes {
    const val CLIPBOARD = "clipboard"
    const val SCREENSHOT = "screenshot"
    const val SYNC = "sync"
    const val EDITOR = "editor/{imagePath}"

    /** Build an editor route with the given image path. */
    fun editorRoute(imagePath: String): String {
        return "editor/$imagePath"
    }
}

/** Data class representing a bottom navigation item. */
data class NavItem(
    val route: String,
    val label: String,
    val icon: ImageVector
)

/** The list of bottom navigation items. */
private val NAV_ITEMS = listOf(
    NavItem(Routes.CLIPBOARD, "剪贴板", Icons.Filled.ContentCopy),
    NavItem(Routes.SCREENSHOT, "截图", Icons.Filled.Screenshot),
    NavItem(Routes.SYNC, "同步", Icons.Filled.Sync)
)

/**
 * Composable that renders the bottom navigation bar.
 *
 * @param currentRoute The currently active route.
 * @param onNavigate Callback invoked when a navigation item is selected.
 * @param modifier Optional modifier.
 */
@Composable
fun BottomNavItem(
    currentRoute: String?,
    onNavigate: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    NavigationBar(modifier = modifier) {
        NAV_ITEMS.forEach { item ->
            NavigationBarItem(
                icon = { Icon(item.icon, contentDescription = item.label) },
                label = { Text(item.label) },
                selected = currentRoute == item.route,
                onClick = { onNavigate(item.route) }
            )
        }
    }
}

/**
 * Composable that defines the navigation graph for the app.
 * Contains three tabs: Clipboard, Screenshot, and Sync,
 * plus an editor route for image editing.
 *
 * @param navController The NavHostController for navigation.
 * @param modifier Optional modifier.
 */
@Composable
fun AppNavigation(
    navController: NavHostController,
    modifier: Modifier = Modifier
) {
    NavHost(
        navController = navController,
        startDestination = Routes.CLIPBOARD,
        modifier = modifier
    ) {
        composable(Routes.CLIPBOARD) {
            ClipboardScreen()
        }
        composable(Routes.SCREENSHOT) {
            ScreenshotScreen(
                onEditImage = { imagePath ->
                    navController.navigate(Routes.editorRoute(imagePath))
                }
            )
        }
        composable(Routes.SYNC) {
            SyncScreen()
        }
        composable(
            route = Routes.EDITOR,
            arguments = listOf(
                navArgument("imagePath") { type = NavType.StringType }
            )
        ) { backStackEntry ->
            val imagePath = backStackEntry.arguments?.getString("imagePath") ?: ""
            ImageEditorScreen(
                imagePath = imagePath,
                onBack = { navController.popBackStack() }
            )
        }
    }
}
