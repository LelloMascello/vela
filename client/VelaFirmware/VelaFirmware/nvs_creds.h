#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  nvs_creds.h  –  Persist Vela credentials in ESP32 Non-Volatile Storage
// ─────────────────────────────────────────────────────────────────────────────

#include "config.h"
#include "vela_state.h"
#include <Preferences.h>

class NvsCreds {
public:
    /** Load saved credentials. Returns false if any field is empty. */
    static bool load(VelaCredentials& out) {
        Preferences prefs;
        prefs.begin(NVS_NS, /*readOnly=*/true);

        out.piHost   = prefs.getString(NVS_PI_HOST,  "");
        out.username = prefs.getString(NVS_USERNAME, "");
        out.password = prefs.getString(NVS_PASSWORD, "");
        prefs.end();

        out.valid = !out.piHost.isEmpty() &&
                    !out.username.isEmpty() &&
                    !out.password.isEmpty();

        if (out.valid) {
            Serial.printf("[NVS] Loaded creds: host=%s user=%s\n",
                          out.piHost.c_str(), out.username.c_str());
        } else {
            Serial.println("[NVS] No complete credentials found");
        }
        return out.valid;
    }

    /** Persist credentials. */
    static void save(const String& piHost,
                     const String& username,
                     const String& password)
    {
        Preferences prefs;
        prefs.begin(NVS_NS, /*readOnly=*/false);
        prefs.putString(NVS_PI_HOST,  piHost);
        prefs.putString(NVS_USERNAME, username);
        prefs.putString(NVS_PASSWORD, password);
        prefs.end();
        Serial.printf("[NVS] Saved creds: host=%s user=%s\n",
                      piHost.c_str(), username.c_str());
    }

    /** Wipe all saved credentials (useful for re-provisioning). */
    static void clear() {
        Preferences prefs;
        prefs.begin(NVS_NS, false);
        prefs.clear();
        prefs.end();
        Serial.println("[NVS] Credentials cleared");
    }
};
