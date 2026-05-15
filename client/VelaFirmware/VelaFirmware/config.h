#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  config.h  –  Hardware pins & tunable parameters for the Vela ESP32 node
// ─────────────────────────────────────────────────────────────────────────────
//
//  Tested with:
//    • ESP32-WROOM-32 / ESP32-DevKitC
//    • INMP441  MEMS microphone  (I2S input)
//    • MAX98357A I2S amplifier   (I2S output)
//
//  Change the pin numbers below to match your wiring.
// ─────────────────────────────────────────────────────────────────────────────

// ── I2S Microphone (INMP441) ──────────────────────────────────────────────────
//   INMP441 pin → ESP32 pin
//   WS  (L/R)   → I2S_MIC_WS
//   SCK (CLK)   → I2S_MIC_SCK
//   SD  (DATA)  → I2S_MIC_SD
//   L/R (sel)   → GND  (left channel)
//   VDD         → 3.3 V
//   GND         → GND

#define I2S_MIC_WS    15
#define I2S_MIC_SCK   14
#define I2S_MIC_SD    32
#define I2S_MIC_PORT  I2S_NUM_0

// ── I2S Amplifier / DAC (MAX98357A) ──────────────────────────────────────────
//   MAX98357A pin → ESP32 pin
//   LRC (WS)      → I2S_SPK_LRC
//   BCLK          → I2S_SPK_BCLK
//   DIN           → I2S_SPK_DOUT
//   SD (shutdown) → 3.3 V (always on) or a GPIO if you want SW mute
//   VIN           → 5 V
//   GND           → GND

#define I2S_SPK_LRC   27
#define I2S_SPK_BCLK  26
#define I2S_SPK_DOUT  25
#define I2S_SPK_PORT  I2S_NUM_1

// ── Status LED ────────────────────────────────────────────────────────────────
//   Built-in LED on most DevKit boards = GPIO 2
//   Set to -1 to disable.

#define LED_PIN  2

// ── Audio parameters ──────────────────────────────────────────────────────────
#define SAMPLE_RATE       16000   // Hz  – must match server expectation
#define BITS_PER_SAMPLE   16
#define MIC_CHANNELS      1       // mono
#define SPK_CHANNELS      1

// Number of 16-bit samples per chunk sent over WebSocket (~100 ms)
#define MIC_CHUNK_SAMPLES 1600    // 1600 × 2 bytes = 3200 bytes ≈ 100 ms

// I2S DMA buffer tuning
#define I2S_DMA_BUF_COUNT  8
#define I2S_DMA_BUF_LEN    512    // samples per DMA buffer

// ── Network / server ports ────────────────────────────────────────────────────
#define AUTH_PORT     5001        // auth.py
#define ROUTER_PORT   8766        // router.py  (default, overridden by JWT response)
#define HTTP_TIMEOUT_MS 10000

// ── WiFiManager ───────────────────────────────────────────────────────────────
#define WIFIMANAGER_AP_NAME  "Vela-Setup"
#define WIFIMANAGER_AP_PASS  "vela1234"   // min 8 chars for WPA2; set "" for open
#define WIFIMANAGER_TIMEOUT  180          // seconds before AP gives up

// ── NVS keys (Preferences namespace "vela") ──────────────────────────────────
#define NVS_NS          "vela"
#define NVS_PI_HOST     "pi_host"
#define NVS_USERNAME    "username"
#define NVS_PASSWORD    "password"

// ── Reconnect policy ──────────────────────────────────────────────────────────
#define RECONNECT_DELAY_MS  5000   // wait between reconnect attempts
#define MAX_AUTH_RETRIES    5
