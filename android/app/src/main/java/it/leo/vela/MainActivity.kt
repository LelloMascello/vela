package it.leo.vela

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioFormat
import android.media.AudioManager
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.*
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONObject
import java.util.UUID
import java.util.concurrent.TimeUnit

class MainActivity : ComponentActivity() {

    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null
    private var webSocket: WebSocket? = null

    // UI State
    private val isConnected = mutableStateOf(false)
    private val transcriptions = mutableStateListOf<String>()

    // Coroutine control
    private val scope = CoroutineScope(Dispatchers.IO)
    private var recordingJob: Job? = null
    private var playbackJob: Job? = null

    // Channel to queue incoming audio chunks
    private val audioPlaybackQueue = Channel<ByteArray>(Channel.UNLIMITED)

    // Request permission launcher
    private val requestPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted: Boolean ->
        if (isGranted) connectToVela()
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    VelaApp()
                }
            }
        }
    }

    @Composable
    fun VelaApp() {
        val connected by isConnected

        Column(
            modifier = Modifier.padding(16.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text("Vela AI Client", style = MaterialTheme.typography.headlineMedium)
            Spacer(modifier = Modifier.height(16.dp))

            Button(onClick = {
                if (connected) disconnect() else checkPermissionAndConnect()
            }) {
                Text(if (connected) "Disconnect" else "Connect")
            }

            Spacer(modifier = Modifier.height(16.dp))

            Text("Logs:", style = MaterialTheme.typography.titleMedium)
            Spacer(modifier = Modifier.height(8.dp))

            // Transcription Logs
            Column {
                transcriptions.takeLast(5).forEach { text ->
                    Text(text)
                }
            }
        }
    }

    private fun checkPermissionAndConnect() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
            connectToVela()
        } else {
            requestPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun connectToVela() {
        val clientId = UUID.randomUUID().toString().take(8)
        val userId = 1
        // IMPORTANT: Replace with your Raspberry Pi's actual IP
        val url = "ws://192.168.178.144:8000/ws/audio/$clientId?user_id=$userId"

        val client = OkHttpClient.Builder()
            .readTimeout(0, TimeUnit.MILLISECONDS) // Keep connection alive
            .build()
        val request = Request.Builder().url(url).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                isConnected.value = true
                startRecording(webSocket)
                startPlayback()
                log("Connected to Vela")
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                // Parse the JSON config/transcriptions sent from the backend
                try {
                    val json = JSONObject(text)
                    when (json.getString("type")) {
                        "wake_detected" -> log("System is listening...")
                        "transcription" -> log("You: ${json.getString("text")}")
                        "turn_end" -> log("Assistant finished speaking.")
                        "audio_config" -> {
                            // Backend tells us its audio config
                            val rate = json.getInt("sample_rate")
                            setupAudioTrack(rate)
                        }
                    }
                } catch (e: Exception) {
                    e.printStackTrace()
                }
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                // Receive TTS audio chunks and queue them for playback
                scope.launch {
                    audioPlaybackQueue.send(bytes.toByteArray())
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                cleanup()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                log("Error: ${t.message}")
                cleanup()
            }
        })
    }

    private fun startRecording(webSocket: WebSocket) {
        val sampleRate = 16000
        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val bufferSize = AudioRecord.getMinBufferSize(sampleRate, channelConfig, audioFormat)

        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                sampleRate,
                channelConfig,
                audioFormat,
                bufferSize
            )

            audioRecord?.startRecording()

            recordingJob = scope.launch {
                val buffer = ByteArray(1280 * 2) // Send small chunks roughly matching openWakeWord requirement
                while (isActive) {
                    val read = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (read > 0) {
                        webSocket.send(buffer.copyOfRange(0, read).toByteString())
                    }
                }
            }
        } catch (e: SecurityException) {
            log("Audio permission denied.")
        }
    }

    private fun setupAudioTrack(sampleRate: Int = 16000) {
        audioTrack?.release()
        val bufferSize = AudioTrack.getMinBufferSize(
            sampleRate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )

        audioTrack = AudioTrack(
            AudioManager.STREAM_MUSIC,
            sampleRate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            bufferSize,
            AudioTrack.MODE_STREAM
        )
        audioTrack?.play()
    }

    private fun startPlayback() {
        // Fallback default track in case backend takes time to send audio_config
        setupAudioTrack()

        playbackJob = scope.launch {
            for (chunk in audioPlaybackQueue) {
                if (isActive) {
                    audioTrack?.write(chunk, 0, chunk.size)
                }
            }
        }
    }

    private fun disconnect() {
        webSocket?.close(1000, "User disconnected")
        cleanup()
    }

    private fun cleanup() {
        isConnected.value = false
        recordingJob?.cancel()
        playbackJob?.cancel()
        audioRecord?.stop()
        audioRecord?.release()
        audioTrack?.stop()
        audioTrack?.release()
        audioRecord = null
        audioTrack = null
        log("Disconnected.")
    }

    private fun log(message: String) {
        CoroutineScope(Dispatchers.Main).launch {
            transcriptions.add(message)
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        disconnect()
    }
}