// ─────────────────────────────────────────────────────────────────────────────
//  VelaFirmware.ino  –  Main sketch for Vela ESP32 voice-assistant node
//
//  Board    : ESP32 (select "ESP32 Dev Module" in Arduino IDE)
//  Libraries (install via Library Manager):
//    • WiFiManager          by tzapu          >= 2.0.17
//    • WebSockets           by Markus Sattler >= 2.4.0
//    • ArduinoJson          by Benoit Blanchon >= 7.0.0
//
//  Partition scheme: "Default 4MB with spiffs" or larger
//  (ArduinoJson large documents need heap space)
// ─────────────────────────────────────────────────────────────────────────────

#include <Arduino.h>
#include <WiFi.h>

#include "config.h"
#include "vela_state.h"
#include "led.h"
#include "nvs_creds.h"
#include "wifi_provision.h"
#include "auth_client.h"
#include "audio_i2s.h"
#include "router_ws.h"
#include "engine_ws.h"
#include "base64_decode.h"

// ── Global objects ────────────────────────────────────────────────────────────
Led           gLed;
MicI2S        gMic;
SpeakerI2S    gSpeaker;
RouterWS      gRouter;
EngineWS      gEngine;

VelaState     gState       = VelaState::BOOT;
VelaCredentials gCreds;
AuthInfo      gAuth;

// Timestamp used for error-retry delays
uint32_t      gErrorAt     = 0;
uint8_t       gAuthRetries = 0;

// PCM sample buffer used by the mic reader
static int16_t sMicBuf[MIC_CHUNK_SAMPLES];

// ── SpeakerI2S::playBase64Wav – implemented here so it can use Base64 ─────────
void SpeakerI2S::playBase64Wav(const String& b64) {
    size_t len = 0;
    uint8_t* wav = Base64::decode(b64, len);
    if (!wav) {
        Serial.println("[SPK] Base64 decode failed (OOM?)");
        return;
    }
    playWav(wav, len);
    free(wav);
}

// ─────────────────────────────────────────────────────────────────────────────
//  State helpers
// ─────────────────────────────────────────────────────────────────────────────
void setState(VelaState s) {
    Serial.printf("[STATE] %s → %s\n", stateName(gState), stateName(s));
    gState = s;

    switch (s) {
        case VelaState::WIFI_CONNECT:
        case VelaState::AUTHENTICATING:
            gLed.setPattern(LedPattern::FAST_BLINK);    break;
        case VelaState::ROUTER_CONNECT:
        case VelaState::ENGINE_CONNECT:
            gLed.setPattern(LedPattern::FAST_BLINK);    break;
        case VelaState::LISTENING:
            gLed.setPattern(LedPattern::SLOW_BLINK);    break;
        case VelaState::WAKE_DETECTED:
        case VelaState::ACTIVE:
            gLed.setPattern(LedPattern::DOUBLE_PULSE);  break;
        case VelaState::RESPONDING:
            gLed.setPattern(LedPattern::SOLID_ON);      break;
        case VelaState::ERROR:
            gLed.setPattern(LedPattern::FAST_BLINK);
            gErrorAt = millis();
            break;
        default:
            gLed.setPattern(LedPattern::OFF);           break;
    }
}

void fatalError(const String& msg) {
    Serial.printf("[ERROR] %s\n", msg.c_str());
    setState(VelaState::ERROR);
}

// ─────────────────────────────────────────────────────────────────────────────
//  Router callbacks
// ─────────────────────────────────────────────────────────────────────────────
void onRouterReady() {
    setState(VelaState::LISTENING);
}

void onRouterAudioCue(uint8_t* data, size_t len) {
    setState(VelaState::WAKE_DETECTED);
    gSpeaker.playWav(data, len);
    // State will advance to ENGINE_CONNECT when the handoff arrives
}

void onRouterHandoff(String host, int port) {
    gRouter.disconnect();
    setState(VelaState::ENGINE_CONNECT);

    gEngine.begin(
        host, port,
        // onChunk
        [](String text, String audioB64) {
            setState(VelaState::RESPONDING);
            Serial.printf("[MAIN] ▶ \"%s\"\n", text.c_str());
            gSpeaker.playBase64Wav(audioB64);
            // After playing, go back to ACTIVE so we keep streaming mic
            if (gState == VelaState::RESPONDING)
                setState(VelaState::ACTIVE);
        },
        // onEnd
        [](String reason) {
            Serial.printf("[MAIN] Session ended: %s\n", reason.c_str());
            gEngine.disconnect();
            // Go back to authenticating → listening for a new session
            gAuthRetries = 0;
            setState(VelaState::AUTHENTICATING);
        },
        // onError
        [](String msg) {
            fatalError("Engine: " + msg);
        }
    );
}

void onRouterError(String msg) {
    fatalError("Router: " + msg);
}

// ─────────────────────────────────────────────────────────────────────────────
//  setup()
// ─────────────────────────────────────────────────────────────────────────────
void setup() {
    Serial.begin(115200);
    delay(500);
    Serial.println("\n\n========== Vela ESP32 Firmware ==========");

    // ── LED ──────────────────────────────────────────────────────────────────
    gLed.begin();
    setState(VelaState::BOOT);

    // ── Load saved Vela credentials from NVS ─────────────────────────────────
    NvsCreds::load(gCreds);

    // ── WiFi + provisioning ───────────────────────────────────────────────────
    setState(VelaState::WIFI_CONNECT);
    if (!WifiProvision::run(gCreds)) {
        fatalError("WiFi provisioning failed or timed out");
        return;  // will retry on next reboot
    }

    // ── I2S audio ─────────────────────────────────────────────────────────────
    if (!gMic.begin()) {
        fatalError("Microphone I2S init failed");
        return;
    }
    if (!gSpeaker.begin()) {
        fatalError("Speaker I2S init failed");
        return;
    }

    // ── Authenticate ──────────────────────────────────────────────────────────
    setState(VelaState::AUTHENTICATING);
    if (!AuthClient::login(gCreds, gAuth)) {
        fatalError("Authentication failed");
        return;
    }

    // ── Connect to router ─────────────────────────────────────────────────────
    connectRouter();
}

// ─────────────────────────────────────────────────────────────────────────────
//  connectRouter()  –  called from setup() and after session_end
// ─────────────────────────────────────────────────────────────────────────────
void connectRouter() {
    setState(VelaState::ROUTER_CONNECT);
    gRouter.begin(
        gAuth.wsHost,
        gAuth.wsPort,
        gAuth.token,
        onRouterReady,
        onRouterAudioCue,
        onRouterHandoff,
        onRouterError
    );
}

// ─────────────────────────────────────────────────────────────────────────────
//  loop()
// ─────────────────────────────────────────────────────────────────────────────
void loop() {
    gLed.tick();

    switch (gState) {

        // ── WebSocket maintenance ─────────────────────────────────────────────
        case VelaState::ROUTER_CONNECT:
        case VelaState::LISTENING:
        case VelaState::WAKE_DETECTED:
            gRouter.loop();
            // Stream microphone while listening for wake word
            if (gState == VelaState::LISTENING) {
                size_t got = gMic.readChunk(sMicBuf);
                if (got > 0) gRouter.sendAudio(sMicBuf, got);
            }
            break;

        case VelaState::ENGINE_CONNECT:
        case VelaState::ACTIVE:
        case VelaState::RESPONDING:
            gEngine.loop();
            // Stream microphone to engine during active session
            if (gState == VelaState::ACTIVE) {
                size_t got = gMic.readChunk(sMicBuf);
                if (got > 0) gEngine.sendAudio(sMicBuf, got);
            }
            break;

        // ── Error: re-authenticate after delay ───────────────────────────────
        case VelaState::ERROR:
            if (millis() - gErrorAt >= RECONNECT_DELAY_MS) {
                Serial.println("[MAIN] Retrying after error…");
                gRouter.disconnect();
                gEngine.disconnect();

                if (WiFi.status() != WL_CONNECTED) {
                    Serial.println("[MAIN] WiFi lost – reconnecting");
                    setState(VelaState::WIFI_CONNECT);
                    if (!WifiProvision::run(gCreds)) {
                        fatalError("WiFi reconnect failed");
                        break;
                    }
                }

                gAuthRetries++;
                if (gAuthRetries > MAX_AUTH_RETRIES) {
                    Serial.println("[MAIN] Too many auth retries – clearing creds & rebooting");
                    NvsCreds::clear();
                    delay(1000);
                    ESP.restart();
                }

                setState(VelaState::AUTHENTICATING);
                if (AuthClient::login(gCreds, gAuth)) {
                    connectRouter();
                } else {
                    fatalError("Re-authentication failed");
                }
            }
            break;

        // ── Re-authenticate after session end (set in onRouterHandoff/end) ───
        case VelaState::AUTHENTICATING:
            if (AuthClient::login(gCreds, gAuth)) {
                gAuthRetries = 0;
                connectRouter();
            } else {
                fatalError("Re-authentication failed");
            }
            break;

        default:
            break;
    }
}
