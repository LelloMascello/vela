#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  wifi_provision.h  –  WiFiManager captive-portal provisioning
//
//  When the ESP32 has no saved WiFi or credentials it opens an AP named
//  "Vela-Setup". The user connects to that AP and is redirected to a
//  captive portal where they can enter:
//    • WiFi SSID + Password  (handled natively by WiFiManager)
//    • Raspberry Pi 5 IP
//    • Vela username
//    • Vela password
//
//  Requires library: WiFiManager by tzapu (>=2.0.17)
// ─────────────────────────────────────────────────────────────────────────────

#include "config.h"
#include "nvs_creds.h"
#include "led.h"
#include <WiFiManager.h>   // tzapu/WiFiManager

extern Led gLed;           // defined in main .ino

class WifiProvision {
public:
    /**
     * Attempt to connect with saved WiFi credentials.
     * If that fails (or no credentials), start the captive-portal AP.
     *
     * @param creds  Filled with Vela credentials if provisioning succeeds.
     * @return true  if WiFi is connected after this call.
     */
    static bool run(VelaCredentials& creds) {
        WiFiManager wm;

        // ── Custom parameters shown in the portal ──────────────────────────

        WiFiManagerParameter paramPiHost(
            "pi_host",                   // HTML id
            "Raspberry Pi 5 IP",         // label
            creds.piHost.c_str(),        // default value
            32                           // max length
        );
        WiFiManagerParameter paramUsername(
            "username",
            "Vela username",
            creds.username.c_str(),
            32
        );
        WiFiManagerParameter paramPassword(
            "vela_pass",                 // avoid "password" – some browsers autofill weirdly
            "Vela password",
            "",                          // never pre-fill password
            64
        );

        wm.addParameter(&paramPiHost);
        wm.addParameter(&paramUsername);
        wm.addParameter(&paramPassword);

        // ── WiFiManager behaviour ──────────────────────────────────────────

        wm.setConfigPortalTimeout(WIFIMANAGER_TIMEOUT);
        wm.setTitle("Vela Setup");
        wm.setShowPassword(false);   // hide password field by default

        // Custom HTML injected at the top of the portal page
        String customHead =
            "<style>"
            "body{font-family:sans-serif;background:#0f1117;color:#fff;}"
            "h1{color:#6c63ff;}"
            "input{background:#1c1f2a!important;color:#fff!important;border:1px solid #6c63ff!important;}"
            "button,input[type=submit]{background:#6c63ff!important;color:#fff!important;border:none;}"
            "</style>";
        wm.setCustomHeadElement(customHead.c_str());

        // LED: fast blink = AP mode / connecting
        gLed.setPattern(LedPattern::FAST_BLINK);

        // ── Try auto-connect first; open portal if it fails ───────────────

        bool connected;
        if (creds.valid) {
            // We already have WiFi credentials saved by WiFiManager internally
            Serial.println("[WIFI] Trying auto-connect…");
            connected = wm.autoConnect(WIFIMANAGER_AP_NAME, WIFIMANAGER_AP_PASS);
        } else {
            Serial.println("[WIFI] No WiFi saved – opening config portal");
            connected = wm.startConfigPortal(WIFIMANAGER_AP_NAME, WIFIMANAGER_AP_PASS);
        }

        if (!connected) {
            Serial.println("[WIFI] Config portal timed out or failed");
            return false;
        }

        // ── Save Vela credentials from the portal form ────────────────────

        String piHost  = String(paramPiHost.getValue());
        String uname   = String(paramUsername.getValue());
        String pass    = String(paramPassword.getValue());

        // If the user left the Vela-password blank, keep the previously saved one
        if (pass.isEmpty()) pass = creds.password;

        if (!piHost.isEmpty() && !uname.isEmpty() && !pass.isEmpty()) {
            NvsCreds::save(piHost, uname, pass);
            creds.piHost   = piHost;
            creds.username = uname;
            creds.password = pass;
            creds.valid    = true;
        }

        Serial.printf("[WIFI] Connected. IP: %s\n",
                      WiFi.localIP().toString().c_str());
        return true;
    }

    /** Force re-provisioning by resetting WiFiManager saved data + NVS. */
    static void resetAll() {
        WiFiManager wm;
        wm.resetSettings();
        NvsCreds::clear();
        Serial.println("[WIFI] All settings reset – will re-provision on next boot");
    }
};
