#pragma once
#include "config.h"
#include <Arduino.h>

// ─────────────────────────────────────────────────────────────────────────────
//  led.h  –  Non-blocking LED patterns for visual status feedback
// ─────────────────────────────────────────────────────────────────────────────

enum class LedPattern {
    OFF,
    ON,
    SLOW_BLINK,    // 1 Hz  – connected, listening for wake word
    FAST_BLINK,    // 5 Hz  – AP mode / connecting
    DOUBLE_PULSE,  // two quick pulses every 2 s – active session
    SOLID_ON       // TTS playback
};

class Led {
public:
    void begin() {
        if (LED_PIN < 0) return;
        pinMode(LED_PIN, OUTPUT);
        digitalWrite(LED_PIN, LOW);
    }

    void setPattern(LedPattern p) { _pattern = p; }

    // Call from loop() – no blocking delay
    void tick() {
        if (LED_PIN < 0) return;
        uint32_t now = millis();

        switch (_pattern) {
            case LedPattern::OFF:
                write(false); break;

            case LedPattern::ON:
            case LedPattern::SOLID_ON:
                write(true); break;

            case LedPattern::SLOW_BLINK:
                if (now - _last >= 500) { _last = now; _state = !_state; write(_state); }
                break;

            case LedPattern::FAST_BLINK:
                if (now - _last >= 100) { _last = now; _state = !_state; write(_state); }
                break;

            case LedPattern::DOUBLE_PULSE: {
                // Two 80 ms pulses separated by 120 ms, then 1.7 s off
                uint32_t phase = (now % 2000);
                bool on = (phase < 80) || (phase >= 200 && phase < 280);
                write(on);
                break;
            }
        }
    }

private:
    LedPattern _pattern = LedPattern::OFF;
    uint32_t   _last    = 0;
    bool       _state   = false;

    inline void write(bool v) {
        digitalWrite(LED_PIN, v ? HIGH : LOW);
    }
};
