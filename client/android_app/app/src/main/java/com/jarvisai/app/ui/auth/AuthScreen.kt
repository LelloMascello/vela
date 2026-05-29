package com.jarvisai.app.ui.auth

import androidx.compose.animation.*
import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusDirection
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.jarvisai.app.ui.theme.*

@Composable
fun AuthScreen(
    viewModel:    AuthViewModel,
    onNavigateHome: () -> Unit,
) {
    val uiState by viewModel.uiState.collectAsState()
    val focus   = LocalFocusManager.current

    var tab      by remember { mutableIntStateOf(0) } // 0 = Login, 1 = Sign Up
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
        contentAlignment = Alignment.TopCenter,
    ) {
        // Futuristic background glow
        Box(
            modifier = Modifier
                .fillMaxSize()
                .background(
                    brush = Brush.radialGradient(
                        colors = listOf(AccentDim, Color.Transparent),
                        center = androidx.compose.ui.geometry.Offset(0f, 0f),
                        radius = 1000f
                    )
                )
        )

        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = 32.dp)
                .padding(top = 64.dp)
                .verticalScroll(rememberScrollState()),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(24.dp)
        ) {
            // ── Logo Section ─────────────────────────────────────────────
            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                Box(contentAlignment = Alignment.Center) {
                    val infiniteTransition = rememberInfiniteTransition(label = "logo")
                    val pulse by infiniteTransition.animateFloat(
                        initialValue = 0.4f,
                        targetValue = 0.8f,
                        animationSpec = infiniteRepeatable(tween(2000), RepeatMode.Reverse),
                        label = "pulse"
                    )
                    Box(
                        modifier = Modifier
                            .size(80.dp)
                            .clip(CircleShape)
                            .background(Accent.copy(alpha = 0.1f * pulse))
                            .border(BorderStroke(1.dp, Accent.copy(alpha = 0.2f * pulse)), CircleShape)
                    )
                    Text(
                        "J",
                        style = MaterialTheme.typography.displayMedium,
                        color = Accent,
                        fontWeight = FontWeight.Black
                    )
                }
                Spacer(Modifier.height(16.dp))
                Text(
                    "JARVIS.AI",
                    style = MaterialTheme.typography.headlineSmall,
                    fontWeight = FontWeight.Black,
                    letterSpacing = 8.sp,
                    color = TextPrimary
                )
                Text(
                    "INTELLIGENT VOICE SYSTEM",
                    style = MaterialTheme.typography.labelSmall,
                    color = TextDim,
                    letterSpacing = 2.sp
                )
            }

            Spacer(Modifier.height(8.dp))

            // ── Form Card ────────────────────────────────────────────────
            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = Surface1,
                shape = RoundedCornerShape(24.dp),
                border = BorderStroke(1.dp, Border1)
            ) {
                Column(
                    modifier = Modifier.padding(24.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp)
                ) {
                    // Tab Selector
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .height(48.dp)
                            .clip(RoundedCornerShape(12.dp))
                            .background(BgDeep.copy(alpha = 0.5f))
                            .padding(4.dp)
                    ) {
                        listOf("LOGIN", "SIGNUP").forEachIndexed { index, label ->
                            val selected = tab == index
                            Box(
                                modifier = Modifier
                                    .weight(1f)
                                    .fillMaxHeight()
                                    .clip(RoundedCornerShape(8.dp))
                                    .background(if (selected) Surface2 else Color.Transparent)
                                    .clickable { tab = index }
                                    .padding(horizontal = 8.dp),
                                contentAlignment = Alignment.Center
                            ) {
                                Text(
                                    label,
                                    style = MaterialTheme.typography.labelSmall,
                                    fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal,
                                    color = if (selected) TextPrimary else TextDim,
                                    letterSpacing = 1.sp
                                )
                            }
                        }
                    }

                    Spacer(Modifier.height(8.dp))

                    // Fields
                    AuthTextField(
                        value = username,
                        onValueChange = { username = it },
                        label = "IDENTIFIER",
                        placeholder = "Enter username",
                        imeAction = ImeAction.Next,
                        keyboardActions = KeyboardActions(onNext = { focus.moveFocus(FocusDirection.Down) })
                    )

                    AuthTextField(
                        value = password,
                        onValueChange = { password = it },
                        label = "ACCESS CODE",
                        placeholder = "••••••••",
                        isPassword = true,
                        showPassword = showPwd,
                        onToggleShow = { showPwd = !showPwd },
                        imeAction = ImeAction.Done,
                        keyboardActions = KeyboardActions(onDone = {
                            focus.clearFocus()
                            if (tab == 0) viewModel.login(username, password)
                            else viewModel.signup(username, password)
                        })
                    )

                    Spacer(Modifier.height(8.dp))

                    // Action Button
                    Button(
                        onClick = {
                            focus.clearFocus()
                            if (tab == 0) viewModel.login(username, password)
                            else viewModel.signup(username, password)
                        },
                        modifier = Modifier.fillMaxWidth().height(56.dp),
                        shape = RoundedCornerShape(16.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = Accent,
                            contentColor = Color.White,
                            disabledContainerColor = Accent.copy(alpha = 0.3f)
                        ),
                        enabled = !uiState.isLoading
                    ) {
                        if (uiState.isLoading) {
                            CircularProgressIndicator(modifier = Modifier.size(24.dp), color = Color.White, strokeWidth = 2.dp)
                        } else {
                            Text(
                                if (tab == 0) "INITIALIZE SESSION" else "CREATE IDENTITY",
                                fontWeight = FontWeight.Black,
                                letterSpacing = 1.sp
                            )
                        }
                    }
                }
            }

            // Error Message
            AnimatedVisibility(
                visible = uiState.message.isNotEmpty(),
                enter = fadeIn() + expandVertically(),
                exit = fadeOut() + shrinkVertically()
            ) {
                Surface(
                    modifier = Modifier.fillMaxWidth(),
                    color = if (uiState.isError) RedDim else GreenDim,
                    border = BorderStroke(1.dp, if (uiState.isError) Red.copy(alpha = 0.3f) else Green.copy(alpha = 0.3f)),
                    shape = RoundedCornerShape(12.dp)
                ) {
                    Text(
                        uiState.message,
                        modifier = Modifier.padding(12.dp),
                        style = MaterialTheme.typography.bodySmall,
                        color = if (uiState.isError) Red else Green,
                        textAlign = TextAlign.Center
                    )
                }
            }
        }
    }
}

@Composable
fun AuthTextField(
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
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            label,
            style = MaterialTheme.typography.labelSmall,
            color = TextMuted,
            letterSpacing = 1.sp,
            fontWeight = FontWeight.Bold
        )
        OutlinedTextField(
            value = value,
            onValueChange = onValueChange,
            placeholder = { Text(placeholder, color = TextDim, style = MaterialTheme.typography.bodyMedium) },
            visualTransformation = if (isPassword && !showPassword) PasswordVisualTransformation() else VisualTransformation.None,
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedBorderColor = Accent,
                unfocusedBorderColor = Border1,
                focusedContainerColor = Surface2,
                unfocusedContainerColor = Color.Transparent,
                focusedTextColor = TextPrimary,
                unfocusedTextColor = TextPrimary
            ),
            trailingIcon = if (isPassword && onToggleShow != null) {
                {
                    IconButton(onClick = onToggleShow) {
                        Text(if (showPassword) "🙈" else "👁", fontSize = 16.sp)
                    }
                }
            } else null,
            keyboardOptions = KeyboardOptions(imeAction = imeAction),
            keyboardActions = keyboardActions
        )
    }
}
