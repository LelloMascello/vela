#pragma once
#include <Arduino.h>

// ─────────────────────────────────────────────────────────────────────────────
//  vela_state.h  –  Shared state definitions
// ─────────────────────────────────────────────────────────────────────────────

enum class VelaState {
    BOOT,            // Hardware init
    WIFI_CONNECT,    // Connecting to saved WiFi / starting AP
    AUTHENTICATING,  // HTTP POST /auth/login
    ROUTER_CONNECT,  // Opening WebSocket to router.py
    LISTENING,       // Connected, streaming mic → router (waiting for wake word)
    WAKE_DETECTED,   // Playing audio cue
    ENGINE_CONNECT,  // Opening WebSocket to main.py
    ACTIVE,          // Streaming mic → engine
    RESPONDING,      // Playing TTS response chunks
    ERROR,           // Fatal error – will retry after delay
};

inline const char* stateName(VelaState s) {
    switch (s) {
        case VelaState::BOOT:           return "BOOT";
        case VelaState::WIFI_CONNECT:   return "WIFI_CONNECT";
        case VelaState::AUTHENTICATING: return "AUTHENTICATING";
        case VelaState::ROUTER_CONNECT: return "ROUTER_CONNECT";
        case VelaState::LISTENING:      return "LISTENING";
        case VelaState::WAKE_DETECTED:  return "WAKE_DETECTED";
        case VelaState::ENGINE_CONNECT: return "ENGINE_CONNECT";
        case VelaState::ACTIVE:         return "ACTIVE";
        case VelaState::RESPONDING:     return "RESPONDING";
        case VelaState::ERROR:          return "ERROR";
        default:                        return "UNKNOWN";
    }
}

// ── Credentials (loaded from NVS, filled by WiFiManager) ─────────────────────
struct VelaCredentials {
    String piHost;
    String username;
    String password;
    bool   valid = false;
};

// ── JWT + server info returned by auth.py ─────────────────────────────────────
struct AuthInfo {
    String token;
    String wsHost;
    int    wsPort = 8766;
    bool   valid  = false;
};
