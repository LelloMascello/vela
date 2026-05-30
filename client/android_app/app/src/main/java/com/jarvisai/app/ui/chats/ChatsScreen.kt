package com.jarvisai.app.ui.chats

import androidx.compose.animation.*
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.*
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.jarvisai.app.data.ChatMessage
import com.jarvisai.app.data.ChatSession
import com.jarvisai.app.ui.theme.*
import java.text.SimpleDateFormat
import java.util.*

@Composable
fun ChatsScreen(
    viewModel:      ChatsViewModel,
    onContinue:     (ChatSession) -> Unit,
) {
    val ui    by viewModel.uiState.collectAsState()
    val focus = LocalFocusManager.current

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDeep),
    ) {
        // ── Toolbar ───────────────────────────────────────────────────
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 16.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            OutlinedTextField(
                value         = ui.query,
                onValueChange = { viewModel.search(it) },
                modifier      = Modifier.weight(1f),
                placeholder   = {
                    Text("Cerca sessioni…", color = TextDim,
                        style = MaterialTheme.typography.bodyMedium)
                },
                leadingIcon  = { Text("⌕", fontSize = 16.sp, color = TextDim) },
                trailingIcon = if (ui.query.isNotEmpty()) ({
                    IconButton(onClick = { viewModel.clearSearch(); focus.clearFocus() }) {
                        Icon(Icons.Default.Close, contentDescription = "Clear",
                            tint = TextDim, modifier = Modifier.size(16.dp))
                    }
                }) else null,
                singleLine    = true,
                shape         = RoundedCornerShape(12.dp),
                colors = OutlinedTextFieldDefaults.colors(
                    unfocusedBorderColor    = Border1,
                    focusedBorderColor      = Accent,
                    unfocusedContainerColor = Surface1,
                    focusedContainerColor   = Surface2,
                    cursorColor             = Accent,
                    focusedTextColor        = TextPrimary,
                    unfocusedTextColor      = TextPrimary,
                ),
                textStyle       = MaterialTheme.typography.bodyMedium,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                keyboardActions = KeyboardActions(onSearch = { focus.clearFocus() }),
            )

            if (!ui.isLoading) {
                Surface(
                    shape  = RoundedCornerShape(999.dp),
                    color  = Surface2,
                    border = BorderStroke(1.dp, Border1),
                ) {
                    Text(
                        text = if (ui.query.isBlank())
                            "${ui.sessions.size} session${if (ui.sessions.size != 1) "i" else "e"}"
                        else
                            "${ui.filtered.size} di ${ui.sessions.size}",
                        modifier   = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                        style      = MaterialTheme.typography.labelSmall,
                        color      = TextDim,
                        fontFamily = FontFamily.Monospace,
                    )
                }
            }
        }

        HorizontalDivider(color = Border1, thickness = 1.dp)

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
                        Text("Caricamento sessioni…", style = MaterialTheme.typography.bodySmall,
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
                        "Nessuna sessione ancora. Avvia una sessione vocale per vederla qui."
                    else
                        "Nessuna sessione corrispondente a \"${ui.query}\"",
                )
            }
            else -> {
                LazyColumn(
                    modifier        = Modifier.fillMaxSize(),
                    contentPadding  = PaddingValues(horizontal = 16.dp, vertical = 10.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(ui.filtered, key = { it.resolveId() ?: it.hashCode().toString() }) { session ->
                        SessionCard(
                            session = session,
                            query = ui.query,
                            onDelete = { viewModel.deleteSession(it) },
                            onContinue = { onContinue(session) }
                        )
                    }
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  SESSION CARD  (expandable)
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun SessionCard(
    session: ChatSession,
    query: String,
    onDelete: (String) -> Unit,
    onContinue: () -> Unit,
) {
    var expanded by remember { mutableStateOf(false) }
    var showDeleteConfirm by remember { mutableStateOf(false) }

    val msgs     = session.chat
    val aiCount  = msgs.count { it.role == "assistant" }
    val title    = sessionTitle(session)
    val preview  = previewText(session)
    val dateStr  = formatDate(session)

    if (showDeleteConfirm) {
        AlertDialog(
            onDismissRequest = { showDeleteConfirm = false },
            title = { Text("Elimina sessione") },
            text = { Text("Eliminare permanentemente questa sessione?") },
            confirmButton = {
                TextButton(onClick = {
                    session.resolveId()?.let { onDelete(it) }
                    showDeleteConfirm = false
                }) {
                    Text("ELIMINA", color = Red)
                }
            },
            dismissButton = {
                TextButton(onClick = { showDeleteConfirm = false }) {
                    Text("ANNULLA")
                }
            },
            containerColor = Surface1,
            titleContentColor = TextPrimary,
            textContentColor = TextMuted,
        )
    }

    // Chevron rotation animation
    val chevronRotation by animateFloatAsState(
        targetValue   = if (expanded) 180f else 0f,
        animationSpec = tween(200),
        label         = "chevron",
    )

    Surface(
        shape    = RoundedCornerShape(14.dp),
        color    = Surface1,
        border   = BorderStroke(1.dp, if (expanded) Border2 else Border1),
        modifier = Modifier
            .fillMaxWidth()
            .clickable { expanded = !expanded },
    ) {
        Column {
            // ── Header ────────────────────────────────────────────────────
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(14.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment     = Alignment.Top,
            ) {
                Column(
                    modifier = Modifier.weight(1f),
                    verticalArrangement = Arrangement.spacedBy(4.dp),
                ) {
                    HighlightedText(
                        text     = title,
                        query    = query,
                        style    = MaterialTheme.typography.bodyMedium.copy(
                            fontWeight = FontWeight.SemiBold, color = TextPrimary),
                        maxLines = 1,
                    )
                    HighlightedText(
                        text     = preview,
                        query    = query,
                        style    = MaterialTheme.typography.bodySmall.copy(color = TextMuted),
                        maxLines = 1,
                    )
                }

                Column(
                    horizontalAlignment = Alignment.End,
                    verticalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(dateStr,
                        style      = MaterialTheme.typography.labelSmall,
                        color      = TextDim,
                        fontFamily = FontFamily.Monospace,
                        fontSize   = 9.sp)
                    Surface(
                        shape  = RoundedCornerShape(999.dp),
                        color  = SkyDim,
                        border = BorderStroke(1.dp, Sky.copy(alpha = 0.2f)),
                    ) {
                        Text(
                            "$aiCount turn${if (aiCount != 1) "i" else "o"}",
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 3.dp),
                            style    = MaterialTheme.typography.labelSmall,
                            color    = Sky,
                            fontSize = 9.sp)
                    }
                    Text(
                        "▾",
                        color    = TextDim,
                        fontSize = 10.sp,
                        modifier = Modifier.graphicsLayer(rotationZ = chevronRotation),
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
                    HorizontalDivider(color = Border1, thickness = 1.dp)

                    // Actions Row
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 8.dp),
                        horizontalArrangement = Arrangement.End,
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        TextButton(
                            onClick = onContinue,
                            colors = ButtonDefaults.textButtonColors(contentColor = Accent)
                        ) {
                            Text("▶ CONTINUA", style = MaterialTheme.typography.labelMedium)
                        }
                        Spacer(Modifier.width(8.dp))
                        TextButton(
                            onClick = { showDeleteConfirm = true },
                            colors = ButtonDefaults.textButtonColors(contentColor = Red)
                        ) {
                            Text("🗑 ELIMINA", style = MaterialTheme.typography.labelMedium)
                        }
                    }

                    HorizontalDivider(color = Border1.copy(alpha = 0.5f), thickness = 0.5.dp)

                    Column(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(14.dp),
                        verticalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        if (msgs.isEmpty()) {
                            Text("Nessun messaggio in questa sessione.",
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
        modifier            = Modifier.fillMaxWidth(),
        horizontalAlignment = if (isUser) Alignment.End else Alignment.Start,
    ) {
        Text(
            text     = if (isUser) "Tu" else "jarvis.ai",
            style    = MaterialTheme.typography.labelSmall,
            color    = TextDim,
            modifier = Modifier.padding(
                start  = if (!isUser) 4.dp else 0.dp,
                end    = if (isUser) 4.dp else 0.dp,
                bottom = 3.dp,
            ),
            fontSize      = 9.sp,
            letterSpacing = 1.sp,
        )
        Surface(
            shape  = if (isUser) RoundedCornerShape(12.dp, 4.dp, 12.dp, 12.dp)
                     else        RoundedCornerShape(4.dp, 12.dp, 12.dp, 12.dp),
            color  = if (isUser) AccentDim else Surface2,
            border = BorderStroke(1.dp, if (isUser) Accent.copy(alpha = 0.2f) else Border1),
            modifier = Modifier.widthIn(max = 300.dp),
        ) {
            HighlightedText(
                text     = msg.content.trim().ifEmpty { "(empty)" },
                query    = query,
                style    = MaterialTheme.typography.bodySmall.copy(
                    color      = TextPrimary,
                    lineHeight = 20.sp,
                ),
                modifier = Modifier.padding(12.dp, 8.dp),
            )
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════
//  HIGHLIGHTED TEXT
// ═══════════════════════════════════════════════════════════════════════════

@Composable
fun HighlightedText(
    text:     String,
    query:    String,
    style:    androidx.compose.ui.text.TextStyle,
    maxLines: Int      = Int.MAX_VALUE,
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
        pushStyle(SpanStyle(background = AccentDim, color = Accent))
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
                textAlign = TextAlign.Center)
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

private val dateFormatter = SimpleDateFormat("d MMM yyyy · HH:mm", Locale.getDefault())

private fun formatDate(doc: ChatSession): String {
    val raw = doc.createdAt ?: return ""
    val ms: Long = when (raw) {
        is Long      -> raw
        is Double    -> raw.toLong()
        is Map<*, *> -> (raw["\$date"] as? Long) ?: return ""
        else         -> return ""
    }
    return if (ms > 0) dateFormatter.format(Date(ms)) else ""
}
