package com.jarvisai.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val FlowDarkColors = darkColorScheme(
    primary          = Accent,
    onPrimary        = Color.White,
    primaryContainer = AccentDim,
    secondary        = Sky,
    background       = BgDeep,
    surface          = Surface1,
    onBackground     = TextPrimary,
    onSurface        = TextPrimary,
    error            = Red,
    outline          = Border1,
)

@Composable
fun JarvisAITheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = FlowDarkColors,
        typography  = AppTypography,
        content     = content
    )
}
