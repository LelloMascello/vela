package com.flowai.app.ui.chats

import androidx.compose.animation.*
import androidx.compose.animation.core.tween
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.flowai.app.data.ChatMessage
import com.flowai.app.data.ChatSession
import com.flowai.app.ui.theme.*
import java.text.SimpleDateFormat
import java.util.*

@Composable
fun ChatsScreen(
    viewModel:     ChatsViewModel,
    username:      String,
    onNavigateHome: () -> Unit,
    onLogout:      () -> Unit,
) {
    val ui    by viewModel.uiState.collectAsState()
    val focus = LocalFocusManager.current

    Scaffold(
        containerColor = BgDeep,
        topBar = {
            ChatsTopBar(
                username        = username,
                onNavigateHome  = onNavigateHome,
                onLogout        = onLogout,
                onRefresh       = { viewModel.load() },
            )
        },
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            // ── Toolbar ───────────────────────────────────────────────────
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(horizontal = 16.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(10.dp),
            ) {
                // Search field
                OutlinedTextField(
                    value         = ui.query,
                    onValueChange = { viewModel.search(it) },
                    modifier      = Modifier.weight(1f),
                    placeholder   = { Text("Search sessions…", color = TextDim,
                        style = MaterialTheme.typography.bodyMedium) },
                    leadingIcon   = { Text("⌕", fontSize = 16.sp, color = TextDim) },
                    trailingIcon  = if (ui.query.isNotEmpty()) ({
                        IconButton(onClick = { viewModel.clearSearch(); focus.clearFocus() }) {
                            Icon(Icons.Default.Close, contentDescription = "Clear",
                                tint = TextDim, modifier = Modifier.size(16.dp))
                        }
                    }) else null,
                    singleLine    = true,
                    shape         = RoundedCornerShape(12.dp),
                    colors        = OutlinedTextFieldDefaults.colors(
                        unfocusedBorderColor    = Border1,
                        focusedBorderColor      = Accent,
                        unfocusedContainerColor = Surface1,
                        focusedContainerColor   = Surface2,
                        cursorColor             = Accent,
                        focusedTextColor        = TextPrimary,
                        unfocusedTextColor      = TextPrimary,
                    ),
                    textStyle = MaterialTheme.typography.bodyMedium,
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                    keyboardActions = KeyboardActions(onSearch = { focus.clearFocus() }),
                )

                // Count pill
                if (!ui.isLoading) {
                    Surface(
                        shape  = RoundedCornerShape(999.dp),
                        color  = Surface2,
                        border = BorderStroke(1.dp, Border1),
                    ) {
                        Text(
                            text = if (ui.query.isBlank()) "${ui.sessions.size} session${if (ui.sessions.size != 1) "s" else ""}"
                                   else "${ui.filtered.size} of ${ui.sessions.size}",
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                            style    = MaterialTheme.typography.labelSmall,
                            color    = TextDim,
                            fontFamily = FontFamily.Monospace,
                        )
                    }
                }
            }

            Divider(color = Border1, thickness = 1.dp)

            // ── Content ───────────────────────────────────────────────────
            when {
                ui.isLoading -> {
                    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                        Column(
                            horizontalAlignment = Alignment.CenterHorizontally,
                            verticalArrangement = Arrangement.spacedBy(12.dp),
                        ) {
                            CircularProgressIndicator(color = Accent, strokeWidth = 2.dp,
                                modifier = Modifier.size(28.dp))
                            Text("Loading sessions…", style = MaterialTheme.typography.bodySmall,
                                color = TextDim)
                        }
                    }
                }
                ui.errorMessage.isNotEmpty() -> {
                    EmptyState(icon = "⚠️", message = ui.errorMessage)
                }
                ui.filtered.isEmpty() -> {
                    EmptyState(
                        icon    = if (ui.query.isBlank()) "💬" else "🔍",
                        message = if (ui.query.isBlank())
                            "No sessions yet. Start a voice session to see it here."
                        else
                            "No sessions match \"${ui.query}\"",
                    )
                }
                else -> {
                    LazyColumn(
                        modifier        = Modifier.fillMaxSize(),
                        contentPadding  = PaddingValues(horizontal = 16.dp, vertical = 10.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(ui.filtered, key = { it.hashCode() }) { session ->
                            SessionCard(session = session, query = ui.query)
                        }
                    }
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
fun ChatsTopBar(
    username:       String,
    onNavigateHome: () -> Unit,
    onLogout:       () -> Unit,
    onRefresh:      () -> Unit,
) {
    TopAppBar(
        colors = TopAppBarDefaults.topAppBarColors(containerColor = BgDeep.copy(alpha = 0.95f)),
        modifier = Modifier.border(BorderStroke(1.dp, Border1)),
        title = {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Text("flow.ai", style = MaterialTheme.typography.titleLarge,
                    color = TextPrimary, fontWeight = FontWeight.ExtraBold)
            }
        },
        actions = {
            // Nav links
            TextButton(onClick = onNavigateHome) {
                Text("Home", color = TextMuted, style = MaterialTheme.typography.bodySmall,
                    fontWeight = FontWeight.Medium)
            }
            Surface(
                shape  = RoundedCornerShape(999.dp),
                color  = Surface2,
                border = BorderStroke(1.dp, Border2),
                modifier = Modifier.padding(end = 4.dp),
            ) {
                Text(
                    "Chats",
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                    style    = MaterialTheme.typography.bodySmall,
                    color    = TextPrimary,
                    fontWeight = FontWeight.SemiBold,
                )
            }
            // Username
            Surface(
                shape  = RoundedCornerShape(999.dp),
                color  = Surface2,
                border = BorderStroke(1.dp, Border1),
                modifier = Modifier.padding(end = 4.dp),
            ) {
                Text(
                    username,
                    modifier = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                    style    = MaterialTheme.typography.labelSmall,
                    color    = TextMuted,
                    fontFamily = FontFamily.Monospace,
                )
            }
            // Refresh
            IconButton(onClick = onRefresh) {
                Icon(Icons.Default.Refresh, contentDescription = "Refresh",
                    tint = TextDim, modifier = Modifier.size(18.dp))
            }
            // Logout
            TextButton(onClick = onLogout) {
                Text("Logout", color = Red.copy(alpha = 0.8f),
                    style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.width(4.dp))
        }
    )
}

// ═══════════════════════════════════════════════════════════════════════════
//  SESSION CARD  (expandable)
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun SessionCard(session: ChatSession, query: String) {
    var expanded by remember { mutableStateOf(false) }

    val msgs      = session.chat
    val aiCount   = msgs.count { it.role == "assistant" }
    val title     = sessionTitle(session)
    val preview   = previewText(session)
    val dateStr   = formatDate(session)

    Surface(
        shape    = RoundedCornerShape(14.dp),
        color    = Surface1,
        border   = BorderStroke(1.dp, if (expanded) Border2 else Border1),
        modifier = Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded },
    ) {
        Column {
            // ── Card header ───────────────────────────────────────────────
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(14.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment     = Alignment.Top,
            ) {
                // Left: title + preview
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    HighlightedText(
                        text    = title,
                        query   = query,
                        style   = MaterialTheme.typography.bodyMedium.copy(
                            fontWeight = FontWeight.SemiBold, color = TextPrimary),
                        maxLines = 1,
                    )
                    HighlightedText(
                        text    = preview,
                        query   = query,
                        style   = MaterialTheme.typography.bodySmall.copy(color = TextMuted),
                        maxLines = 1,
                    )
                }

                // Right: date + badge + chevron
                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(
                        dateStr,
                        style  = MaterialTheme.typography.labelSmall,
                        color  = TextDim,
                        fontFamily = FontFamily.Monospace,
                        fontSize   = 9.sp,
                    )
                    Surface(
                        shape  = RoundedCornerShape(999.dp),
                        color  = SkyDim,
                        border = BorderStroke(1.dp, Sky.copy(alpha = 0.2f)),
                    ) {
                        Text(
                            "$aiCount turn${if (aiCount != 1) "s" else ""}",
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                            style    = MaterialTheme.typography.labelSmall,
                            color    = Sky,
                            fontSize = 9.sp,
                        )
                    }
                    // Chevron
                    val rotation by animateFloatAsState(
                        targetValue = if (expanded) 180f else 0f,
                        animationSpec = tween(200), label = "chevron"
                    )
                    Text(
                        "▾",
                        color    = TextDim,
                        fontSize = 10.sp,
                        modifier = Modifier.graphicsLayer(rotationZ = rotation),
                    )
                }
            }

            // ── Expanded thread ───────────────────────────────────────────
            AnimatedVisibility(
                visible = expanded,
                enter   = expandVertically(tween(220)) + fadeIn(tween(220)),
                exit    = shrinkVertically(tween(180)) + fadeOut(tween(180)),
            ) {
                Column {
                    Divider(color = Border1, thickness = 1.dp)
                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        if (msgs.isEmpty()) {
                            Text("No messages in this session.",
                                style = MaterialTheme.typography.bodySmall, color = TextDim)
                        } else {
                            msgs.forEach { msg -> MessageBubble(msg, query) }
                        }
                    }
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  MESSAGE BUBBLE
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun MessageBubble(msg: ChatMessage, query: String) {
    val isUser = msg.role == "user"
    Column(
        modifier          = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Text(
            text     = if (isUser) "You" else "flow.ai",
            style    = MaterialTheme.typography.labelSmall,
            color    = TextDim,
            modifier = Modifier.padding(
                start = if (!isUser) 4.dp else 0.dp,
                end   = if (isUser) 4.dp else 0.dp,
                bottom = 3.dp,
            ),
            fontSize      = 9.sp,
            letterSpacing = 1.sp,
        )
        Surface(
            shape  = if (isUser) RoundedCornerShape(12.dp, 4.dp, 12.dp, 12.dp)
                     else        RoundedCornerShape(4.dp, 12.dp, 12.dp, 12.dp),
            color  = if (isUser) AccentDim else Surface2,
            border = BorderStroke(
                1.dp,
                if (isUser) Accent.copy(alpha = 0.2f) else Border1
            ),
            modifier = Modifier.widthIn(max = 300.dp),
        ) {
            HighlightedText(
                text    = msg.content.trim().ifEmpty { "(empty)" },
                query   = query,
                style   = MaterialTheme.typography.bodySmall.copy(
                    color      = TextPrimary,
                    lineHeight = 20.sp,
                ),
                modifier = Modifier.padding(12.dp, 8.dp),
            )
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  HIGHLIGHTED TEXT  (fuzzy match highlight)
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun HighlightedText(
    text:     String,
    query:    String,
    style:    androidx.compose.ui.text.TextStyle,
    maxLines: Int = Int.MAX_VALUE,
    modifier: Modifier = Modifier,
) {
    if (query.isBlank()) {
        Text(text, style = style, maxLines = maxLines,
            overflow = TextOverflow.Ellipsis, modifier = modifier)
        return
    }

    val lower = text.lowercase()
    val pat   = query.trim().lowercase()
    val idx   = lower.indexOf(pat)

    if (idx < 0) {
        Text(text, style = style, maxLines = maxLines,
            overflow = TextOverflow.Ellipsis, modifier = modifier)
        return
    }

    val annotated = buildAnnotatedString {
        append(text.substring(0, idx))
        pushStyle(
            androidx.compose.ui.text.SpanStyle(
                background = AccentDim,
                color      = Accent,
            )
        )
        append(text.substring(idx, idx + pat.length))
        pop()
        append(text.substring(idx + pat.length))
    }

    Text(annotated, style = style, maxLines = maxLines,
        overflow = TextOverflow.Ellipsis, modifier = modifier)
}

// ═══════════════════════════════════════════════════════════════════════════
//  EMPTY STATE
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun EmptyState(icon: String, message: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Column(
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(10.dp),
            modifier = Modifier.padding(32.dp),
        ) {
            Text(icon, fontSize = 32.sp)
            Text(message,
                style     = MaterialTheme.typography.bodyMedium,
                color     = TextDim,
                textAlign = androidx.compose.ui.text.style.TextAlign.Center,
            )
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  DATA HELPERS
// ═══════════════════════════════════════════════════════════════════════════

private fun sessionTitle(doc: ChatSession): String {
    val first = doc.chat.firstOrNull { it.role == "user" }
    if (first != null && first.content.isNotBlank()) {
        val t = first.content.trim()
        return if (t.length > 70) t.take(70) + "…" else t
    }
    return "Voice session"
}

private fun previewText(doc: ChatSession): String {
    if (doc.chat.isEmpty()) return "No messages"
    val last = doc.chat.last()
    val text = last.content.trim()
    return if (text.length > 120) text.take(120) + "…" else text.ifEmpty { "No messages" }
}

private val sdf = SimpleDateFormat("d MMM yyyy · HH:mm", Locale.getDefault())

private fun formatDate(doc: ChatSession): String {
    val raw = doc.createdAt ?: return ""
    val ms: Long = when (raw) {
        is Long   -> raw
        is Double -> raw.toLong()
        is Map<*, *> -> (raw["\$date"] as? Long) ?: return ""
        else      -> return ""
    }
    return if (ms > 0) sdf.format(Date(ms)) else ""
}

// Needed for graphicsLayer rotation
private val animateFloatAsState = @Composable { targetValue: Float, animationSpec: androidx.compose.animation.core.AnimationSpec<Float>, label: String ->
    androidx.compose.animation.core.animateFloatAsState(
        targetValue   = targetValue,
        animationSpec = animationSpec,
        label         = label,
    )
}
