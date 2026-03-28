package it.leo.vela // <-- CAMBIA QUESTO CON IL TUO PACKAGE REALE

import android.Manifest
import android.content.pm.PackageManager
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.os.Bundle
import android.util.Base64
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.*
import okhttp3.*
import org.json.JSONObject
import java.security.MessageDigest

class MainActivity : ComponentActivity() {

    // --- VARIABILI DI RETE E AUDIO ---
    private var webSocket: WebSocket? = null
    private val client = OkHttpClient()
    private val serverUrl = "ws://192.168.178.136:8765" // Sostituisci con l'IP del Pi 5

    private var audioRecord: AudioRecord? = null
    private var audioTrack: AudioTrack? = null
    private var isStreaming = false
    private var streamingJob: Job? = null

    private val micSampleRate = 16000 // Input per Whisper STT
    private val ttsSampleRate = 22050 // Output da Piper TTS

    // --- STATO DELL'INTERFACCIA (COMPOSE) ---
    private var isConnected by mutableStateOf(false)
    private var statusText by mutableStateOf("Disconnesso")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // Gestore per richiedere il permesso del microfono a runtime
        val requestPermissionLauncher = registerForActivityResult(
            ActivityResultContracts.RequestPermission()
        ) { isGranted ->
            if (!isGranted) {
                statusText = "Permesso microfono negato!"
            }
        }

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    Column(modifier = Modifier.padding(16.dp)) {
                        Text(
                            text = "VELA Client",
                            style = MaterialTheme.typography.headlineMedium
                        )
                        Spacer(modifier = Modifier.height(8.dp))
                        Text(
                            text = "Stato: $statusText",
                            style = MaterialTheme.typography.bodyLarge
                        )
                        Spacer(modifier = Modifier.height(24.dp))

                        Button(
                            onClick = {
                                // 1. Controllo Permessi
                                if (ContextCompat.checkSelfPermission(this@MainActivity, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
                                    requestPermissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
                                } else {
                                    // 2. Toggle Connessione
                                    if (!isConnected) {
                                        connectWebSocket()
                                    } else {
                                        disconnect()
                                    }
                                }
                            },
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            Text(if (isConnected) "Disconnetti e Ferma" else "Connetti a VELA")
                        }
                    }
                }
            }
        }
    }

    // ==========================================
    // GESTIONE WEBSOCKET E RICEZIONE (TTS)
    // ==========================================
    private fun connectWebSocket() {
        statusText = "Connessione in corso..."
        val request = Request.Builder().url(serverUrl).build()

        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                isConnected = true
                statusText = "Connesso. Avvio audio..."

                // Prepariamo l'altoparlante per le risposte
                initAudioTrack()

                // Inviamo le credenziali
                val authJson = JSONObject().apply {
                    put("type", "auth")
                    put("username", "alice")
                    put("password_hash", sha256("tua_password_segreta")) // Modifica la psw
                }
                webSocket.send(authJson.toString())

                // Avviamo la registrazione del microfono
                startAudioStreaming()
            }

            override fun onMessage(webSocket: WebSocket, text: String) {
                try {
                    val json = JSONObject(text)
                    when (json.optString("type")) {
                        "tts_chunk" -> {
                            val base64Audio = json.getString("data")
                            val audioBytes = Base64.decode(base64Audio, Base64.DEFAULT)
                            // Riproduzione immediata in streaming!
                            audioTrack?.write(audioBytes, 0, audioBytes.size)
                        }
                        "auth_result" -> {
                            val status = json.optString("status")
                            Log.d("VELA", "Auth: $status")
                            statusText = "Connesso (Auth: $status)"
                        }
                        else -> {
                            Log.d("VELA", "Ricevuto: $text")
                        }
                    }
                } catch (e: Exception) {
                    Log.e("VELA", "Errore parsing JSON: ${e.message}")
                }
            }

            override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                isConnected = false
                statusText = "Disconnesso"
                stopAudioStreaming()
                releaseAudioTrack()
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e("VELA", "Errore WebSocket", t)
                isConnected = false
                statusText = "Errore di rete"
                stopAudioStreaming()
                releaseAudioTrack()
            }
        })
    }

    private fun disconnect() {
        webSocket?.close(1000, "Chiusura manuale")
        webSocket = null
        isConnected = false
        statusText = "Disconnesso"
        stopAudioStreaming()
        releaseAudioTrack()
    }

    // ==========================================
    // GESTIONE MICROFONO (INVIO STT)
    // ==========================================
    private fun startAudioStreaming() {
        if (isStreaming) return
        isStreaming = true
        statusText = "In ascolto..."

        val channelConfig = AudioFormat.CHANNEL_IN_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val bufferSize = AudioRecord.getMinBufferSize(micSampleRate, channelConfig, audioFormat)

        try {
            audioRecord = AudioRecord(
                MediaRecorder.AudioSource.MIC,
                micSampleRate,
                channelConfig,
                audioFormat,
                bufferSize
            )
            audioRecord?.startRecording()

            streamingJob = CoroutineScope(Dispatchers.IO).launch {
                val buffer = ByteArray(bufferSize)
                var sequence = 0

                while (isStreaming && isActive) {
                    val readBytes = audioRecord?.read(buffer, 0, buffer.size) ?: 0
                    if (readBytes > 0) {
                        val base64Data = Base64.encodeToString(buffer, 0, readBytes, Base64.NO_WRAP)

                        val payload = JSONObject().apply {
                            put("type", "audio_chunk")
                            put("data", base64Data)
                            put("seq", sequence)
                        }

                        webSocket?.send(payload.toString())
                        sequence++
                    }
                }
            }
        } catch (e: SecurityException) {
            Log.e("VELA", "Permesso microfono non concesso", e)
            statusText = "Errore microfono"
        }
    }

    private fun stopAudioStreaming() {
        isStreaming = false
        streamingJob?.cancel()
        audioRecord?.stop()
        audioRecord?.release()
        audioRecord = null
    }

    // ==========================================
    // GESTIONE ALTOPARLANTE (RIPRODUZIONE TTS)
    // ==========================================
    private fun initAudioTrack() {
        val channelConfig = AudioFormat.CHANNEL_OUT_MONO
        val audioFormat = AudioFormat.ENCODING_PCM_16BIT
        val bufferSize = AudioTrack.getMinBufferSize(ttsSampleRate, channelConfig, audioFormat)

        audioTrack = AudioTrack.Builder()
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                    .build()
            )
            .setAudioFormat(
                AudioFormat.Builder()
                    .setEncoding(audioFormat)
                    .setSampleRate(ttsSampleRate)
                    .setChannelMask(channelConfig)
                    .build()
            )
            .setBufferSizeInBytes(bufferSize)
            .setTransferMode(AudioTrack.MODE_STREAM)
            .build()

        audioTrack?.play()
    }

    private fun releaseAudioTrack() {
        audioTrack?.stop()
        audioTrack?.release()
        audioTrack = null
    }

    // ==========================================
    // UTILITY
    // ==========================================
    private fun sha256(input: String): String {
        val bytes = MessageDigest.getInstance("SHA-256").digest(input.toByteArray())
        return bytes.joinToString("") { "%02x".format(it) }
    }

    override fun onDestroy() {
        super.onDestroy()
        disconnect()
    }
}