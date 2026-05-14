package com.vela.app.audio

import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import kotlinx.coroutines.isActive
import kotlin.coroutines.coroutineContext

/**
 * Captures microphone audio as 16 kHz / 16-bit / mono PCM.
 * Emits ByteArray chunks (~100 ms each) as a cold Flow.
 *
 * Usage:
 *   val job = launch { recorder.chunks().collect { chunk -> sendToServer(chunk) } }
 *   job.cancel()   // stops recording
 */
class AudioRecorder {

    companion object {
        const val SAMPLE_RATE   = 16_000          // Hz
        const val CHANNEL_IN    = AudioFormat.CHANNEL_IN_MONO
        const val ENCODING      = AudioFormat.ENCODING_PCM_16BIT
        /** ~100 ms of audio at 16 kHz 16-bit mono = 3 200 bytes */
        const val CHUNK_BYTES   = 3_200
    }

    fun chunks(): Flow<ByteArray> = flow {
        val minBuf = AudioRecord.getMinBufferSize(SAMPLE_RATE, CHANNEL_IN, ENCODING)
        val bufSize = maxOf(minBuf * 4, CHUNK_BYTES * 4)

        val recorder = AudioRecord(
            MediaRecorder.AudioSource.MIC,
            SAMPLE_RATE,
            CHANNEL_IN,
            ENCODING,
            bufSize
        )

        check(recorder.state == AudioRecord.STATE_INITIALIZED) {
            "AudioRecord failed to initialize"
        }

        recorder.startRecording()
        try {
            val buf = ByteArray(CHUNK_BYTES)
            while (coroutineContext.isActive) {
                val read = recorder.read(buf, 0, buf.size)
                if (read > 0) emit(buf.copyOf(read))
            }
        } finally {
            recorder.stop()
            recorder.release()
        }
    }.flowOn(Dispatchers.IO)
}
