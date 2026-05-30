package com.jarvisai.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Scaffold
import androidx.compose.runtime.*
import androidx.core.content.ContextCompat
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import com.jarvisai.app.data.SessionManager
import com.jarvisai.app.ui.auth.AuthScreen
import com.jarvisai.app.ui.auth.AuthViewModel
import com.jarvisai.app.ui.chats.ChatsScreen
import com.jarvisai.app.ui.chats.ChatsViewModel
import com.jarvisai.app.ui.components.JarvisTopBar
import com.jarvisai.app.ui.home.HomeScreen
import com.jarvisai.app.ui.home.HomeViewModel
import com.jarvisai.app.ui.theme.JarvisAITheme

// ── Route constants ────────────────────────────────────────────────────────

object Routes {
    const val AUTH  = "auth"
    const val HOME  = "home"
    const val CHATS = "chats"
}

// ── Activity ───────────────────────────────────────────────────────────────

class MainActivity : ComponentActivity() {

    // Change this to your server's address (LAN IP or hostname).
    // The web server (website.py on port 8005) and the router (router.py on 8000)
    // should be accessible from the device on the same network.
    private val WEB_BASE_URL = "http://192.168.178.136:8005"

    private lateinit var session: SessionManager

    // ── Mic permission ────────────────────────────────────────────────────
    private var onMicGranted: (() -> Unit)? = null

    private val micPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) onMicGranted?.invoke()
    }

    fun requestMicPermission(onGranted: () -> Unit) {
        onMicGranted = onGranted
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
            == PackageManager.PERMISSION_GRANTED
        ) {
            onGranted()
        } else {
            micPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    // ── onCreate ──────────────────────────────────────────────────────────

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        session = SessionManager(applicationContext)

        setContent {
            JarvisAITheme {
                JarvisAIApp(
                    session    = session,
                    webBaseUrl = WEB_BASE_URL,
                    activity   = this,
                )
            }
        }
    }
}

// ── Root composable with navigation ──────────────────────────────────────

@Composable
fun JarvisAIApp(
    session:    SessionManager,
    webBaseUrl: String,
    activity:   MainActivity,
) {
    val navController = rememberNavController()
    val navBackStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = navBackStackEntry?.destination?.route

    // Scoped to the activity to allow cross-screen session continuation
    val homeVm: HomeViewModel = viewModel(session, webBaseUrl)

    // Start at auth unless already logged in
    val startDestination = if (session.isLoggedIn) Routes.HOME else Routes.AUTH

    androidx.compose.material3.Scaffold(
        containerColor = com.jarvisai.app.ui.theme.BgDeep,
        topBar = {
            if (session.isLoggedIn && currentRoute != Routes.AUTH && currentRoute != null) {
                JarvisTopBar(
                    currentRoute = currentRoute,
                    username = session.username ?: "",
                    onNavigateHome = { navController.navigate(Routes.HOME) },
                    onNavigateChats = { navController.navigate(Routes.CHATS) },
                    onLogout = {
                        session.clear()
                        homeVm.disconnect() // Ensure shared VM is disconnected
                        navController.navigate(Routes.AUTH) {
                            popUpTo(0) { inclusive = true }
                        }
                    },
                    onRefresh = {
                        // Refresh logic is specific to screens. 
                        // For now, we'll let screens handle their own refresh or trigger via events.
                    }
                )
            }
        }
    ) { padding ->
        androidx.compose.foundation.layout.Box(modifier = androidx.compose.ui.Modifier.padding(padding)) {
            NavHost(
                navController = navController,
                startDestination = startDestination,
            ) {
                // ── Auth ──────────────────────────────────────────────────────────
                composable(Routes.AUTH) {
                    val vm: AuthViewModel = viewModel(session, webBaseUrl)
                    AuthScreen(
                        viewModel = vm,
                        onNavigateHome = {
                            navController.navigate(Routes.HOME) {
                                popUpTo(Routes.AUTH) { inclusive = true }
                            }
                        },
                    )
                }

                // ── Home ──────────────────────────────────────────────────────────
                composable(Routes.HOME) {
                    // Auth guard
                    if (!session.isLoggedIn) {
                        LaunchedEffect(Unit) {
                            navController.navigate(Routes.AUTH) {
                                popUpTo(Routes.HOME) { inclusive = true }
                            }
                        }
                        return@composable
                    }

                    // Request mic permission before the screen starts connecting
                    LaunchedEffect(Unit) {
                        activity.requestMicPermission { /* permission granted — connect button still manual */ }
                    }

                    HomeScreen(
                        viewModel = homeVm,
                    )
                }

                // ── Chats ─────────────────────────────────────────────────────────
                composable(Routes.CHATS) {
                    // Auth guard
                    if (!session.isLoggedIn) {
                        LaunchedEffect(Unit) {
                            navController.navigate(Routes.AUTH) {
                                popUpTo(Routes.CHATS) { inclusive = true }
                            }
                        }
                        return@composable
                    }

                    val vm: ChatsViewModel = viewModel(session, webBaseUrl)

                    ChatsScreen(
                        viewModel = vm,
                        onContinue = { chatSession ->
                            homeVm.prepareContinuation(chatSession.resolveId() ?: "", chatSession.chat)
                            navController.navigate(Routes.HOME) {
                                popUpTo(Routes.CHATS) { inclusive = true }
                            }
                        }
                    )
                }
            }
        }
    }
}

// ── Scoped ViewModel factory helpers ─────────────────────────────────────

@Composable
inline fun <reified VM : ViewModel> viewModel(
    session:    SessionManager,
    webBaseUrl: String,
): VM {
    val factory = object : ViewModelProvider.Factory {
        @Suppress("UNCHECKED_CAST")
        override fun <T : ViewModel> create(modelClass: Class<T>): T = when {
            modelClass.isAssignableFrom(AuthViewModel::class.java)  ->
                AuthViewModel(session, webBaseUrl) as T
            modelClass.isAssignableFrom(HomeViewModel::class.java)  ->
                HomeViewModel(session, webBaseUrl) as T
            modelClass.isAssignableFrom(ChatsViewModel::class.java) ->
                ChatsViewModel(session, webBaseUrl) as T
            else -> throw IllegalArgumentException("Unknown ViewModel: ${modelClass.name}")
        }
    }
    return androidx.lifecycle.viewmodel.compose.viewModel(factory = factory)
}
