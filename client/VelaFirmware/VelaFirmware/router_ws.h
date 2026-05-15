#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  router_ws.h  –  WebSocket client for router.py
//
//  Protocol:
//    1. Connect  ws://<ws_host>:<ws_port>
//    2. Send     {"type":"auth","token":"<JWT>"}
//    3. Receive  {"type":"ready"}
//    4. Stream   binary PCM frames  → sendAudio()
//    5. Receive  binary frame       → audio cue WAV
//       OR       {"type":"handoff","ws_host":"…","ws_port":N}
//       OR       {"type":"error","error":"…"}
//
//  Requires library: WebSockets by Markus Sattler (>=2.4.0)
// ─────────────────────────────────────────────────────────────────────────────

#include "config.h"
#include "vela_state.h"
#include <Arduino.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

// Callback signatures
using RouterReadyCb   = std::function<void()>;
using RouterAudioCb   = std::function<void(uint8_t*, size_t)>;   // WAV bytes
using RouterHandoffCb = std::function<void(String host, int port)>;
using RouterErrorCb   = std::function<void(String msg)>;

class RouterWS {
public:
    void begin(const String& host, int port, const String& token,
               RouterReadyCb   onReady,
               RouterAudioCb   onAudioCue,
               RouterHandoffCb onHandoff,
               RouterErrorCb   onError)
    {
        _token      = token;
        _onReady    = onReady;
        _onAudioCue = onAudioCue;
        _onHandoff  = onHandoff;
        _onError    = onError;
        _ready      = false;

        Serial.printf("[ROUTER] Connecting to ws://%s:%d\n", host.c_str(), port);

        _ws.begin(host, port, "/");
        _ws.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
            _handleEvent(type, payload, length);
        });
        _ws.setReconnectInterval(3000);
        _ws.enableHeartbeat(20000, 5000, 3);  // ping every 20 s
    }

    /** Must be called from loop() */
    void loop() { _ws.loop(); }

    /** Send a raw PCM chunk as a binary WebSocket frame. */
    void sendAudio(const int16_t* samples, size_t count) {
        if (!_ready) return;
        _ws.sendBIN((const uint8_t*)samples, count * sizeof(int16_t));
    }

    void disconnect() {
        _ready = false;
        _ws.disconnect();
    }

    bool isReady() const { return _ready; }

private:
    WebSocketsClient _ws;
    String           _token;
    bool             _ready = false;

    RouterReadyCb    _onReady;
    RouterAudioCb    _onAudioCue;
    RouterHandoffCb  _onHandoff;
    RouterErrorCb    _onError;

    void _handleEvent(WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {

            case WStype_CONNECTED:
                Serial.println("[ROUTER] Connected – sending auth");
                {
                    String authMsg = "{\"type\":\"auth\",\"token\":\"" + _token + "\"}";
                    _ws.sendTXT(authMsg);
                }
                break;

            case WStype_TEXT: {
                StaticJsonDocument<512> doc;
                DeserializationError err = deserializeJson(doc, payload, length);
                if (err) {
                    Serial.printf("[ROUTER] JSON parse error: %s\n", err.c_str());
                    break;
                }
                const char* msgType = doc["type"];
                if (!msgType) break;

                if (strcmp(msgType, "ready") == 0) {
                    Serial.println("[ROUTER] Ready – streaming mic");
                    _ready = true;
                    if (_onReady) _onReady();

                } else if (strcmp(msgType, "handoff") == 0) {
                    String host = doc["ws_host"] | "";
                    int    port = doc["ws_port"] | 8765;
                    Serial.printf("[ROUTER] Handoff → ws://%s:%d\n",
                                  host.c_str(), port);
                    _ready = false;
                    if (_onHandoff) _onHandoff(host, port);

                } else if (strcmp(msgType, "error") == 0) {
                    String msg = doc["error"] | "unknown error";
                    Serial.printf("[ROUTER] Error: %s\n", msg.c_str());
                    if (_onError) _onError(msg);
                }
                break;
            }

            case WStype_BIN:
                // Binary frame = audio cue WAV from router
                Serial.printf("[ROUTER] Audio cue received (%u bytes)\n", length);
                if (_onAudioCue) _onAudioCue(payload, length);
                break;

            case WStype_DISCONNECTED:
                Serial.println("[ROUTER] Disconnected");
                _ready = false;
                break;

            case WStype_ERROR:
                Serial.println("[ROUTER] WebSocket error");
                _ready = false;
                if (_onError) _onError("WebSocket error");
                break;

            default:
                break;
        }
    }
};
