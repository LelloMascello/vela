#pragma once

// ─────────────────────────────────────────────────────────────────────────────
//  audio_i2s.h  –  I2S microphone (INMP441) + speaker (MAX98357A) driver
// ─────────────────────────────────────────────────────────────────────────────

#include "config.h"
#include <Arduino.h>
#include <driver/i2s.h>

// ── Microphone ────────────────────────────────────────────────────────────────

class MicI2S {
public:
    bool begin() {
        i2s_config_t cfg = {
            .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_RX),
            .sample_rate          = SAMPLE_RATE,
            .bits_per_sample      = I2S_BITS_PER_SAMPLE_32BIT, // INMP441 outputs 32-bit (data in top 18 bits)
            .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_I2S,
            .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count        = I2S_DMA_BUF_COUNT,
            .dma_buf_len          = I2S_DMA_BUF_LEN,
            .use_apll             = false,
            .tx_desc_auto_clear   = false,
            .fixed_mclk           = 0
        };

        i2s_pin_config_t pins = {
            .bck_io_num   = I2S_MIC_SCK,
            .ws_io_num    = I2S_MIC_WS,
            .data_out_num = I2S_PIN_NO_CHANGE,
            .data_in_num  = I2S_MIC_SD
        };

        esp_err_t err = i2s_driver_install(I2S_MIC_PORT, &cfg, 0, NULL);
        if (err != ESP_OK) { Serial.printf("[MIC] driver_install failed: %d\n", err); return false; }

        err = i2s_set_pin(I2S_MIC_PORT, &pins);
        if (err != ESP_OK) { Serial.printf("[MIC] set_pin failed: %d\n", err); return false; }

        Serial.println("[MIC] I2S microphone ready");
        return true;
    }

    void end() { i2s_driver_uninstall(I2S_MIC_PORT); }

    /**
     * Read one chunk of raw PCM (16-bit signed, mono, SAMPLE_RATE Hz).
     * Returns the number of 16-bit samples written into `outBuf`.
     * outBuf must hold at least MIC_CHUNK_SAMPLES int16_t values.
     */
    size_t readChunk(int16_t* outBuf, size_t samples = MIC_CHUNK_SAMPLES) {
        // INMP441 gives 32-bit words; we shift right 14 to get 18-bit data
        // and then take the top 16 bits → store as int16_t.
        static int32_t raw[MIC_CHUNK_SAMPLES];
        size_t bytesRead = 0;

        i2s_read(I2S_MIC_PORT,
                 raw,
                 samples * sizeof(int32_t),
                 &bytesRead,
                 portMAX_DELAY);

        size_t samplesRead = bytesRead / sizeof(int32_t);
        for (size_t i = 0; i < samplesRead; i++) {
            // Sign-extend 18-bit value and scale to 16-bit
            outBuf[i] = (int16_t)(raw[i] >> 14);
        }
        return samplesRead;
    }

private:
};

// ── Speaker ───────────────────────────────────────────────────────────────────

class SpeakerI2S {
public:
    bool begin() {
        i2s_config_t cfg = {
            .mode                 = (i2s_mode_t)(I2S_MODE_MASTER | I2S_MODE_TX),
            .sample_rate          = SAMPLE_RATE,
            .bits_per_sample      = I2S_BITS_PER_SAMPLE_16BIT,
            .channel_format       = I2S_CHANNEL_FMT_ONLY_LEFT,
            .communication_format = I2S_COMM_FORMAT_STAND_I2S,
            .intr_alloc_flags     = ESP_INTR_FLAG_LEVEL1,
            .dma_buf_count        = I2S_DMA_BUF_COUNT,
            .dma_buf_len          = I2S_DMA_BUF_LEN,
            .use_apll             = false,
            .tx_desc_auto_clear   = true,
            .fixed_mclk           = 0
        };

        i2s_pin_config_t pins = {
            .bck_io_num   = I2S_SPK_BCLK,
            .ws_io_num    = I2S_SPK_LRC,
            .data_out_num = I2S_SPK_DOUT,
            .data_in_num  = I2S_PIN_NO_CHANGE
        };

        esp_err_t err = i2s_driver_install(I2S_SPK_PORT, &cfg, 0, NULL);
        if (err != ESP_OK) { Serial.printf("[SPK] driver_install failed: %d\n", err); return false; }

        err = i2s_set_pin(I2S_SPK_PORT, &pins);
        if (err != ESP_OK) { Serial.printf("[SPK] set_pin failed: %d\n", err); return false; }

        Serial.println("[SPK] I2S speaker ready");
        return true;
    }

    void end() { i2s_driver_uninstall(I2S_SPK_PORT); }

    /**
     * Play a WAV byte array synchronously (blocks until done).
     * Handles standard 44-byte PCM WAV headers; auto-resamples if the
     * WAV sample rate differs from SAMPLE_RATE by adjusting the I2S clock.
     */
    void playWav(const uint8_t* data, size_t len) {
        if (len < 44) return;

        // Parse WAV header
        uint32_t sampleRate   = *(uint32_t*)(data + 24);
        uint16_t numChannels  = *(uint16_t*)(data + 22);
        uint16_t bitsPerSamp  = *(uint16_t*)(data + 34);

        // Find "data" chunk
        size_t dataOffset = 44;
        for (size_t i = 12; i < len - 8; i++) {
            if (data[i]=='d' && data[i+1]=='a' && data[i+2]=='t' && data[i+3]=='a') {
                dataOffset = i + 8;
                break;
            }
        }
        if (dataOffset >= len) return;

        // Adjust I2S sample rate to match WAV
        if (sampleRate != _currentRate || numChannels != _currentCh || bitsPerSamp != _currentBits) {
            i2s_set_clk(I2S_SPK_PORT,
                        sampleRate,
                        (i2s_bits_per_sample_t)bitsPerSamp,
                        numChannels == 2 ? I2S_CHANNEL_STEREO : I2S_CHANNEL_MONO);
            _currentRate = sampleRate;
            _currentCh   = numChannels;
            _currentBits = bitsPerSamp;
        }

        const size_t WRITE_CHUNK = 1024;
        size_t offset = dataOffset;
        while (offset < len) {
            size_t toWrite = min(WRITE_CHUNK, len - offset);
            size_t written = 0;
            i2s_write(I2S_SPK_PORT, data + offset, toWrite, &written, portMAX_DELAY);
            offset += written;
        }

        // Drain DMA buffers with silence
        static uint8_t silence[512] = {};
        size_t dummy;
        i2s_write(I2S_SPK_PORT, silence, sizeof(silence), &dummy, 100 / portTICK_PERIOD_MS);
    }

    /** Decode base64 WAV string from JSON and play it. */
    void playBase64Wav(const String& b64);  // implemented in .ino

private:
    uint32_t _currentRate = 0;
    uint16_t _currentCh   = 0;
    uint16_t _currentBits = 0;
};
