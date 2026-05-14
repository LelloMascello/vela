package com.vela.app.model

// ── HTTP ──────────────────────────────────────────────────────────────────────

data class LoginRequest(
    val username: String,
    val password: String
)

data class LoginResponse(
    val token: String,
    val ws_host: String,
    val ws_port: Int
)

data class LoginError(val error: String)

// ── WebSocket messages (JSON frames) ──────────────────────────────────────────

/** Generic incoming frame — only the "type" field is guaranteed. */
data class WsFrame(
    val type: String,
    // router / engine
    val error: String?      = null,
    val client_id: String?  = null,
    // handoff (router → client)
    val ws_host: String?    = null,
    val ws_port: Int?       = null,
    // response_chunk (engine → client)
    val text: String?       = null,
    val audio: String?      = null,   // base64 WAV
    // session_end (engine → client)
    val reason: String?     = null
)

// ── UI state ──────────────────────────────────────────────────────────────────

enum class VelaState {
    IDLE,           // Not connected
    CONNECTING,     // HTTP login in progress
    LISTENING,      // Connected to router, streaming mic to wake-word detector
    WAKE_DETECTED,  // Wake word hit, playing cue / waiting for handoff
    ACTIVE,         // Connected to engine, user can speak
    RESPONDING,     // Engine is generating + streaming audio back
    ERROR
}

data class VelaUiState(
    val state: VelaState        = VelaState.IDLE,
    val statusText: String      = "Premi connetti per iniziare",
    val transcript: String      = "",
    val errorMessage: String?   = null,
    val canDisconnect: Boolean  = false
)
