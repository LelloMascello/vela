package com.jarvisai.app.audio

import android.annotation.SuppressLint
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch

/**
 * Records microphone audio at [SAMPLE_RATE] Hz (PCM 16-bit mono) and calls
 * [onSamples] with every chunk of raw [ShortArray] samples.
 *
 * The recording loop runs on [Dispatchers.IO].  The caller is responsible for
 * assembling chunks into frames of the desired size.
 */
class MicRecorder(private val scope: CoroutineScope) {

    companion object {
        const val SAMPLE_RATE = 16_000
        private const val CHANNEL    = AudioFormat.CHANNEL_IN_MONO
        private const val ENCODING   = AudioFormat.ENCODING_PCM_16BIT
        // ~20 ms per read at 16 kHz
        private const val READ_CHUNK  = 320
    }

    private var recorder: AudioRecord? = null
    private var job: Job? = null

    /** Callback invoked on the IO thread with raw PCM samples. */
    var onSamples: ((ShortArray) -> Unit)? = null

    @SuppressLint("MissingPermission")
    fun start() {
        if (job?.isActive == true) return

        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL, ENCODING)
            .coerceAtLeast(READ_CHUNK * 4)

        recorder = AudioRecord(
            MediaRecorder.AudioSource.VOICE_RECOGNITION,
            SAMPLE_RATE,
            CHANNEL,
            ENCODING,
            minBuf
        )
        recorder?.startRecording()

        job = scope.launch(Dispatchers.IO) {
            val buf = ShortArray(READ_CHUNK)
            while (isActive) {
                val read = recorder?.read(buf, 0, buf.size) ?: break
                if (read > 0) {
                    onSamples?.invoke(buf.copyOf(read))
                }
            }
        }
    }

    fun stop() {
        job?.cancel()
        job = null
        try { recorder?.stop() } catch (_: Exception) {}
        recorder?.release()
        recorder = null
    }
}
