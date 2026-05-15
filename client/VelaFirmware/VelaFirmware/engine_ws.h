#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  engine_ws.h  –  WebSocket client for main.py (the AI engine)
//
//  Protocol:
//    1. Connect  ws://<ws_host>:<ws_port>
//    2. Stream   binary PCM frames  → sendAudio()
//    3. Receive  {"type":"response_chunk","text":"…","audio":"<b64 WAV>"}
//       OR       {"type":"session_end","reason":"silence"}
//       OR       {"type":"error","error":"…"}
//
//  Requires library: WebSockets by Markus Sattler (>=2.4.0)
// ─────────────────────────────────────────────────────────────────────────────

#include "config.h"
#include "vela_state.h"
#include <Arduino.h>
#include <WebSocketsClient.h>
#include <ArduinoJson.h>

// ── Callbacks ─────────────────────────────────────────────────────────────────
using EngineChunkCb  = std::function<void(String text, String audioB64)>;
using EngineEndCb    = std::function<void(String reason)>;
using EngineErrorCb  = std::function<void(String msg)>;

class EngineWS {
public:
    void begin(const String& host, int port,
               EngineChunkCb onChunk,
               EngineEndCb   onEnd,
               EngineErrorCb onError)
    {
        _onChunk = onChunk;
        _onEnd   = onEnd;
        _onError = onError;
        _open    = false;

        Serial.printf("[ENGINE] Connecting to ws://%s:%d\n", host.c_str(), port);

        _ws.begin(host, port, "/");
        _ws.onEvent([this](WStype_t type, uint8_t* payload, size_t length) {
            _handleEvent(type, payload, length);
        });
        _ws.setReconnectInterval(0);    // don't auto-reconnect to engine
        _ws.enableHeartbeat(20000, 5000, 3);
    }

    void loop() { _ws.loop(); }

    /** Send a raw PCM chunk to the engine. */
    void sendAudio(const int16_t* samples, size_t count) {
        if (!_open) return;
        _ws.sendBIN((const uint8_t*)samples, count * sizeof(int16_t));
    }

    void disconnect() {
        _open = false;
        _ws.disconnect();
    }

    bool isOpen() const { return _open; }

private:
    WebSocketsClient _ws;
    bool             _open = false;

    EngineChunkCb    _onChunk;
    EngineEndCb      _onEnd;
    EngineErrorCb    _onError;

    void _handleEvent(WStype_t type, uint8_t* payload, size_t length) {
        switch (type) {

            case WStype_CONNECTED:
                Serial.println("[ENGINE] Connected – streaming mic");
                _open = true;
                break;

            case WStype_TEXT: {
                // The response_chunk audio field can be large (base64 WAV).
                // Use DynamicJsonDocument sized for up to ~64 KB of audio.
                DynamicJsonDocument doc(1024 * 96);   // 96 KB
                DeserializationError err = deserializeJson(doc, payload, length);
                if (err) {
                    Serial.printf("[ENGINE] JSON parse error: %s\n", err.c_str());
                    break;
                }

                const char* msgType = doc["type"];
                if (!msgType) break;

                if (strcmp(msgType, "response_chunk") == 0) {
                    String text     = doc["text"]  | "";
                    String audioB64 = doc["audio"] | "";
                    Serial.printf("[ENGINE] Chunk: \"%s\" (%u b64 chars)\n",
                                  text.c_str(), audioB64.length());
                    if (_onChunk) _onChunk(text, audioB64);

                } else if (strcmp(msgType, "session_end") == 0) {
                    String reason = doc["reason"] | "silence";
                    Serial.printf("[ENGINE] Session end: %s\n", reason.c_str());
                    _open = false;
                    if (_onEnd) _onEnd(reason);

                } else if (strcmp(msgType, "error") == 0) {
                    String msg = doc["error"] | "unknown error";
                    Serial.printf("[ENGINE] Error: %s\n", msg.c_str());
                    _open = false;
                    if (_onError) _onError(msg);
                }
                break;
            }

            case WStype_DISCONNECTED:
                Serial.println("[ENGINE] Disconnected");
                _open = false;
                break;

            case WStype_ERROR:
                Serial.println("[ENGINE] WebSocket error");
                _open = false;
                if (_onError) _onError("WebSocket error");
                break;

            default:
                break;
        }
    }
};
