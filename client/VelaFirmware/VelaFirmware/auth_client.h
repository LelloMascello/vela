#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  auth_client.h  –  HTTP login against auth.py (port 5001)
//
//  POST http://<piHost>:5001/auth/login
//  Body:  { "username": "...", "password": "..." }
//  200:   { "token": "...", "ws_host": "...", "ws_port": 8766 }
//  401:   { "error": "..." }
// ─────────────────────────────────────────────────────────────────────────────

#include "config.h"
#include "vela_state.h"
#include <Arduino.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>

class AuthClient {
public:
    /**
     * Perform the login request.
     * @param creds   Input credentials (piHost, username, password).
     * @param out     Filled with token + ws_host:ws_port on success.
     * @return true   on HTTP 200 with a valid token.
     */
    static bool login(const VelaCredentials& creds, AuthInfo& out) {
        if (!creds.valid) {
            Serial.println("[AUTH] Invalid credentials struct");
            return false;
        }

        String url = "http://" + creds.piHost + ":" + String(AUTH_PORT) + "/auth/login";
        Serial.printf("[AUTH] POST %s  user=%s\n", url.c_str(), creds.username.c_str());

        HTTPClient http;
        http.begin(url);
        http.addHeader("Content-Type", "application/json");
        http.setTimeout(HTTP_TIMEOUT_MS);

        // Build JSON body
        StaticJsonDocument<256> reqDoc;
        reqDoc["username"] = creds.username;
        reqDoc["password"] = creds.password;
        String reqBody;
        serializeJson(reqDoc, reqBody);

        int httpCode = http.POST(reqBody);

        if (httpCode <= 0) {
            Serial.printf("[AUTH] HTTP error: %s\n", http.errorToString(httpCode).c_str());
            http.end();
            return false;
        }

        String payload = http.getString();
        http.end();

        Serial.printf("[AUTH] HTTP %d  body: %s\n", httpCode, payload.c_str());

        if (httpCode != 200) {
            // Try to extract error message
            StaticJsonDocument<128> errDoc;
            if (deserializeJson(errDoc, payload) == DeserializationError::Ok) {
                Serial.printf("[AUTH] Server error: %s\n",
                              errDoc["error"] | "unknown");
            }
            return false;
        }

        // Parse success response
        StaticJsonDocument<512> resDoc;
        DeserializationError err = deserializeJson(resDoc, payload);
        if (err) {
            Serial.printf("[AUTH] JSON parse error: %s\n", err.c_str());
            return false;
        }

        const char* token   = resDoc["token"];
        const char* wsHost  = resDoc["ws_host"];
        int         wsPort  = resDoc["ws_port"] | ROUTER_PORT;

        if (!token || !wsHost) {
            Serial.println("[AUTH] Response missing token or ws_host");
            return false;
        }

        out.token  = String(token);
        out.wsHost = String(wsHost);
        out.wsPort = wsPort;
        out.valid  = true;

        Serial.printf("[AUTH] OK – ws://%s:%d\n", out.wsHost.c_str(), out.wsPort);
        return true;
    }
};
