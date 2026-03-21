package it.leo.vela

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.*
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewmodel.compose.viewModel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlin.math.cos
import kotlin.math.sin

// ─────────────────────────────────────────────────────────────
// Palette — deep space
// ─────────────────────────────────────────────────────────────

object AppColors {
    val Background  = Color(0xFF08091A)
    val Surface     = Color(0xFF0F1128)
    val GlassStroke = Color(0x22FFFFFF)
    val TextPrimary = Color(0xFFF0F2FF)
    val TextMuted   = Color(0xFF6B7099)

    val IdleCore    = Color(0xFF7C5CFC)
    val IdleGlow    = Color(0x557C5CFC)
    val RecordCore  = Color(0xFFFF4B6E)
    val RecordGlow  = Color(0x55FF4B6E)
    val UploadCore  = Color(0xFF00C8E0)
    val UploadGlow  = Color(0x5500C8E0)
    val AiCore      = Color(0xFF34D09A)
    val AiGlow      = Color(0x5534D09A)
    val ErrorCore   = Color(0xFFFF8C42)
    val ErrorGlow   = Color(0x55FF8C42)
}

// ─────────────────────────────────────────────────────────────
// Theme
// ─────────────────────────────────────────────────────────────

private val CosmicColorScheme = darkColorScheme(
    primary          = AppColors.IdleCore,
    onPrimary        = AppColors.TextPrimary,
    primaryContainer = Color(0xFF1E1740),
    secondary        = AppColors.AiCore,
    background       = AppColors.Background,
    surface          = AppColors.Surface,
    onSurface        = AppColors.TextPrimary,
    error            = AppColors.RecordCore,
)

@Composable
fun AppTheme(content: @Composable () -> Unit) {
    MaterialTheme(colorScheme = CosmicColorScheme, content = content)
}

// ─────────────────────────────────────────────────────────────
// App States
// ─────────────────────────────────────────────────────────────

enum class AppState { IDLE, RECORDING, UPLOADING, AI_RESPONDING, ERROR }

private data class StateConfig(
    val label      : String,
    val coreColor  : Color,
    val glowColor  : Color,
    val statusLine1: String,
    val statusLine2: String,
)

private fun configFor(state: AppState) = when (state) {
    AppState.IDLE          -> StateConfig("READY",      AppColors.IdleCore,   AppColors.IdleGlow,   "AI Assistant",    "Tap the mic or send a photo")
    AppState.RECORDING     -> StateConfig("LISTENING",  AppColors.RecordCore, AppColors.RecordGlow, "Listening\u2026",  "Tap stop when you\u2019re done")
    AppState.UPLOADING     -> StateConfig("UPLOADING",  AppColors.UploadCore, AppColors.UploadGlow, "Sending\u2026",    "Uploading to server")
    AppState.AI_RESPONDING -> StateConfig("RESPONDING", AppColors.AiCore,     AppColors.AiGlow,     "AI is thinking\u2026", "Response on its way")
    AppState.ERROR         -> StateConfig("ERROR",      AppColors.ErrorCore,  AppColors.ErrorGlow,  "Connection lost", "Server unreachable")
}

// ─────────────────────────────────────────────────────────────
// ViewModel
// ─────────────────────────────────────────────────────────────

class MainViewModel : ViewModel() {
    private val _uiState = MutableStateFlow(AppState.IDLE)
    val uiState: StateFlow<AppState> = _uiState.asStateFlow()

    fun startRecording()   { _uiState.value = AppState.RECORDING }
    fun stopAndUpload()    { _uiState.value = AppState.UPLOADING   /* TODO: upload audio */ }
    fun onServerResponse() { _uiState.value = AppState.AI_RESPONDING }
    fun triggerError()     { _uiState.value = AppState.ERROR }
    fun resetToIdle()      { _uiState.value = AppState.IDLE }
    fun takePhoto()        { _uiState.value = AppState.UPLOADING   /* TODO: launch camera */ }
}

// ─────────────────────────────────────────────────────────────
// Entry point
// ─────────────────────────────────────────────────────────────

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AppTheme {
                Surface(
                    modifier = Modifier.fillMaxSize(),
                    color    = AppColors.Background
                ) { MainScreen() }
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────
// Main Screen
// ─────────────────────────────────────────────────────────────

@Composable
fun MainScreen(viewModel: MainViewModel = viewModel()) {
    val state  by viewModel.uiState.collectAsState()
    val config  = configFor(state)

    val animatedCore by animateColorAsState(
        targetValue   = config.coreColor,
        animationSpec = tween(700, easing = FastOutSlowInEasing),
        label         = "coreColor"
    )
    val animatedGlow by animateColorAsState(
        targetValue   = config.glowColor,
        animationSpec = tween(700, easing = FastOutSlowInEasing),
        label         = "glowColor"
    )

    Box(modifier = Modifier.fillMaxSize()) {
        StarfieldBackground()

        Column(
            modifier            = Modifier.fillMaxSize(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.SpaceBetween
        ) {
            Spacer(modifier = Modifier.height(56.dp))

            // State badge
            AnimatedContent(
                targetState  = config.label,
                transitionSpec = { fadeIn(tween(400)) togetherWith fadeOut(tween(300)) },
                label        = "stateLabel"
            ) { label ->
                Text(
                    text          = label,
                    fontSize      = 11.sp,
                    fontWeight    = FontWeight.Bold,
                    letterSpacing = 4.sp,
                    color         = animatedCore.copy(alpha = 0.8f),
                    fontFamily    = FontFamily.Monospace
                )
            }

            // Central orb
            Box(modifier = Modifier.weight(1f), contentAlignment = Alignment.Center) {
                StateOrb(state = state, coreColor = animatedCore, glowColor = animatedGlow)
            }

            // Status text
            AnimatedContent(
                targetState  = config,
                transitionSpec = { fadeIn(tween(400)) togetherWith fadeOut(tween(300)) },
                label        = "statusText"
            ) { cfg ->
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text       = cfg.statusLine1,
                        fontSize   = 22.sp,
                        fontWeight = FontWeight.SemiBold,
                        color      = AppColors.TextPrimary,
                        textAlign  = TextAlign.Center
                    )
                    Spacer(modifier = Modifier.height(6.dp))
                    Text(
                        text      = cfg.statusLine2,
                        fontSize  = 14.sp,
                        color     = AppColors.TextMuted,
                        textAlign = TextAlign.Center
                    )
                }
            }

            Spacer(modifier = Modifier.height(32.dp))

            BottomBar(
                state         = state,
                accentColor   = animatedCore,
                onMicClick    = {
                    when (state) {
                        AppState.IDLE, AppState.ERROR -> viewModel.startRecording()
                        AppState.RECORDING            -> viewModel.stopAndUpload()
                        AppState.AI_RESPONDING        -> viewModel.resetToIdle()
                        AppState.UPLOADING            -> Unit
                    }
                },
                onCameraClick = { viewModel.takePhoto() }
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────
// Starfield background
// ─────────────────────────────────────────────────────────────

@Composable
fun StarfieldBackground() {
    val stars = remember {
        List(80) {
            Triple(
                Math.random().toFloat(),
                Math.random().toFloat(),
                (Math.random() * 0.6 + 0.2).toFloat()
            )
        }
    }
    val transition = rememberInfiniteTransition(label = "stars")
    val twinkle by transition.animateFloat(
        initialValue = 0f, targetValue = 1f,
        animationSpec = infiniteRepeatable(tween(3000), RepeatMode.Reverse),
        label = "twinkle"
    )

    Canvas(modifier = Modifier.fillMaxSize()) {
        drawRect(
            brush = Brush.radialGradient(
                colors = listOf(Color(0xFF12153A), AppColors.Background),
                center = Offset(size.width * 0.5f, size.height * 0.38f),
                radius = size.width * 0.9f
            )
        )
        stars.forEachIndexed { i, (xF, yF, baseAlpha) ->
            val a = baseAlpha * (0.4f + 0.6f * if (i % 3 == 0) twinkle else (1f - twinkle))
            drawCircle(
                color  = Color.White.copy(alpha = a),
                radius = if (i % 7 == 0) 2.2f else 1.2f,
                center = Offset(xF * size.width, yF * size.height)
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────
// Central orb
// ─────────────────────────────────────────────────────────────

@Composable
fun StateOrb(state: AppState, coreColor: Color, glowColor: Color) {
    val infinite = rememberInfiniteTransition(label = "orb")

    val pulse by infinite.animateFloat(
        initialValue = 0.92f,
        targetValue  = when (state) {
            AppState.RECORDING     -> 1.35f
            AppState.UPLOADING     -> 1.12f
            else                   -> 1.08f
        },
        animationSpec = infiniteRepeatable(
            tween(
                durationMillis = when (state) {
                    AppState.RECORDING     -> 600
                    AppState.AI_RESPONDING -> 900
                    else                   -> 2000
                },
                easing = FastOutSlowInEasing
            ),
            RepeatMode.Reverse
        ),
        label = "pulse"
    )

    val rotation by infinite.animateFloat(
        initialValue  = 0f, targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(3000, easing = LinearEasing)),
        label         = "rotation"
    )

    val spinnerAngle by infinite.animateFloat(
        initialValue  = 0f, targetValue = 360f,
        animationSpec = infiniteRepeatable(tween(900, easing = LinearEasing)),
        label         = "spinner"
    )

    val errorAlpha by infinite.animateFloat(
        initialValue  = 1f, targetValue = 0.3f,
        animationSpec = infiniteRepeatable(tween(750), RepeatMode.Reverse),
        label         = "errorBlink"
    )

    Box(modifier = Modifier.size(280.dp), contentAlignment = Alignment.Center) {
        // Outer halo
        Box(
            modifier = Modifier
                .size(260.dp)
                .scale(pulse * 1.05f)
                .background(
                    brush = Brush.radialGradient(listOf(glowColor.copy(alpha = 0.12f), Color.Transparent)),
                    shape = CircleShape
                )
        )
        // Mid halo
        Box(
            modifier = Modifier
                .size(200.dp)
                .scale(pulse)
                .background(
                    brush = Brush.radialGradient(listOf(glowColor.copy(alpha = 0.28f), Color.Transparent)),
                    shape = CircleShape
                )
        )

        // Orbit dots (AI only)
        if (state == AppState.AI_RESPONDING) {
            OrbitDots(color = coreColor, radius = 90f, rotation = rotation)
        }

        // Upload arc
        if (state == AppState.UPLOADING) {
            Canvas(modifier = Modifier.size(160.dp)) {
                drawArc(
                    color      = coreColor.copy(alpha = 0.9f),
                    startAngle = spinnerAngle,
                    sweepAngle = 260f,
                    useCenter  = false,
                    style      = androidx.compose.ui.graphics.drawscope.Stroke(
                        width = 4.dp.toPx(),
                        cap   = StrokeCap.Round
                    )
                )
            }
        }

        // Core orb
        Box(
            modifier = Modifier
                .size(120.dp)
                .alpha(if (state == AppState.ERROR) errorAlpha else 1f)
                .background(
                    brush = Brush.radialGradient(
                        listOf(coreColor.copy(0.95f), coreColor.copy(0.55f), Color.Transparent)
                    ),
                    shape = CircleShape
                )
        )

        // Inner highlight
        Box(
            modifier = Modifier
                .size(44.dp)
                .alpha(if (state == AppState.ERROR) errorAlpha else 1f)
                .background(
                    brush = Brush.radialGradient(listOf(Color.White.copy(0.55f), Color.Transparent)),
                    shape = CircleShape
                )
        )

        // Error icon
        if (state == AppState.ERROR) {
            Icon(
                imageVector        = Icons.Default.Warning,
                contentDescription = "Error",
                tint               = AppColors.TextPrimary.copy(alpha = errorAlpha),
                modifier           = Modifier.size(38.dp)
            )
        }
    }
}

@Composable
fun OrbitDots(color: Color, radius: Float, rotation: Float) {
    Canvas(modifier = Modifier.size(240.dp)) {
        val cx = size.width / 2f
        val cy = size.height / 2f
        val count = 6
        repeat(count) { i ->
            val angle = Math.toRadians((rotation + (360f / count) * i).toDouble())
            val alpha = 0.35f + 0.65f * (i.toFloat() / count)
            drawCircle(
                color  = color.copy(alpha = alpha),
                radius = (5f - i * 0.5f).coerceAtLeast(1f),
                center = Offset(cx + radius * cos(angle).toFloat(), cy + radius * sin(angle).toFloat())
            )
        }
    }
}

// ─────────────────────────────────────────────────────────────
// Bottom bar — frosted glass
// ─────────────────────────────────────────────────────────────

@Composable
fun BottomBar(
    state        : AppState,
    accentColor  : Color,
    onMicClick   : () -> Unit,
    onCameraClick: () -> Unit
) {
    val isBusy   = state == AppState.UPLOADING
    val fabColor = when (state) {
        AppState.RECORDING     -> AppColors.RecordCore
        AppState.AI_RESPONDING -> AppColors.AiCore
        else                   -> accentColor
    }
    val fabIcon  = if (state == AppState.RECORDING) Icons.Default.Stop else Icons.Default.Mic
    val fabLabel = when (state) {
        AppState.IDLE, AppState.ERROR -> "SPEAK"
        AppState.RECORDING            -> "STOP"
        AppState.UPLOADING            -> "SENDING"
        AppState.AI_RESPONDING        -> "DONE"
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(topStart = 28.dp, topEnd = 28.dp))
            .background(AppColors.Surface.copy(alpha = 0.75f))
    ) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .height(1.dp)
                .background(AppColors.GlassStroke)
        )

        Row(
            modifier              = Modifier
                .fillMaxWidth()
                .navigationBarsPadding()
                .padding(horizontal = 36.dp, vertical = 24.dp),
            horizontalArrangement = Arrangement.SpaceEvenly,
            verticalAlignment     = Alignment.CenterVertically
        ) {
            // Camera
            BarAction(label = "PHOTO", enabled = state == AppState.IDLE) {
                IconButton(
                    onClick  = onCameraClick,
                    enabled  = state == AppState.IDLE,
                    modifier = Modifier
                        .size(56.dp)
                        .clip(CircleShape)
                        .background(AppColors.GlassStroke)
                ) {
                    Icon(
                        imageVector        = Icons.Default.CameraAlt,
                        contentDescription = "Send Photo",
                        tint               = if (state == AppState.IDLE) AppColors.TextPrimary else AppColors.TextMuted,
                        modifier           = Modifier.size(24.dp)
                    )
                }
            }

            // Mic FAB
            BarAction(label = fabLabel, enabled = !isBusy) {
                Box(contentAlignment = Alignment.Center) {
                    if (state == AppState.RECORDING) RecordingRing(color = fabColor)
                    FloatingActionButton(
                        onClick        = { if (!isBusy) onMicClick() },
                        containerColor = fabColor,
                        contentColor   = AppColors.TextPrimary,
                        modifier       = Modifier.size(72.dp),
                        elevation      = FloatingActionButtonDefaults.elevation(0.dp)
                    ) {
                        Icon(fabIcon, contentDescription = "Mic", modifier = Modifier.size(30.dp))
                    }
                }
            }

            // Balance
            Spacer(modifier = Modifier.size(56.dp))
        }
    }
}

@Composable
fun RecordingRing(color: Color) {
    val inf = rememberInfiniteTransition(label = "recRing")
    val scale by inf.animateFloat(
        initialValue  = 1f, targetValue = 1.7f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
        label         = "ringScale"
    )
    val alpha by inf.animateFloat(
        initialValue  = 0.5f, targetValue = 0f,
        animationSpec = infiniteRepeatable(tween(700), RepeatMode.Reverse),
        label         = "ringAlpha"
    )
    Box(
        modifier = Modifier
            .size(72.dp)
            .scale(scale)
            .background(color.copy(alpha = alpha), CircleShape)
    )
}

@Composable
private fun BarAction(
    label  : String,
    enabled: Boolean = true,
    content: @Composable () -> Unit
) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        content()
        Spacer(modifier = Modifier.height(8.dp))
        Text(
            text          = label,
            fontSize      = 10.sp,
            letterSpacing = 1.5.sp,
            fontWeight    = FontWeight.Medium,
            fontFamily    = FontFamily.Monospace,
            color         = if (enabled) AppColors.TextMuted else AppColors.TextMuted.copy(alpha = 0.4f)
        )
    }
}
