package com.flowai.app.ui.home

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.*
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.*
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.flowai.app.data.ConversationTurn
import com.flowai.app.ui.theme.*
import kotlin.math.*

@Composable
fun HomeScreen(
    viewModel:      HomeViewModel,
    username:       String,
    onNavigateChats: () -> Unit,
    onLogout:       () -> Unit,
) {
    val ui by viewModel.uiState.collectAsState()

    var routerHost  by remember { mutableStateOf("192.168.1.100:8000") }
    var routerFrame by remember { mutableStateOf("1280") }

    // fake waveform animation (replace with real AudioRecord data in production)
    val wavePhase by rememberInfiniteTransition(label = "wave").animateFloat(
        initialValue = 0f, targetValue = (2 * PI).toFloat(),
        animationSpec = infiniteRepeatable(tween(2000, easing = LinearEasing)), label = "wavePhase"
    )

    Scaffold(
        containerColor = BgDeep,
        topBar  = { HomeTopBar(username, ui, onNavigateChats, onLogout) },
        bottomBar = { HomeFooter(ui) },
    ) { padding ->
        Row(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // ── Left panel ────────────────────────────────────────────────
            Column(
                modifier = Modifier
                    .width(270.dp)
                    .fillMaxHeight()
                    .verticalScroll(rememberScrollState())
                    .background(Color.Transparent)
                    .border(width = 0.dp, color = Color.Transparent)
                    .padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                // Connection section
                PanelSection(title = "Connection") {
                    LabeledField("Router Host") {
                        FlowInput(routerHost, onValueChange = { routerHost = it })
                    }
                    LabeledField("Frame Size (samples)") {
                        FlowInput(
                            routerFrame,
                            onValueChange = { routerFrame = it },
                            isNumber = true,
                        )
                    }
                    if (ui.phase == Phase.IDLE) {
                        Button(
                            onClick = { viewModel.connect(routerHost, routerFrame.toIntOrNull() ?: 1280) },
                            modifier = Modifier.fillMaxWidth(),
                            shape    = RoundedCornerShape(10.dp),
                            colors   = ButtonDefaults.buttonColors(containerColor = Accent),
                            contentPadding = PaddingValues(vertical = 12.dp),
                        ) {
                            Text("Connect & Start", style = MaterialTheme.typography.bodyMedium,
                                color = Color.White, fontWeight = FontWeight.SemiBold)
                        }
                    } else {
                        Button(
                            onClick = { viewModel.disconnect() },
                            modifier = Modifier.fillMaxWidth(),
                            shape    = RoundedCornerShape(10.dp),
                            colors   = ButtonDefaults.buttonColors(containerColor = RedDim,
                                contentColor = Red),
                            border   = BorderStroke(1.dp, Red.copy(alpha = 0.3f)),
                            contentPadding = PaddingValues(vertical = 12.dp),
                        ) {
                            Text("Disconnect", style = MaterialTheme.typography.bodyMedium,
                                fontWeight = FontWeight.SemiBold)
                        }
                    }
                }

                // Waveform
                PanelSection(title = "Microphone") {
                    WaveformCanvas(
                        phase      = wavePhase,
                        isActive   = ui.phase != Phase.IDLE,
                        phaseColor = when (ui.phase) {
                            Phase.MAIN   -> Accent
                            Phase.ROUTER -> Sky
                            else         -> TextDim
                        },
                    )
                }

                // Wake word OR silence timer depending on phase
                AnimatedContent(
                    targetState = ui.phase,
                    transitionSpec = { fadeIn() togetherWith fadeOut() },
                    label = "phase-panel"
                ) { phase ->
                    if (phase != Phase.MAIN) {
                        WakeWordPanel(ui)
                    } else {
                        SilenceTimerPanel(ui)
                    }
                }

                // Stats
                PanelSection(title = "Stats") {
                    StatRow("Frames sent",  ui.framesSent.toString())
                    StatRow("WW detections", ui.detectCount.toString())
                    StatRow("AI turns",     ui.turnCount.toString())
                    StatRow("Reconnects",   ui.reconnectCount.toString())
                    StatRow("Errors",       ui.errorCount.toString())
                }
            }

            // Divider
            Divider(
                modifier  = Modifier.fillMaxHeight().width(1.dp),
                color     = Border1,
                thickness = 1.dp,
            )

            // ── Right panel ───────────────────────────────────────────────
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight(),
            ) {
                if (ui.phase != Phase.MAIN || ui.conversation.isEmpty()) {
                    IdlePlaceholder(isConnected = ui.phase == Phase.ROUTER)
                } else {
                    ConversationPanel(
                        turns   = ui.conversation,
                        onClear = { viewModel.clearConversationPublic() },
                    )
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  TOP BAR
// ═══════════════════════════════════════════════════════════════════════════

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeTopBar(
    username: String,
    ui: HomeUiState,
    onNavigateChats: () -> Unit,
    onLogout:        () -> Unit,
) {
    TopAppBar(
        colors = TopAppBarDefaults.topAppBarColors(
            containerColor = BgDeep.copy(alpha = 0.95f),
        ),
        modifier = Modifier.border(BorderStroke(1.dp, Border1)),
        title = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text(
                    text     = "flow.ai",
                    style    = MaterialTheme.typography.titleLarge,
                    color    = TextPrimary,
                    fontWeight = FontWeight.ExtraBold,
                )

                // Phase pills
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    PhasePill(
                        number  = 1,
                        label   = "Wake Word",
                        state   = when (ui.phase) {
                            Phase.ROUTER -> "active"
                            Phase.MAIN   -> "done"
                            else         -> "idle"
                        }
                    )
                    Text("›", color = TextDim, fontSize = 14.sp)
                    PhasePill(
                        number  = 2,
                        label   = "AI Voice",
                        state   = if (ui.phase == Phase.MAIN) "active" else "idle"
                    )
                }
            }
        },
        actions = {
            // Username chip
            Surface(
                shape  = RoundedCornerShape(999.dp),
                color  = Surface2,
                border = BorderStroke(1.dp, Border1),
                modifier = Modifier.padding(end = 4.dp),
            ) {
                Text(
                    text     = username,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                    style    = MaterialTheme.typography.labelSmall,
                    color    = TextMuted,
                    fontFamily = FontFamily.Monospace,
                )
            }

            TextButton(
                onClick  = onNavigateChats,
                modifier = Modifier.padding(end = 2.dp),
            ) {
                Text("Chats", color = TextMuted, style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.Medium)
            }

            TextButton(
                onClick = onLogout,
            ) {
                Text("Logout", color = Red.copy(alpha = 0.8f), style = MaterialTheme.typography.bodySmall)
            }

            // Status indicator
            StatusPill(ui.phase, ui.statusText)
            Spacer(Modifier.width(8.dp))
        }
    )
}

@Composable
fun PhasePill(number: Int, label: String, state: String) {
    val bg    = when (state) { "active" -> Surface2; "done" -> GreenDim; else -> Surface1 }
    val fg    = when (state) { "active" -> TextPrimary; "done" -> TextMuted; else -> TextDim }
    val numBg = when (state) { "active" -> Accent; "done" -> GreenDim; else -> Surface2 }
    val numFg = when (state) { "active" -> Color.White; "done" -> Green; else -> TextDim }

    Surface(
        shape  = RoundedCornerShape(999.dp),
        color  = bg,
        border = BorderStroke(1.dp, if (state == "active") Border2 else Border1),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(5.dp),
        ) {
            Surface(shape = CircleShape, color = numBg) {
                Text(
                    text     = number.toString(),
                    modifier = Modifier.size(16.dp).wrapContentSize(Alignment.Center),
                    style    = MaterialTheme.typography.labelSmall,
                    color    = numFg,
                    fontSize = 8.sp,
                )
            }
            Text(label, style = MaterialTheme.typography.labelSmall, color = fg, fontSize = 9.sp)
        }
    }
}

@Composable
fun StatusPill(phase: Phase, statusText: String) {
    val dotColor = when (phase) {
        Phase.ROUTER -> Sky
        Phase.MAIN   -> Green
        else         -> TextDim
    }
    val dotAnim by rememberInfiniteTransition(label = "dot").animateFloat(
        initialValue = 1f, targetValue = if (phase != Phase.IDLE) 0.3f else 1f,
        animationSpec = if (phase != Phase.IDLE)
            infiniteRepeatable(tween(1200, easing = EaseInOutQuad))
        else snap(),
        label = "dotAnim"
    )
    Surface(
        shape  = RoundedCornerShape(999.dp),
        color  = Surface1,
        border = BorderStroke(1.dp, Border1),
    ) {
        Row(
            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Canvas(Modifier.size(7.dp)) {
                drawCircle(dotColor.copy(alpha = dotAnim))
            }
            Text(statusText, style = MaterialTheme.typography.labelSmall, color = TextMuted,
                fontFamily = FontFamily.Monospace)
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  FOOTER
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun HomeFooter(ui: HomeUiState) {
    Surface(
        color  = BgDeep.copy(alpha = 0.95f),
        border = BorderStroke(1.dp, Border1),
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .height(36.dp)
                .padding(horizontal = 16.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(20.dp),
        ) {
            FooterStat("phase",       ui.phase.name.lowercase())
            FooterStat("router ws",   ui.routerWsUrl)
            FooterStat("main ws",     ui.mainWsUrl)
            FooterStat("frame",       ui.frameSize.toString())
            FooterStat("sample rate", "16 kHz")
        }
    }
}

@Composable
fun FooterStat(label: String, value: String) {
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label, style = MaterialTheme.typography.labelSmall, color = TextDim, fontSize = 9.sp)
        Text(value, style = MaterialTheme.typography.labelSmall, color = TextMuted,
            fontFamily = FontFamily.Monospace, fontSize = 9.sp)
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  WAVEFORM
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun WaveformCanvas(phase: Float, isActive: Boolean, phaseColor: Color) {
    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(48.dp)
            .clip(RoundedCornerShape(8.dp))
            .background(Surface1)
    ) {
        drawWaveform(this, phase, isActive, phaseColor)
    }
}

fun drawWaveform(scope: DrawScope, phase: Float, isActive: Boolean, color: Color) {
    val w     = scope.size.width
    val h     = scope.size.height
    val mid   = h / 2
    val path  = Path()
    val pts   = 100

    for (i in 0..pts) {
        val x    = w * i / pts
        val norm = i.toFloat() / pts
        val amp  = if (isActive) (sin(norm * 4 * PI + phase) * 0.4 + sin(norm * 9 * PI + phase * 1.5) * 0.3).toFloat() else 0f
        val y    = mid + amp * mid * 0.7f
        if (i == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }

    scope.drawPath(
        path  = path,
        color = if (isActive) color.copy(alpha = 0.85f) else color.copy(alpha = 0.2f),
        style = Stroke(width = 1.5.dp.value),
    )
}

// ═══════════════════════════════════════════════════════════════════════════
//  WAKE WORD PANEL
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun WakeWordPanel(ui: HomeUiState) {
    PanelSection(title = "Wake Word Score") {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(ui.wwModelName, style = MaterialTheme.typography.labelSmall,
                color = TextMuted, fontFamily = FontFamily.Monospace)
            Text("%.3f".format(ui.wwScore), style = MaterialTheme.typography.titleMedium,
                color = TextPrimary, fontFamily = FontFamily.Monospace, fontSize = 14.sp)
        }
        // Progress bar
        val barColor = if (ui.wwScore >= 0.5f) Green else Sky
        LinearProgressIndicator(
            progress         = { ui.wwScore.coerceIn(0f, 1f) },
            modifier         = Modifier.fillMaxWidth().height(4.dp).clip(RoundedCornerShape(4.dp)),
            color            = barColor,
            trackColor       = Surface3,
        )
        // Detection badge
        val detected    = ui.detectCount > 0
        val badgeBg     = if (detected) GreenDim  else Surface2
        val badgeBorder = if (detected) Green.copy(alpha = 0.3f) else Border1
        val badgeText   = if (detected) "Detected!" else "Listening…"
        val badgeFg     = if (detected) Green else TextMuted

        Surface(
            color  = badgeBg,
            shape  = RoundedCornerShape(10.dp),
            border = BorderStroke(1.dp, badgeBorder),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Text("🎙", fontSize = 14.sp)
                Text(badgeText, style = MaterialTheme.typography.bodySmall,
                    color = badgeFg, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                Surface(
                    shape = RoundedCornerShape(999.dp),
                    color = Surface3,
                ) {
                    Text(
                        ui.detectCount.toString(),
                        modifier = Modifier.padding(horizontal = 8.dp, vertical = 2.dp),
                        style    = MaterialTheme.typography.labelSmall,
                        color    = TextDim,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SILENCE TIMER PANEL
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun SilenceTimerPanel(ui: HomeUiState) {
    PanelSection(title = "Silence Timer") {
        // Ring
        Box(
            modifier = Modifier.size(80.dp).align(Alignment.CenterHorizontally),
            contentAlignment = Alignment.Center,
        ) {
            val frac = (ui.silenceLeft / 10f).coerceIn(0f, 1f)
            val ringColor = when {
                frac > 0.5f -> Accent
                frac > 0.25f -> Amber
                else -> Red
            }
            Canvas(Modifier.fillMaxSize()) {
                val radius = size.minDimension / 2 - 5.dp.toPx()
                val stroke = Stroke(width = 5.dp.toPx(), cap = StrokeCap.Round)
                drawCircle(Surface2, radius = radius, style = stroke)
                val sweep = frac * 360f
                drawArc(
                    color      = ringColor,
                    startAngle = -90f,
                    sweepAngle = sweep,
                    useCenter  = false,
                    style      = stroke,
                    topLeft    = Offset(size.width / 2 - radius, size.height / 2 - radius),
                    size       = Size(radius * 2, radius * 2),
                )
            }
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Text(
                    text  = ceil(ui.silenceLeft).toInt().toString(),
                    style = MaterialTheme.typography.titleLarge,
                    color = TextPrimary,
                    fontWeight = FontWeight.ExtraBold,
                )
                Text("silence", style = MaterialTheme.typography.bodySmall, color = TextDim, fontSize = 9.sp)
            }
        }

        // AI state badge
        val (badgeMod, stateText) = when (ui.aiState) {
            AiState.LISTENING -> Pair(GreenDim to Green.copy(alpha = 0.3f), "listening…")
            AiState.SPEAKING  -> Pair(AccentDim to Accent.copy(alpha = 0.3f), "AI speaking…")
            AiState.THINKING  -> Pair(AccentDim to Accent.copy(alpha = 0.3f), "thinking…")
            AiState.TIMEOUT   -> Pair(Surface2 to Border1, "silence timeout — reconnecting…")
            else               -> Pair(Surface2 to Border1, "waiting for speech…")
        }
        val badgeBg     = badgeMod.first
        val badgeBorder = badgeMod.second
        val dotColor    = when (ui.aiState) {
            AiState.LISTENING -> Green
            AiState.SPEAKING, AiState.THINKING -> Accent
            else -> TextDim
        }
        val dotAnim by rememberInfiniteTransition(label = "aiDot").animateFloat(
            initialValue = 1f, targetValue = if (ui.aiState != AiState.WAITING) 0.3f else 1f,
            animationSpec = if (ui.aiState != AiState.WAITING)
                infiniteRepeatable(tween(900)) else snap(),
            label = "aiDotAnim"
        )
        Surface(
            color  = badgeBg,
            shape  = RoundedCornerShape(10.dp),
            border = BorderStroke(1.dp, badgeBorder),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                Canvas(Modifier.size(7.dp)) {
                    drawCircle(dotColor.copy(alpha = dotAnim))
                }
                Text(stateText, style = MaterialTheme.typography.bodySmall,
                    color = when (ui.aiState) {
                        AiState.LISTENING -> Green
                        AiState.SPEAKING, AiState.THINKING -> Accent
                        else -> TextMuted
                    },
                    fontWeight = FontWeight.Medium,
                )
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  CONVERSATION PANEL
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun ConversationPanel(
    turns:   List<ConversationTurn>,
    onClear: () -> Unit,
) {
    val listState = rememberLazyListState()

    // Auto-scroll to bottom on new messages
    LaunchedEffect(turns.size) {
        if (turns.isNotEmpty()) listState.animateScrollToItem(turns.size - 1)
    }

    Column(Modifier.fillMaxSize()) {
        // Header
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp)
                .border(BorderStroke(0.dp, Color.Transparent)),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment     = Alignment.CenterVertically,
        ) {
            Text(
                "Live Session",
                style    = MaterialTheme.typography.labelSmall,
                color    = TextDim,
                fontWeight = FontWeight.Bold,
                letterSpacing = 1.sp,
            )
            TextButton(
                onClick = onClear,
                contentPadding = PaddingValues(horizontal = 10.dp, vertical = 4.dp),
            ) {
                Text("Clear", style = MaterialTheme.typography.bodySmall, color = TextDim)
            }
        }
        Divider(color = Border1, thickness = 1.dp)

        LazyColumn(
            state            = listState,
            modifier         = Modifier.fillMaxSize(),
            contentPadding   = PaddingValues(horizontal = 16.dp, vertical = 14.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            items(turns, key = { it.id }) { turn ->
                AnimatedVisibility(
                    visible = true,
                    enter   = fadeIn() + slideInVertically(initialOffsetY = { 20 }),
                ) {
                    ConversationTurnItem(turn)
                }
            }
        }
    }
}

@Composable
fun ConversationTurnItem(turn: ConversationTurn) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        // User bubble
        if (turn.userText != null || (turn.aiText == null && !turn.isStreamingAi)) {
            Column(
                modifier          = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.End,
            ) {
                Text(
                    "You",
                    style    = MaterialTheme.typography.labelSmall,
                    color    = TextDim,
                    modifier = Modifier.padding(end = 4.dp, bottom = 2.dp),
                    fontSize = 9.sp,
                    letterSpacing = 1.sp,
                )
                Surface(
                    shape  = RoundedCornerShape(12.dp, 4.dp, 12.dp, 12.dp),
                    color  = AccentDim,
                    border = BorderStroke(1.dp, Accent.copy(alpha = 0.2f)),
                    modifier = Modifier.widthIn(max = 280.dp),
                ) {
                    if (turn.userText == null) {
                        // Pending state
                        Row(
                            modifier = Modifier.padding(12.dp, 10.dp),
                            verticalAlignment = Alignment.CenterVertically,
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            PulsingDot(Accent)
                            Text(
                                "Speaking…",
                                style     = MaterialTheme.typography.bodyMedium,
                                color     = TextMuted,
                                fontStyle = androidx.compose.ui.text.font.FontStyle.Italic,
                            )
                        }
                    } else {
                        Text(
                            turn.userText,
                            style    = MaterialTheme.typography.bodyMedium,
                            color    = TextPrimary,
                            modifier = Modifier.padding(12.dp, 10.dp),
                        )
                    }
                }
            }
        }

        // AI bubble
        if (turn.aiText != null || turn.isStreamingAi) {
            Column(
                modifier          = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.Start,
            ) {
                Text(
                    "flow.ai",
                    style    = MaterialTheme.typography.labelSmall,
                    color    = TextDim,
                    modifier = Modifier.padding(start = 4.dp, bottom = 2.dp),
                    fontSize = 9.sp,
                    letterSpacing = 1.sp,
                )
                Surface(
                    shape  = RoundedCornerShape(4.dp, 12.dp, 12.dp, 12.dp),
                    color  = Surface2,
                    border = BorderStroke(1.dp, Border1),
                    modifier = Modifier.widthIn(max = 280.dp),
                ) {
                    Row(
                        modifier = Modifier.padding(12.dp, 10.dp),
                        horizontalArrangement = Arrangement.spacedBy(4.dp),
                        verticalAlignment = Alignment.Bottom,
                    ) {
                        Text(
                            text  = turn.aiText ?: "",
                            style = MaterialTheme.typography.bodyMedium,
                            color = TextPrimary,
                            modifier = Modifier.weight(1f, fill = false),
                        )
                        if (turn.isStreamingAi) {
                            PulsingDot(Accent, modifier = Modifier.padding(bottom = 2.dp))
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun PulsingDot(color: Color, modifier: Modifier = Modifier) {
    val alpha by rememberInfiniteTransition(label = "pd").animateFloat(
        initialValue = 1f, targetValue = 0.2f,
        animationSpec = infiniteRepeatable(tween(700, easing = EaseInOutQuad),
            RepeatMode.Reverse),
        label = "pdAlpha"
    )
    Canvas(modifier.size(8.dp)) { drawCircle(color.copy(alpha = alpha)) }
}

// ═══════════════════════════════════════════════════════════════════════════
//  IDLE PLACEHOLDER
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun IdlePlaceholder(isConnected: Boolean) {
    Box(
        modifier          = Modifier.fillMaxSize(),
        contentAlignment  = Alignment.Center,
    ) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Surface(
                shape  = CircleShape,
                color  = Surface1,
                border = BorderStroke(1.5.dp, Border2),
                modifier = Modifier.size(64.dp),
            ) {
                Box(contentAlignment = Alignment.Center, modifier = Modifier.fillMaxSize()) {
                    Text(if (isConnected) "🎙" else "📡", fontSize = 24.sp)
                }
            }
            Text(
                if (isConnected) "Waiting for wake word…" else "Ready when you are",
                style     = MaterialTheme.typography.titleMedium,
                color     = TextMuted,
                fontWeight = FontWeight.Bold,
            )
            Text(
                if (isConnected) "Say the wake word to start a conversation."
                else             "Connect and say the wake word to start a session.",
                style = MaterialTheme.typography.bodySmall,
                color = TextDim,
            )
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SHARED COMPOSABLES
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun PanelSection(title: String, content: @Composable ColumnScope.() -> Unit) {
    Surface(
        shape  = RoundedCornerShape(14.dp),
        color  = Surface1,
        border = BorderStroke(1.dp, Border1),
    ) {
        Column(
            modifier = Modifier.fillMaxWidth().padding(12.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                title.uppercase(),
                style         = MaterialTheme.typography.labelSmall,
                color         = TextDim,
                fontWeight    = FontWeight.Bold,
                letterSpacing = 1.sp,
                modifier      = Modifier.padding(bottom = 2.dp),
            )
            content()
        }
    }
}

@Composable
fun LabeledField(label: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(3.dp)) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = TextMuted, fontSize = 10.sp)
        content()
    }
}

@Composable
fun FlowInput(
    value:         String,
    onValueChange: (String) -> Unit,
    isNumber:      Boolean = false,
) {
    OutlinedTextField(
        value         = value,
        onValueChange = onValueChange,
        singleLine    = true,
        modifier      = Modifier.fillMaxWidth(),
        shape         = RoundedCornerShape(8.dp),
        textStyle     = MaterialTheme.typography.bodySmall.copy(
            color      = TextPrimary,
            fontFamily = if (isNumber) FontFamily.Monospace else FontFamily.Default,
        ),
        colors = OutlinedTextFieldDefaults.colors(
            unfocusedBorderColor  = Border1,
            focusedBorderColor    = Accent,
            unfocusedContainerColor = Surface1,
            focusedContainerColor   = Surface2,
            cursorColor             = Accent,
        ),
        keyboardOptions = if (isNumber)
            androidx.compose.foundation.text.KeyboardOptions(
                keyboardType = androidx.compose.ui.text.input.KeyboardType.Number)
        else
            androidx.compose.foundation.text.KeyboardOptions.Default,
    )
}

@Composable
fun StatRow(label: String, value: String) {
    Row(
        modifier              = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment     = Alignment.CenterVertically,
    ) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = TextMuted)
        Text(value, style = MaterialTheme.typography.labelSmall, color = TextPrimary,
            fontFamily = FontFamily.Monospace)
    }
}
