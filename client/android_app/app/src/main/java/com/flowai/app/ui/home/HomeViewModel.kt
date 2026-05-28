package com.flowai.app.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.flowai.app.audio.AudioPlayer
import com.flowai.app.audio.MicRecorder
import com.flowai.app.data.ConversationTurn
import com.flowai.app.data.SessionManager
import com.flowai.app.data.network.ApiResult
import com.flowai.app.data.network.ApiService
import com.google.gson.Gson
import com.google.gson.JsonObject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import okhttp3.*
import java.nio.ByteOrder

// ── Phase ─────────────────────────────────────────────────────────────────

enum class Phase { IDLE, ROUTER, MAIN }

enum class AiState { WAITING, LISTENING, THINKING, SPEAKING, TIMEOUT }

// ── UI state ──────────────────────────────────────────────────────────────

data class HomeUiState(
    val phase:          Phase                = Phase.IDLE,
    val aiState:        AiState              = AiState.WAITING,
    val statusText:     String               = "disconnected",
    val routerWsUrl:    String               = "—",
    val mainWsUrl:      String               = "—",
    val frameSize:      Int                  = 1280,
    val wwScore:        Float                = 0f,
    val wwModelName:    String               = "—",
    val detectCount:    Int                  = 0,
    val framesSent:     Int                  = 0,
    val turnCount:      Int                  = 0,
    val reconnectCount: Int                  = 0,
    val errorCount:     Int                  = 0,
    val silenceLeft:    Float                = 10f,
    val conversation:   List<ConversationTurn> = emptyList(),
    val errorMessage:   String               = "",
)

class HomeViewModel(
    private val session:     SessionManager,
    private val webBaseUrl:  String,
) : ViewModel() {

    // ── Constants ─────────────────────────────────────────────────────────
    private val SILENCE_TIMEOUT_S   = 10f
    private val MAIN_FRAME_LENGTH   = 512
    private val ROUTER_FRAME_DEFAULT = 1280

    // ── Public state ──────────────────────────────────────────────────────
    private val _ui = MutableStateFlow(HomeUiState())
    val uiState: StateFlow<HomeUiState> = _ui.asStateFlow()

    // ── WebSocket + audio internals ───────────────────────────────────────
    private val client    = OkHttpClient()
    private val gson      = Gson()
    private var wsRouter  : WebSocket? = null
    private var wsMain    : WebSocket? = null
    private var savedRouterUrl: String? = null
    private var api       = ApiService(webBaseUrl)

    private val mic       = MicRecorder(viewModelScope)
    private val player    = AudioPlayer(viewModelScope)

    // PCM ring buffer – accumulates mic samples until a full frame is ready
    private val pcmBuf    = ArrayDeque<Short>()
    private var micMuted  = false
    private var currentFrameSize = ROUTER_FRAME_DEFAULT

    // Silence countdown
    private var silenceJob : kotlinx.coroutines.Job? = null
    private var timerFrozen = false

    // Track the current pending user turn index so we can fill in transcript
    private var pendingTurnIndex = -1

    init {
        player.onFinished = {
            // Mirror JS pendingDoneActions logic: re-open mic after TTS ends
            viewModelScope.launch(Dispatchers.Main) { onAudioQueueDrained() }
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    //  CONNECT
    // ═════════════════════════════════════════════════════════════════════

    fun connect(routerHost: String, routerFrame: Int) {
        val username = session.username ?: return
        val password = session.password ?: return
        currentFrameSize = routerFrame

        viewModelScope.launch {
            _ui.update { it.copy(statusText = "authenticating…") }
            when (val r = api.routerAuth(routerHost, username, password)) {
                is ApiResult.Error   -> _ui.update { it.copy(statusText = "auth failed", errorMessage = r.message) }
                is ApiResult.Success -> {
                    savedRouterUrl = r.data
                    startMic()
                    connectRouterWs(r.data)
                }
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    //  DISCONNECT
    // ═════════════════════════════════════════════════════════════════════

    fun disconnect() {
        wsRouter?.close(1000, "user disconnect"); wsRouter = null
        wsMain?.close(1000, "user disconnect");   wsMain   = null
        cleanup()
    }

    // ═════════════════════════════════════════════════════════════════════
    //  ROUTER WS
    // ═════════════════════════════════════════════════════════════════════

    private fun connectRouterWs(url: String) {
        val req = Request.Builder().url(url).build()
        wsRouter = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                micMuted = false
                pcmBuf.clear()
                _ui.update { it.copy(
                    phase       = Phase.ROUTER,
                    statusText  = "router ws",
                    routerWsUrl = url.removePrefix("ws://"),
                    frameSize   = currentFrameSize,
                ) }
            }
            override fun onMessage(ws: WebSocket, text: String) {
                handleRouterMessage(text)
            }
            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                _ui.update { it.copy(statusText = "ws error", errorCount = _ui.value.errorCount + 1) }
            }
            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                _ui.update { it.copy(routerWsUrl = "closed") }
            }
        })
    }

    private fun handleRouterMessage(text: String) {
        val obj = try { gson.fromJson(text, JsonObject::class.java) } catch (_: Exception) { return }

        if (obj.has("error")) {
            _ui.update { it.copy(errorCount = _ui.value.errorCount + 1) }
            return
        }

        // Wake-word score update
        if (obj.has("wake_word")) {
            val score = obj.get("best_score")?.asFloat ?: 0f
            val model = obj.get("best_model")?.asString ?: "—"
            _ui.update { it.copy(wwScore = score, wwModelName = model) }
            if (obj.get("wake_word").asBoolean) {
                _ui.update { it.copy(detectCount = _ui.value.detectCount + 1) }
            }
            return
        }

        // Redirect to main
        if (obj.has("ip") && obj.has("port")) {
            val ip       = obj.get("ip").asString
            val port     = obj.get("port").asInt
            val username = obj.get("username")?.asString ?: session.username ?: ""
            viewModelScope.launch(Dispatchers.Main) { switchToMain(ip, port, username) }
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    //  SWITCH TO MAIN
    // ═════════════════════════════════════════════════════════════════════

    private fun switchToMain(ip: String, port: Int, username: String) {
        wsRouter?.close(1000, "switching to main"); wsRouter = null
        val url = "ws://$ip:$port/ws?username=${java.net.URLEncoder.encode(username, "UTF-8")}"

        // Clear conversation for new session
        clearConversation()

        val req = Request.Builder().url(url).build()
        wsMain = client.newWebSocket(req, object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                currentFrameSize = MAIN_FRAME_LENGTH
                micMuted = false
                pcmBuf.clear()
                _ui.update { it.copy(
                    phase      = Phase.MAIN,
                    statusText = "main ws",
                    mainWsUrl  = "$ip:$port",
                    frameSize  = MAIN_FRAME_LENGTH,
                    aiState    = AiState.LISTENING,
                    silenceLeft = SILENCE_TIMEOUT_S,
                ) }
                startSilenceTimer()
                ws.send(gson.toJson(mapOf("type" to "mic_open")))
            }
            override fun onMessage(ws: WebSocket, text: String) {
                viewModelScope.launch(Dispatchers.Main) { handleMainMessage(text) }
            }
            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) {
                _ui.update { it.copy(statusText = "ws error", errorCount = _ui.value.errorCount + 1) }
                stopSilenceTimer()
            }
            override fun onClosed(ws: WebSocket, code: Int, reason: String) {
                _ui.update { it.copy(mainWsUrl = "closed") }
                player.clear()
                stopSilenceTimer()
                clearConversation()
            }
        })
    }

    // ═════════════════════════════════════════════════════════════════════
    //  MAIN WS MESSAGES
    // ═════════════════════════════════════════════════════════════════════

    private fun handleMainMessage(text: String) {
        val obj = try { gson.fromJson(text, JsonObject::class.java) } catch (_: Exception) { return }
        val type = obj.get("type")?.asString ?: return

        when (type) {
            "listening_stop" -> {
                micMuted = true
                pcmBuf.clear()
                // Add a pending user turn immediately (transcript = null)
                addPendingUserTurn()
                _ui.update { it.copy(aiState = AiState.THINKING) }
            }
            "tts_start" -> {
                _ui.update { it.copy(
                    aiState   = AiState.SPEAKING,
                    turnCount = _ui.value.turnCount + 1,
                ) }
                freezeTimer()
                startAiTurn()
            }
            "chunk" -> {
                val txt   = obj.get("text")?.asString
                val audio = obj.get("audio")?.asString
                if (!txt.isNullOrEmpty()) appendAiText(txt)
                if (!audio.isNullOrEmpty()) player.enqueue(audio)
            }
            "tts_end" -> { /* audio will drain, onFinished handles mic re-open */ }
            "done" -> {
                val fullText   = obj.get("full_text")?.asString ?: ""
                val transcript = obj.get("transcript")?.asString
                finaliseAiTurn(fullText)
                fillTranscript(transcript)
                // If audio still playing, pendingDoneActions will fire in onAudioQueueDrained
            }
            "silence_timeout" -> {
                _ui.update { it.copy(aiState = AiState.TIMEOUT) }
                switchBackToRouter()
            }
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    //  CONVERSATION HELPERS
    // ═════════════════════════════════════════════════════════════════════

    private fun addPendingUserTurn() {
        val newTurn = ConversationTurn(userText = null, aiText = null)
        val list    = _ui.value.conversation.toMutableList()
        list.add(newTurn)
        pendingTurnIndex = list.lastIndex
        _ui.update { it.copy(conversation = list) }
    }

    private fun fillTranscript(text: String?) {
        val idx = pendingTurnIndex
        if (idx < 0) return
        val list = _ui.value.conversation.toMutableList()
        if (idx >= list.size) return
        list[idx] = list[idx].copy(userText = text ?: "(no transcript)")
        pendingTurnIndex = -1
        _ui.update { it.copy(conversation = list) }
    }

    private fun startAiTurn() {
        val idx  = pendingTurnIndex.coerceAtLeast(0)
        val list = _ui.value.conversation.toMutableList()
        if (idx < list.size) {
            list[idx] = list[idx].copy(aiText = "", isStreamingAi = true)
        } else {
            list.add(ConversationTurn(aiText = "", isStreamingAi = true))
        }
        _ui.update { it.copy(conversation = list) }
    }

    private fun appendAiText(token: String) {
        val list = _ui.value.conversation.toMutableList()
        val idx  = list.indexOfLast { it.isStreamingAi }
        if (idx >= 0) {
            list[idx] = list[idx].copy(aiText = (list[idx].aiText ?: "") + token)
        }
        _ui.update { it.copy(conversation = list) }
    }

    private fun finaliseAiTurn(fullText: String) {
        val list = _ui.value.conversation.toMutableList()
        val idx  = list.indexOfLast { it.isStreamingAi }
        if (idx >= 0) {
            list[idx] = list[idx].copy(aiText = fullText, isStreamingAi = false)
        }
        _ui.update { it.copy(conversation = list) }
    }

    private fun clearConversation() {
        pendingTurnIndex = -1
        _ui.update { it.copy(conversation = emptyList()) }
    }

    fun clearConversationPublic() = clearConversation()

    // ═════════════════════════════════════════════════════════════════════
    //  AUDIO QUEUE DRAINED  (mirrors JS pendingDoneActions)
    // ═════════════════════════════════════════════════════════════════════

    private fun onAudioQueueDrained() {
        if (_ui.value.phase != Phase.MAIN) return
        micMuted = false
        pcmBuf.clear()
        unfreezeTimer()
        resetSilenceTimer()
        _ui.update { it.copy(aiState = AiState.WAITING) }
        wsMain?.send(gson.toJson(mapOf("type" to "mic_open")))
    }

    // ═════════════════════════════════════════════════════════════════════
    //  MIC  →  PCM frame assembly  →  WebSocket
    // ═════════════════════════════════════════════════════════════════════

    private fun startMic() {
        mic.onSamples = { samples ->
            if (!micMuted) pushSamples(samples)
        }
        mic.start()
    }

    private fun pushSamples(samples: ShortArray) {
        samples.forEach { pcmBuf.addLast(it) }

        val targetWs = if (_ui.value.phase == Phase.MAIN) wsMain else wsRouter
        if (targetWs == null) return

        while (pcmBuf.size >= currentFrameSize) {
            val frame = ShortArray(currentFrameSize) { pcmBuf.removeFirst() }

            // Convert to little-endian byte array (Int16 PCM)
            val bytes = ByteArray(frame.size * 2)
            val bb    = java.nio.ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            frame.forEach { bb.putShort(it) }

            targetWs.send(okio.ByteString.of(*bytes))
            _ui.update { it.copy(framesSent = it.framesSent + 1) }
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    //  SILENCE TIMER
    // ═════════════════════════════════════════════════════════════════════

    private fun startSilenceTimer() {
        stopSilenceTimer()
        timerFrozen = false
        silenceJob  = viewModelScope.launch(Dispatchers.Main) {
            while (true) {
                kotlinx.coroutines.delay(250)
                if (!timerFrozen) {
                    val next = (_ui.value.silenceLeft - 0.25f).coerceAtLeast(0f)
                    _ui.update { it.copy(silenceLeft = next) }
                }
            }
        }
    }

    private fun stopSilenceTimer()  { silenceJob?.cancel(); silenceJob = null }
    private fun resetSilenceTimer() { _ui.update { it.copy(silenceLeft = SILENCE_TIMEOUT_S) } }
    private fun freezeTimer()       { timerFrozen = true }
    private fun unfreezeTimer()     { timerFrozen = false }

    // ═════════════════════════════════════════════════════════════════════
    //  SWITCH BACK TO ROUTER
    // ═════════════════════════════════════════════════════════════════════

    private fun switchBackToRouter() {
        stopSilenceTimer()
        player.clear()
        micMuted = true
        wsMain?.close(1000, "silence timeout"); wsMain = null
        clearConversation()
        _ui.update { it.copy(
            reconnectCount = _ui.value.reconnectCount + 1,
            wwScore        = 0f,
            wwModelName    = "—",
        ) }
        val url = savedRouterUrl ?: run { cleanup(); return }
        currentFrameSize = ROUTER_FRAME_DEFAULT
        connectRouterWs(url)
    }

    // ═════════════════════════════════════════════════════════════════════
    //  CLEANUP
    // ═════════════════════════════════════════════════════════════════════

    private fun cleanup() {
        mic.stop()
        player.clear()
        stopSilenceTimer()
        micMuted = false
        pcmBuf.clear()
        savedRouterUrl = null
        clearConversation()
        _ui.update { HomeUiState() }
    }

    override fun onCleared() {
        super.onCleared()
        disconnect()
    }
}
