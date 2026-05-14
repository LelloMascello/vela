package com.vela.app.network

import com.google.gson.Gson
import com.vela.app.model.WsFrame
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString.Companion.toByteString
import java.util.concurrent.TimeUnit

/**
 * WebSocket client for main.py (the AI engine).
 *
 * Protocol:
 *  1. Connect to ws://<ws_host>:<ws_port>
 *  2. Stream raw PCM binary frames  →  [sendAudio]
 *  3. Receive JSON frames:
 *       { type:"response_chunk", text:"...", audio:"<base64 WAV>" }
 *       { type:"session_end",    reason:"silence" }
 *       { type:"error",          error:"..." }
 */
class EngineSocket(
    private val wsHost: String,
    private val wsPort: Int,
    private val onResponseChunk: (text: String, audioB64: String) -> Unit,
    private val onSessionEnd: (reason: String) -> Unit,
    private val onError: (String) -> Unit,
    private val onClosed: () -> Unit
) {
    private val gson   = Gson()
    private val client = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .build()

    private var ws: WebSocket? = null

    fun connect() {
        val request = Request.Builder()
            .url("ws://$wsHost:$wsPort")
            .build()
        ws = client.newWebSocket(request, Listener())
    }

    /** Send a raw PCM chunk as a binary WebSocket frame. */
    fun sendAudio(pcm: ByteArray) {
        ws?.send(pcm.toByteString())
    }

    fun close() {
        ws?.close(1000, "Client disconnect")
        ws = null
    }

    // ── WebSocketListener ─────────────────────────────────────────────────────

    private inner class Listener : WebSocketListener() {

        override fun onOpen(webSocket: WebSocket, response: Response) {
            // Engine is ready; audio streaming starts immediately from ViewModel
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val frame = runCatching { gson.fromJson(text, WsFrame::class.java) }
                .getOrNull() ?: return

            when (frame.type) {
                "response_chunk" -> {
                    val t = frame.text  ?: return
                    val a = frame.audio ?: return
                    onResponseChunk(t, a)
                }
                "session_end" -> onSessionEnd(frame.reason ?: "silence")
                "error"       -> onError(frame.error ?: "Errore sconosciuto dall'engine")
            }
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            onError("Connessione all'engine persa: ${t.message}")
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            onClosed()
        }
    }
}
