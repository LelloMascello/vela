package com.jarvisai.app.ui.components

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.jarvisai.app.ui.theme.*

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun JarvisTopBar(
    currentRoute:    String,
    username:        String,
    onNavigateHome:  () -> Unit,
    onNavigateChats: () -> Unit,
    onLogout:        () -> Unit,
    onRefresh:       () -> Unit,
) {
    TopAppBar(
        colors   = TopAppBarDefaults.topAppBarColors(containerColor = BgDeep.copy(alpha = 0.95f)),
        modifier = Modifier.border(BorderStroke(1.dp, Border1)),
        title = {
            Text("jarvis.ai", style = MaterialTheme.typography.titleLarge,
                color = TextPrimary, fontWeight = FontWeight.ExtraBold)
        },
        actions = {
            // Home Pill/Button
            if (currentRoute == "home") {
                ActivePill("Home")
            } else {
                TextButton(onClick = onNavigateHome) {
                    Text("Home", color = TextMuted, style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.Medium)
                }
            }

            // Chats Pill/Button
            if (currentRoute == "chats") {
                ActivePill("Chats")
            } else {
                TextButton(onClick = onNavigateChats) {
                    Text("Chats", color = TextMuted, style = MaterialTheme.typography.bodySmall,
                        fontWeight = FontWeight.Medium)
                }
            }

            Spacer(Modifier.width(8.dp))

            // Username
            Surface(
                shape    = RoundedCornerShape(999.dp),
                color    = Surface2,
                border   = BorderStroke(1.dp, Border1),
            ) {
                Text(username,
                    modifier   = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
                    style      = MaterialTheme.typography.labelSmall,
                    color      = TextMuted,
                    fontFamily = FontFamily.Monospace)
            }

            IconButton(onClick = onRefresh) {
                Icon(Icons.Default.Refresh, contentDescription = "Refresh",
                    tint = TextDim, modifier = Modifier.size(18.dp))
            }

            TextButton(onClick = onLogout) {
                Text("Logout", color = Red.copy(alpha = 0.8f),
                    style = MaterialTheme.typography.bodySmall)
            }
            Spacer(Modifier.width(4.dp))
        }
    )
}

@Composable
private fun ActivePill(label: String) {
    Surface(
        shape    = RoundedCornerShape(999.dp),
        color    = Surface2,
        border   = BorderStroke(1.dp, Border2),
        modifier = Modifier.padding(horizontal = 4.dp),
    ) {
        Text(label,
            modifier   = Modifier.padding(horizontal = 10.dp, vertical = 5.dp),
            style      = MaterialTheme.typography.bodySmall,
            color      = TextPrimary,
            fontWeight = FontWeight.SemiBold)
    }
}
