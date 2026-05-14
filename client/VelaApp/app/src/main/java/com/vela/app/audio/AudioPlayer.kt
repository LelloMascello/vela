package com.vela.app.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioTrack
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.io.ByteArrayInputStream
import java.io.DataInputStream

/**
 * Plays WAV bytes (from the engine's TTS output or the router's audio cue).
 * Thread-safe: each call creates its own AudioTrack and releases it when done.
 */
class AudioPlayer {

    /**
     * Plays a WAV byte array synchronously (suspends until playback completes).
     * Must be called from a coroutine — it dispatches to Dispatchers.IO internally.
     */
    suspend fun playWav(wavBytes: ByteArray) = withContext(Dispatchers.IO) {
        try {
            val (pcmData, sampleRate, channels, bitsPerSample) = parseWavHeader(wavBytes)

            val channelMask = if (channels == 1)
                AudioFormat.CHANNEL_OUT_MONO else AudioFormat.CHANNEL_OUT_STEREO
            val encoding = if (bitsPerSample == 16)
                AudioFormat.ENCODING_PCM_16BIT else AudioFormat.ENCODING_PCM_8BIT

            val minBuf = AudioTrack.getMinBufferSize(sampleRate, channelMask, encoding)
            val bufSize = maxOf(minBuf, pcmData.size)

            val track = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ASSISTANT)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(sampleRate)
                        .setChannelMask(channelMask)
                        .setEncoding(encoding)
                        .build()
                )
                .setBufferSizeInBytes(bufSize)
                .setTransferMode(AudioTrack.MODE_STATIC)
                .build()

            track.write(pcmData, 0, pcmData.size)
            track.play()

            // Wait until playback finishes
            val durationMs = (pcmData.size.toLong() * 1000L) /
                    (sampleRate * channels * (bitsPerSample / 8))
            kotlinx.coroutines.delay(durationMs + 200L)

            track.stop()
            track.release()
        } catch (e: Exception) {
            android.util.Log.e("AudioPlayer", "Playback error: ${e.message}", e)
        }
    }

    // ── WAV parsing ───────────────────────────────────────────────────────────

    private data class WavInfo(
        val pcmData: ByteArray,
        val sampleRate: Int,
        val channels: Int,
        val bitsPerSample: Int
    )

    private fun parseWavHeader(wav: ByteArray): WavInfo {
        val dis = DataInputStream(ByteArrayInputStream(wav))

        // RIFF header (44 bytes standard)
        val riff = ByteArray(4).also { dis.readFully(it) }
        require(String(riff) == "RIFF") { "Not a RIFF file" }
        dis.readInt()                                       // file size (LE) — ignored
        val wave = ByteArray(4).also { dis.readFully(it) }
        require(String(wave) == "WAVE") { "Not a WAVE file" }

        // fmt  chunk
        val fmt  = ByteArray(4).also { dis.readFully(it) }
        require(String(fmt) == "fmt ") { "Missing fmt chunk" }
        val fmtSize     = readIntLE(dis)
        /* audioFormat = */ readShortLE(dis)               // 1 = PCM
        val channels    = readShortLE(dis).toInt()
        val sampleRate  = readIntLE(dis)
        /* byteRate = */     readIntLE(dis)
        /* blockAlign = */   readShortLE(dis)
        val bitsPerSample = readShortLE(dis).toInt()
        if (fmtSize > 16) dis.skipBytes(fmtSize - 16)

        // data chunk (skip any non-data chunks)
        var pcmData: ByteArray? = null
        while (pcmData == null) {
            val chunkId   = ByteArray(4).also { dis.readFully(it) }
            val chunkSize = readIntLE(dis)
            if (String(chunkId) == "data") {
                pcmData = ByteArray(chunkSize).also { dis.readFully(it) }
            } else {
                dis.skipBytes(chunkSize)
            }
        }

        return WavInfo(pcmData, sampleRate, channels, bitsPerSample)
    }

    private fun readIntLE(dis: DataInputStream): Int {
        val b0 = dis.read(); val b1 = dis.read()
        val b2 = dis.read(); val b3 = dis.read()
        return b0 or (b1 shl 8) or (b2 shl 16) or (b3 shl 24)
    }

    private fun readShortLE(dis: DataInputStream): Short {
        val b0 = dis.read(); val b1 = dis.read()
        return (b0 or (b1 shl 8)).toShort()
    }
}
