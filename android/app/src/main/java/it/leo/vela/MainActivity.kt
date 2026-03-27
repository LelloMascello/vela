package it.leo.vela // <-- ATTENZIONE: Rimetti il nome del tuo package originale qui!

import android.Manifest
import android.content.pm.PackageManager
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.os.Bundle
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.ContextCompat
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.*
import okio.ByteString
import java.io.File
import java.io.FileOutputStream

class MainActivity : ComponentActivity() {

    // --- INSERISCI QUI L'IP DEL TUO RASPBERRY PI 5 ---
    private val WS_URL = "ws://172.18.57.133:8765"
    // -------------------------------------------------

    private var webSocket: WebSocket? = null
    private val client = OkHttpClient()
    private var mediaRecorder: MediaRecorder? = null
    private var mediaPlayer: MediaPlayer? = null
    private lateinit var audioFile: File

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        // File temporaneo dove salveremo la nostra registrazione
        audioFile = File(cacheDir, "audio_record.m4a")

        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
                    VelaApp()
                }
            }
        }
        connectWebSocket()
    }

    private fun connectWebSocket() {
        val request = Request.Builder().url(WS_URL).build()
        webSocket = client.newWebSocket(request, object : WebSocketListener() {
            override fun onOpen(webSocket: WebSocket, response: Response) {
                Log.d("VelaWS", "Connesso al server!")
            }

            override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
                Log.d("VelaWS", "Ricevuti ${bytes.size} bytes dal TTS!")
                playAudioResponse(bytes.toByteArray())
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                Log.e("VelaWS", "Errore WebSocket: ${t.message}")
            }
        })
    }

    private fun startRecording() {
        mediaRecorder = MediaRecorder().apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setOutputFile(audioFile.absolutePath)
            prepare()
            start()
        }
    }

    private fun stopRecordingAndSend() {
        try {
            mediaRecorder?.apply {
                stop()
                release()
            }
            mediaRecorder = null

            // Leggiamo il file registrato e lo inviamo via WebSocket al Pi 5
            val bytes = audioFile.readBytes()
            webSocket?.send(ByteString.of(*bytes))
            Log.d("VelaWS", "Inviati ${bytes.size} bytes di audio al server")

        } catch (e: Exception) {
            Log.e("VelaWS", "Errore invio audio: ${e.message}")
        }
    }

    private fun playAudioResponse(audioData: ByteArray) {
        try {
            // Salviamo il WAV ricevuto da Piper in un file temporaneo
            val tempFile = File(cacheDir, "response.wav")
            val fos = FileOutputStream(tempFile)
            fos.write(audioData)
            fos.close()

            // Lo riproduciamo
            mediaPlayer = MediaPlayer().apply {
                setDataSource(tempFile.absolutePath)
                prepare()
                start()
            }
        } catch (e: Exception) {
            Log.e("VelaWS", "Errore riproduzione: ${e.message}")
        }
    }

    @Composable
    fun VelaApp() {
        var isRecording by remember { mutableStateOf(false) }
        var hasPermission by remember { mutableStateOf(false) }
        val context = LocalContext.current
        val coroutineScope = rememberCoroutineScope()

        val permissionLauncher = rememberLauncherForActivityResult(
            contract = ActivityResultContracts.RequestPermission()
        ) { isGranted -> hasPermission = isGranted }

        LaunchedEffect(Unit) {
            if (ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED) {
                hasPermission = true
            } else {
                permissionLauncher.launch(Manifest.permission.RECORD_AUDIO)
            }
        }

        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = "VELA Client",
                fontSize = 32.sp,
                fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(bottom = 50.dp)
            )

            // Pulsante "Premi e parla" stile Walkie-Talkie
            Box(
                modifier = Modifier
                    .size(200.dp)
                    .background(
                        color = if (isRecording) Color.Red else Color.Blue,
                        shape = CircleShape
                    )
                    .pointerInput(Unit) {
                        detectTapGestures(
                            onPress = {
                                if (hasPermission) {
                                    isRecording = true
                                    startRecording()
                                    tryAwaitRelease() // Aspetta che l'utente alzi il dito
                                    isRecording = false
                                    coroutineScope.launch(Dispatchers.IO) {
                                        stopRecordingAndSend()
                                    }
                                }
                            }
                        )
                    },
                contentAlignment = Alignment.Center
            ) {
                Text(
                    text = if (isRecording) "In ascolto..." else "Tieni premuto\nper parlare",
                    color = Color.White,
                    fontSize = 20.sp,
                    fontWeight = FontWeight.Bold,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center
                )
            }

            Spacer(modifier = Modifier.height(30.dp))
            Text(text = if (isRecording) "Rilascia per inviare" else "Pronto", color = Color.Gray)
        }
    }
}