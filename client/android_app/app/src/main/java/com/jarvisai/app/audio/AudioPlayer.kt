package com.jarvisai.app.audio

import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioTrack
import android.util.Base64
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.launch
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Receives base-64-encoded WAV chunks from the server and plays them one by
 * one in order, mimicking the JS [audioQueue] + [drainAudioQueue] logic.
 *
 * Call [enqueue] from any thread; the drain loop runs on [Dispatchers.IO].
 * [onFinished] is invoked on IO when the queue drains completely.
 */
class AudioPlayer(private val scope: CoroutineScope) {

    private val queue = Channel<ByteArray>(capacity = Channel.UNLIMITED)
    private var drainJob = scope.launch(Dispatchers.IO) { drain() }

    /** Called when the queue empties (all audio finished playing). */
    var onFinished: (() -> Unit)? = null

    // ── Public API ────────────────────────────────────────────────────────

    fun enqueue(base64Wav: String) {
        val bytes = try {
            Base64.decode(base64Wav, Base64.DEFAULT)
        } catch (_: Exception) { return }
        queue.trySend(bytes)
    }

    /** Discard all queued audio immediately (e.g. on disconnect). */
    fun clear() {
        while (queue.tryReceive().isSuccess) { /* drain */ }
    }

    // ── Private drain loop ────────────────────────────────────────────────

    private suspend fun drain() {
        for (wavBytes in queue) {
            playWav(wavBytes)
        }
        onFinished?.invoke()
    }

    private fun playWav(wavBytes: ByteArray) {
        val header = parseWavHeader(wavBytes) ?: return
        val (sampleRate, channels, bitsPerSample) = header

        val pcmData  = wavBytes.copyOfRange(44, wavBytes.size)
        if (pcmData.isEmpty()) return

        val encoding = if (bitsPerSample == 16)
            AudioFormat.ENCODING_PCM_16BIT else AudioFormat.ENCODING_PCM_8BIT
        val channelMask = if (channels == 1)
            AudioFormat.CHANNEL_OUT_MONO else AudioFormat.CHANNEL_OUT_STEREO

        val track = try {
            AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(encoding)
                        .setSampleRate(sampleRate)
                        .setChannelMask(channelMask)
                        .build()
                )
                .setTransferMode(AudioTrack.MODE_STATIC)
                .setBufferSizeInBytes(pcmData.size)
                .build()
        } catch (_: Exception) { return }

        track.write(pcmData, 0, pcmData.size)
        track.play()

        // Block until playback finishes (calculate duration from PCM size).
        val bytesPerSample  = bitsPerSample / 8
        val durationMs = pcmData.size.toLong() * 1000L / (sampleRate * channels * bytesPerSample)
        Thread.sleep(durationMs + 80) // small tail buffer

        track.stop()
        track.release()

        // If the queue is now empty, notify caller.
        if (queue.isEmpty) onFinished?.invoke()
    }

    // ── WAV header parser ─────────────────────────────────────────────────

    /** Returns Triple(sampleRate, channels, bitsPerSample) or null on failure. */
    private fun parseWavHeader(bytes: ByteArray): Triple<Int, Int, Int>? {
        if (bytes.size < 44) return null
        // "RIFF" magic
        if (bytes[0] != 'R'.code.toByte() || bytes[1] != 'I'.code.toByte()) return null

        val bb = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
        val channels       = bb.getShort(22).toInt() and 0xFFFF
        val sampleRate     = bb.getInt(24)
        val bitsPerSample  = bb.getShort(34).toInt() and 0xFFFF

        if (channels < 1 || sampleRate < 1 || bitsPerSample < 1) return null
        return Triple(sampleRate, channels, bitsPerSample)
    }
}
