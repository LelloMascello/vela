package com.flowai.app.ui.auth

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.flowai.app.ui.theme.*

@Composable
fun AuthScreen(
    viewModel:    AuthViewModel,
    onNavigateHome: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsState()
    val focus   = LocalFocusManager.current

    var tab      by remember { mutableStateOf(0) } // 0 = Login, 1 = Sign Up
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var showPwd  by remember { mutableStateOf(false) }

    // Navigation side-effect
    LaunchedEffect(uiState.navigateHome) {
        if (uiState.navigateHome) {
            viewModel.clearNavigation()
            onNavigateHome()
        }
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(BgDeep),
        contentAlignment = Alignment.Center,
    ) {
        // Subtle glow
        Box(
            modifier = Modifier
                .size(400.dp)
                .offset(y = (-60).dp)
                .background(
                    brush = androidx.compose.ui.graphics.Brush.radialGradient(
                        listOf(AccentGlow, androidx.compose.ui.graphics.Color.Transparent)
                    )
                )
        )

        Card(
            modifier = Modifier
                .fillMaxWidth()
                .padding(24.dp),
            shape = RoundedCornerShape(26.dp),
            colors = CardDefaults.cardColors(containerColor = Surface2),
            elevation = CardDefaults.cardElevation(0.dp),
            border = androidx.compose.foundation.BorderStroke(1.dp, Border1),
        ) {
            Column(
                modifier = Modifier.padding(28.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(0.dp),
            ) {

                // ── Logo ─────────────────────────────────────────────────
                Text(
                    text      = "flow.ai",
                    style     = MaterialTheme.typography.displayLarge,
                    color     = TextPrimary,
                    letterSpacing = (-1).sp,
                )
                Text(
                    text  = "Your voice, amplified by intelligence.",
                    style = MaterialTheme.typography.bodySmall,
                    color = TextDim,
                    modifier = Modifier.padding(top = 4.dp, bottom = 24.dp),
                )

                // ── Tab selector ──────────────────────────────────────────
                FlowTabRow(
                    selected = tab,
                    labels   = listOf("Sign in", "Create account"),
                    onSelect = {
                        tab      = it
                        username = ""
                        password = ""
                    },
                )

                Spacer(Modifier.height(20.dp))

                // ── Fields ────────────────────────────────────────────────
                FlowTextField(
                    value         = username,
                    onValueChange = { username = it },
                    label         = "Username",
                    placeholder   = "your_username",
                    imeAction     = ImeAction.Next,
                    keyboardActions = KeyboardActions(onNext = { focus.moveFocus(FocusDirection.Down) }),
                )
                Spacer(Modifier.height(10.dp))
                FlowTextField(
                    value         = password,
                    onValueChange = { password = it },
                    label         = "Password",
                    placeholder   = "••••••••",
                    isPassword    = true,
                    showPassword  = showPwd,
                    onToggleShow  = { showPwd = !showPwd },
                    imeAction     = ImeAction.Done,
                    keyboardActions = KeyboardActions(onDone = {
                        focus.clearFocus()
                        if (tab == 0) viewModel.login(username, password)
                        else          viewModel.signup(username, password)
                    }),
                )

                Spacer(Modifier.height(16.dp))

                // ── Submit ────────────────────────────────────────────────
                Button(
                    onClick = {
                        focus.clearFocus()
                        if (tab == 0) viewModel.login(username, password)
                        else          viewModel.signup(username, password)
                    },
                    modifier = Modifier.fillMaxWidth(),
                    enabled  = !uiState.isLoading,
                    shape    = RoundedCornerShape(12.dp),
                    colors   = ButtonDefaults.buttonColors(
                        containerColor     = Accent,
                        disabledContainerColor = Accent.copy(alpha = 0.4f),
                    ),
                    contentPadding = PaddingValues(vertical = 14.dp),
                ) {
                    if (uiState.isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            color    = androidx.compose.ui.graphics.Color.White,
                            strokeWidth = 2.dp,
                        )
                    } else {
                        Text(
                            text  = if (tab == 0) "Sign in" else "Create account",
                            style = MaterialTheme.typography.bodyLarge,
                            color = androidx.compose.ui.graphics.Color.White,
                        )
                    }
                }

                // ── Message ───────────────────────────────────────────────
                AnimatedVisibility(visible = uiState.message.isNotEmpty()) {
                    val bg  = if (uiState.isError) RedDim   else GreenDim
                    val fg  = if (uiState.isError) Red      else Green
                    Box(
                        modifier = Modifier
                            .padding(top = 12.dp)
                            .fillMaxWidth()
                            .clip(RoundedCornerShape(8.dp))
                            .background(bg)
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                    ) {
                        Text(
                            text      = uiState.message,
                            style     = MaterialTheme.typography.bodySmall,
                            color     = fg,
                            textAlign = TextAlign.Center,
                            modifier  = Modifier.fillMaxWidth(),
                        )
                    }
                }
            }
        }
    }
}

// ── Reusable components ───────────────────────────────────────────────────

@Composable
fun FlowTabRow(
    selected: Int,
    labels:   List<String>,
    onSelect: (Int) -> Unit,
) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(12.dp))
            .background(Surface1)
            .padding(4.dp),
    ) {
        labels.forEachIndexed { i, label ->
            val active = i == selected
            Box(
                modifier = Modifier
                    .weight(1f)
                    .clip(RoundedCornerShape(8.dp))
                    .background(if (active) BgSurface else androidx.compose.ui.graphics.Color.Transparent)
                    .then(if (!active) Modifier else Modifier),
                contentAlignment = Alignment.Center,
            ) {
                TextButton(
                    onClick  = { onSelect(i) },
                    modifier = Modifier.fillMaxWidth(),
                    colors   = ButtonDefaults.textButtonColors(
                        contentColor = if (active) TextPrimary else TextDim,
                    ),
                    contentPadding = PaddingValues(vertical = 8.dp),
                ) {
                    Text(label, style = MaterialTheme.typography.bodyMedium,
                        fontWeight = if (active) androidx.compose.ui.text.font.FontWeight.SemiBold
                        else androidx.compose.ui.text.font.FontWeight.Normal)
                }
            }
        }
    }
}

@Composable
fun FlowTextField(
    value:           String,
    onValueChange:   (String) -> Unit,
    label:           String,
    placeholder:     String,
    isPassword:      Boolean = false,
    showPassword:    Boolean = false,
    onToggleShow:    (() -> Unit)? = null,
    imeAction:       ImeAction = ImeAction.Next,
    keyboardActions: KeyboardActions = KeyboardActions.Default,
) {
    val visual = if (isPassword && !showPassword)
        PasswordVisualTransformation() else VisualTransformation.None

    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(label, style = MaterialTheme.typography.bodySmall, color = TextMuted)
        OutlinedTextField(
            value         = value,
            onValueChange = onValueChange,
            placeholder   = { Text(placeholder, color = TextDim) },
            visualTransformation = visual,
            singleLine    = true,
            modifier      = Modifier.fillMaxWidth(),
            shape         = RoundedCornerShape(12.dp),
            colors        = OutlinedTextFieldDefaults.colors(
                unfocusedBorderColor  = Border1,
                focusedBorderColor    = Accent,
                unfocusedContainerColor = Surface1,
                focusedContainerColor   = Surface2,
                cursorColor             = Accent,
                focusedTextColor        = TextPrimary,
                unfocusedTextColor      = TextPrimary,
            ),
            trailingIcon  = if (isPassword && onToggleShow != null) ({
                IconButton(onClick = onToggleShow) {
                    Text(
                        text  = if (showPassword) "🙈" else "👁",
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }) else null,
            keyboardOptions = KeyboardOptions(imeAction = imeAction),
            keyboardActions = keyboardActions,
        )
    }
}
