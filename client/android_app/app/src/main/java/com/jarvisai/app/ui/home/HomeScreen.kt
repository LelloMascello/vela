package com.jarvisai.app.ui.home

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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.jarvisai.app.data.ConversationTurn
import com.jarvisai.app.ui.theme.*
import kotlin.math.*

@Composable
fun HomeScreen(
    viewModel: HomeViewModel,
) {
    val ui by viewModel.uiState.collectAsState()

    var routerHost  by remember { mutableStateOf("192.168.178.136:8000") }
    var routerFrame by remember { mutableStateOf("1280") }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDeep),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        // ── Main Content Area (Conversation or Idle) ──────────────────
        Box(
            modifier = Modifier
                .weight(1f)
                .fillMaxWidth(),
            contentAlignment = Alignment.Center
        ) {
            if (ui.phase != Phase.MAIN || ui.conversation.isEmpty()) {
                IdleState(isConnected = ui.phase != Phase.IDLE)
            } else {
                ConversationPanel(
                    turns   = ui.conversation,
                    onClear = { viewModel.clearConversationPublic() }
                )
            }
        }

        // ── Audio Intensity Line (The "Visualizer") ───────────────────
        AudioIntensityLine(
            amplitude = ui.currentAmplitude,
            isActive  = ui.phase != Phase.IDLE,
            phase     = ui.phase
        )

        // ── Bottom Settings & Timer ──────────────────────────────────
        Surface(
            modifier = Modifier.fillMaxWidth(),
            color    = Surface1,
            border   = BorderStroke(1.dp, Border1),
            shape    = RoundedCornerShape(topStart = 24.dp, topEnd = 24.dp)
        ) {
            Column(
                modifier = Modifier.padding(24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp)
            ) {
                // Connection Row
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("IP ADDRESS", style = MaterialTheme.typography.labelSmall, color = TextDim, letterSpacing = 1.sp)
                        Spacer(Modifier.height(4.dp))
                        FlowInput(routerHost, onValueChange = { routerHost = it })
                    }
                    Column(modifier = Modifier.weight(0.5f)) {
                        Text("BUFFER", style = MaterialTheme.typography.labelSmall, color = TextDim, letterSpacing = 1.sp)
                        Spacer(Modifier.height(4.dp))
                        FlowInput(routerFrame, onValueChange = { routerFrame = it }, isNumber = true)
                    }
                }

                // Controls & Timer
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    if (ui.phase == Phase.IDLE) {
                        Button(
                            onClick = { viewModel.connect(routerHost, routerFrame.toIntOrNull() ?: 1280) },
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = Accent),
                            modifier = Modifier.height(48.dp).weight(1f)
                        ) {
                            Text("CONNECT SYSTEM", fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                        }
                    } else {
                        Button(
                            onClick = { viewModel.disconnect() },
                            shape = RoundedCornerShape(12.dp),
                            colors = ButtonDefaults.buttonColors(containerColor = RedDim, contentColor = Red),
                            border = BorderStroke(1.dp, Red.copy(alpha = 0.3f)),
                            modifier = Modifier.height(48.dp).weight(1f)
                        ) {
                            Text("DISCONNECT", fontWeight = FontWeight.Bold, letterSpacing = 1.sp)
                        }
                    }

                    if (ui.phase == Phase.MAIN) {
                        Spacer(Modifier.width(12.dp))
                        Surface(
                            color = Surface2,
                            shape = RoundedCornerShape(12.dp),
                            border = BorderStroke(1.dp, Border1),
                            modifier = Modifier.height(48.dp)
                        ) {
                            Row(
                                modifier = Modifier.padding(horizontal = 16.dp),
                                verticalAlignment = Alignment.CenterVertically,
                                horizontalArrangement = Arrangement.spacedBy(8.dp)
                            ) {
                                Text("TIMER", style = MaterialTheme.typography.labelSmall, color = TextDim)
                                Text(
                                    "${ceil(ui.silenceLeft).toInt()}s",
                                    style = MaterialTheme.typography.bodyMedium,
                                    color = if (ui.silenceLeft < 3f) Red else Accent,
                                    fontWeight = FontWeight.Bold,
                                    fontFamily = FontFamily.Monospace
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  AUDIO INTENSITY LINE
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun AudioIntensityLine(amplitude: Float, isActive: Boolean, phase: Phase) {
    val animatedAmplitude by animateFloatAsState(
        targetValue = if (isActive) amplitude else 0f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioNoBouncy, stiffness = Spring.StiffnessMedium),
        label = "amplitude"
    )

    val color = when (phase) {
        Phase.MAIN -> Accent
        Phase.ROUTER -> Sky
        else -> TextDim
    }

    Box(
        modifier = Modifier
            .fillMaxWidth()
            .height(80.dp),
        contentAlignment = Alignment.Center
    ) {
        Canvas(modifier = Modifier.fillMaxWidth(0.8f).height(4.dp)) {
            val width = size.width
            val height = size.height
            val centerY = height / 2

            // Base line
            drawLine(
                color = color.copy(alpha = 0.2f),
                start = Offset(0f, centerY),
                end = Offset(width, centerY),
                strokeWidth = 2.dp.toPx(),
                cap = StrokeCap.Round
            )

            // Active Intensity Line
            val intensityWidth = width * animatedAmplitude
            val startX = (width - intensityWidth) / 2
            
            if (animatedAmplitude > 0.01f) {
                // Glow effect
                drawRect(
                    brush = Brush.horizontalGradient(
                        colors = listOf(Color.Transparent, color, Color.Transparent),
                        startX = startX,
                        endX = startX + intensityWidth
                    ),
                    topLeft = Offset(startX, centerY - 4.dp.toPx()),
                    size = Size(intensityWidth, 8.dp.toPx()),
                    alpha = 0.3f
                )

                drawLine(
                    color = color,
                    start = Offset(startX, centerY),
                    end = Offset(startX + intensityWidth, centerY),
                    strokeWidth = (2.dp + (4.dp * animatedAmplitude)).toPx(),
                    cap = StrokeCap.Round
                )
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  IDLE STATE
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun IdleState(isConnected: Boolean) {
    Column(
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        Text(
            if (isConnected) "SYSTEM ACTIVE" else "SYSTEM OFFLINE",
            style = MaterialTheme.typography.titleMedium,
            color = if (isConnected) Green else TextDim,
            fontWeight = FontWeight.Black,
            letterSpacing = 4.sp
        )
        Text(
            if (isConnected) "Waiting for wake word..." else "Initialize connection to start",
            style = MaterialTheme.typography.bodySmall,
            color = TextMuted
        )
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

    LaunchedEffect(turns.size) {
        if (turns.isNotEmpty()) listState.animateScrollToItem(turns.size - 1)
    }

    Column(Modifier.fillMaxSize()) {
        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 24.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text("LIVE SESSION", style = MaterialTheme.typography.labelSmall, color = TextDim, fontWeight = FontWeight.Bold, letterSpacing = 2.sp)
            TextButton(onClick = onClear) {
                Text("CLEAR", style = MaterialTheme.typography.labelSmall, color = TextDim)
            }
        }
        
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            items(turns, key = { it.id }) { turn ->
                ConversationTurnItem(turn)
            }
        }
    }
}

@Composable
fun ConversationTurnItem(turn: ConversationTurn) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // --- USER MESSAGE ---
        Box(
            modifier = Modifier.fillMaxWidth(),
            contentAlignment = Alignment.CenterEnd
        ) {
            Surface(
                color = Surface2,
                shape = RoundedCornerShape(16.dp, 16.dp, 2.dp, 16.dp),
                border = BorderStroke(1.dp, Border1)
            ) {
                Text(
                    text = turn.userText ?: "trascrizione in corso...",
                    modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                    style = MaterialTheme.typography.bodyMedium,
                    color = if (turn.userText == null) TextDim else TextPrimary,
                )
            }
        }

        // --- AI MESSAGE ---
        if (turn.aiText != null || turn.isStreamingAi) {
            Box(
                modifier = Modifier.fillMaxWidth(),
                contentAlignment = Alignment.CenterStart
            ) {
                Surface(
                    color = Accent.copy(alpha = 0.1f),
                    shape = RoundedCornerShape(16.dp, 16.dp, 16.dp, 2.dp),
                    border = BorderStroke(1.dp, Accent.copy(alpha = 0.2f))
                ) {
                    val isPlaceholder = turn.aiText.isNullOrEmpty() && turn.isStreamingAi
                    Text(
                        text = if (isPlaceholder) "sto rispondendo..." else turn.aiText ?: "",
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
                        style = MaterialTheme.typography.bodyMedium,
                        color = if (isPlaceholder) Accent.copy(alpha = 0.7f) else Accent,
                    )
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  INPUT COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

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
        shape         = RoundedCornerShape(12.dp),
        textStyle     = MaterialTheme.typography.bodySmall.copy(
            color      = TextPrimary,
            fontFamily = if (isNumber) FontFamily.Monospace else FontFamily.Default,
        ),
        colors = OutlinedTextFieldDefaults.colors(
            unfocusedBorderColor    = Border1,
            focusedBorderColor      = Accent,
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
