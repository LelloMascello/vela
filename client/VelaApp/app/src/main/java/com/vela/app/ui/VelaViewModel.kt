package com.vela.app.ui

import android.app.Application
import android.util.Base64
import android.util.Log
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.vela.app.audio.AudioPlayer
import com.vela.app.audio.AudioRecorder
import com.vela.app.model.VelaState
import com.vela.app.model.VelaUiState
import com.vela.app.network.AuthException
import com.vela.app.network.AuthService
import com.vela.app.network.EngineSocket
import com.vela.app.network.RouterSocket
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

private const val TAG = "VelaViewModel"

class VelaViewModel(app: Application) : AndroidViewModel(app) {

    // ── Public state ──────────────────────────────────────────────────────────

    private val _ui = MutableStateFlow(VelaUiState())
    val ui: StateFlow<VelaUiState> = _ui.asStateFlow()

    // ── Private fields ────────────────────────────────────────────────────────

    private val recorder     = AudioRecorder()
    private val player       = AudioPlayer()

    private var authService  : AuthService?   = null
    private var routerSocket : RouterSocket?  = null
    private var engineSocket : EngineSocket?  = null

    private var micJob       : Job? = null
    private var jwtToken     : String = ""
    private var transcriptBuf: StringBuilder = StringBuilder()

    // ── Public API ────────────────────────────────────────────────────────────

    /**
     * Login + connect to the router.
     * @param piHost  IP of the Raspberry Pi (e.g. "192.168.1.42")
     */
    fun connect(piHost: String, username: String, password: String) {
        if (_ui.value.state != VelaState.IDLE && _ui.value.state != VelaState.ERROR) return

        setState(VelaState.CONNECTING, "Autenticazione in corso…")

        viewModelScope.launch {
            try {
                val auth = AuthService(piHost)
                val resp = auth.login(username, password)
                jwtToken = resp.token
                Log.d(TAG, "Login OK → ws://${resp.ws_host}:${resp.ws_port}")
                connectRouter(resp.ws_host, resp.ws_port)
            } catch (e: AuthException) {
                setError(e.message ?: "Errore autenticazione")
            } catch (e: Exception) {
                setError("Impossibile raggiungere il server: ${e.message}")
            }
        }
    }

    /** Disconnect from everything and go back to IDLE. */
    fun disconnect() {
        stopMic()
        routerSocket?.close(); routerSocket = null
        engineSocket?.close(); engineSocket = null
        transcriptBuf.clear()
        setState(VelaState.IDLE, "Disconnesso")
    }

    // ── Router ────────────────────────────────────────────────────────────────

    private fun connectRouter(wsHost: String, wsPort: Int) {
        routerSocket = RouterSocket(
            wsHost    = wsHost,
            wsPort    = wsPort,
            token     = jwtToken,
            onReady   = ::onRouterReady,
            onAudioCue = ::onAudioCue,
            onHandoff = ::onHandoff,
            onError   = ::onRouterError,
            onClosed  = ::onRouterClosed
        )
        routerSocket!!.connect()
    }

    private fun onRouterReady() {
        setState(VelaState.LISTENING, "In ascolto… dì \"Vela\" per iniziare", canDisconnect = true)
        startMic { pcm -> routerSocket?.sendAudio(pcm) }
    }

    private fun onAudioCue(wavBytes: ByteArray) {
        setState(VelaState.WAKE_DETECTED, "Wake word rilevata! Preparazione risposta…")
        viewModelScope.launch { player.playWav(wavBytes) }
    }

    private fun onHandoff(host: String, port: Int) {
        Log.d(TAG, "Handoff → ws://$host:$port")
        stopMic()
        routerSocket = null   // router closed its side
        connectEngine(host, port)
    }

    private fun onRouterError(msg: String) {
        Log.e(TAG, "Router error: $msg")
        setError(msg)
    }

    private fun onRouterClosed() {
        if (_ui.value.state == VelaState.WAKE_DETECTED) return  // handoff in progress
        if (_ui.value.state != VelaState.IDLE) setError("Connessione al router chiusa")
    }

    // ── Engine ────────────────────────────────────────────────────────────────

    private fun connectEngine(wsHost: String, wsPort: Int) {
        transcriptBuf.clear()
        engineSocket = EngineSocket(
            wsHost          = wsHost,
            wsPort          = wsPort,
            onResponseChunk = ::onResponseChunk,
            onSessionEnd    = ::onSessionEnd,
            onError         = ::onEngineError,
            onClosed        = ::onEngineClosed
        )
        engineSocket!!.connect()
        setState(VelaState.ACTIVE, "Sessione attiva — parla pure!", canDisconnect = true)
        startMic { pcm -> engineSocket?.sendAudio(pcm) }
    }

    private fun onResponseChunk(text: String, audioB64: String) {
        setState(VelaState.RESPONDING, "Risposta in corso…")
        transcriptBuf.append(text).append(" ")
        _ui.update { it.copy(transcript = transcriptBuf.toString().trim()) }

        viewModelScope.launch {
            try {
                val wavBytes = Base64.decode(audioB64, Base64.DEFAULT)
                player.playWav(wavBytes)
            } catch (e: Exception) {
                Log.e(TAG, "Audio decode error: ${e.message}")
            }
        }
    }

    private fun onSessionEnd(reason: String) {
        Log.d(TAG, "Session ended: $reason")
        stopMic()
        engineSocket = null
        setState(VelaState.IDLE, "Sessione terminata ($reason). Premi connetti per ricominciare.")
    }

    private fun onEngineError(msg: String) {
        Log.e(TAG, "Engine error: $msg")
        setError(msg)
    }

    private fun onEngineClosed() {
        if (_ui.value.state != VelaState.IDLE) setError("Connessione all'engine chiusa inaspettatamente")
    }

    // ── Mic helpers ───────────────────────────────────────────────────────────

    private fun startMic(onChunk: (ByteArray) -> Unit) {
        stopMic()
        micJob = viewModelScope.launch {
            recorder.chunks().collect { chunk -> onChunk(chunk) }
        }
        Log.d(TAG, "Microphone started")
    }

    private fun stopMic() {
        micJob?.cancel()
        micJob = null
        Log.d(TAG, "Microphone stopped")
    }

    // ── State helpers ─────────────────────────────────────────────────────────

    private fun setState(state: VelaState, msg: String, canDisconnect: Boolean = false) {
        _ui.update { it.copy(state = state, statusText = msg, errorMessage = null, canDisconnect = canDisconnect) }
    }

    private fun setError(msg: String) {
        stopMic()
        routerSocket?.close(); routerSocket = null
        engineSocket?.close(); engineSocket = null
        _ui.update { it.copy(state = VelaState.ERROR, statusText = "Errore", errorMessage = msg, canDisconnect = false) }
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCleared() {
        super.onCleared()
        disconnect()
    }
}
