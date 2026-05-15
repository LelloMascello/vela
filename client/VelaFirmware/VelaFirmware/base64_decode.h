#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  base64_decode.h  –  Decode base64 → binary (for WAV audio from the engine)
//
//  Avoids pulling in heavy external libraries; works entirely in-place.
// ─────────────────────────────────────────────────────────────────────────────

#include <Arduino.h>

class Base64 {
public:
    /**
     * Decode a base64 String into a heap-allocated byte array.
     * The caller must free() the returned pointer.
     *
     * @param input     base64-encoded string
     * @param outLen    set to the number of decoded bytes
     * @return pointer  to decoded bytes, or nullptr on failure
     */
    static uint8_t* decode(const String& input, size_t& outLen) {
        const char* src = input.c_str();
        size_t inLen    = input.length();

        // Strip padding to find real output length
        outLen = (inLen / 4) * 3;
        if (inLen >= 1 && src[inLen - 1] == '=') outLen--;
        if (inLen >= 2 && src[inLen - 2] == '=') outLen--;

        uint8_t* out = (uint8_t*)malloc(outLen);
        if (!out) return nullptr;

        size_t i = 0, j = 0;
        while (i < inLen) {
            uint32_t sextet_a = (i < inLen) ? _decTable[(uint8_t)src[i++]] : 0;
            uint32_t sextet_b = (i < inLen) ? _decTable[(uint8_t)src[i++]] : 0;
            uint32_t sextet_c = (i < inLen) ? _decTable[(uint8_t)src[i++]] : 0;
            uint32_t sextet_d = (i < inLen) ? _decTable[(uint8_t)src[i++]] : 0;

            uint32_t triple = (sextet_a << 18)
                            | (sextet_b << 12)
                            | (sextet_c <<  6)
                            |  sextet_d;

            if (j < outLen) out[j++] = (triple >> 16) & 0xFF;
            if (j < outLen) out[j++] = (triple >>  8) & 0xFF;
            if (j < outLen) out[j++] =  triple        & 0xFF;
        }
        return out;
    }

private:
    static constexpr uint8_t _decTable[256] = {
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0, 62,  0,  0,  0, 63,
       52, 53, 54, 55, 56, 57, 58, 59, 60, 61,  0,  0,  0,  0,  0,  0,
        0,  0,  1,  2,  3,  4,  5,  6,  7,  8,  9, 10, 11, 12, 13, 14,
       15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25,  0,  0,  0,  0,  0,
        0, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40,
       41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,
        0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0,  0
    };
};
