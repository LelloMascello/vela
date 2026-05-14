package com.vela.app.network

import com.google.gson.Gson
import com.vela.app.model.WsFrame
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import java.util.concurrent.TimeUnit

/**
 * WebSocket client for router.py.
 *
 * Protocol:
 *  1. Connect to ws://<ws_host>:<ws_port>
 *  2. Send  { type:"auth", token:"<JWT>" }
 *  3. Receive { type:"ready" }
 *  4. Stream raw PCM binary frames  →  [sendAudio]
 *  5. Receive either:
 *       – binary frame            → audio cue (WAV) to play
 *       – { type:"handoff", ... } → open EngineSocket
 *       – { type:"error",   ... } → surface error
 */
class RouterSocket(
    private val wsHost: String,
    private val wsPort: Int,
    private val token: String,
    private val onReady: () -> Unit,
    private val onAudioCue: (ByteArray) -> Unit,
    private val onHandoff: (host: String, port: Int) -> Unit,
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
            // Step 2 — send auth frame
            webSocket.send("""{"type":"auth","token":"$token"}""")
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val frame = runCatching { gson.fromJson(text, WsFrame::class.java) }
                .getOrNull() ?: return

            when (frame.type) {
                "ready"   -> onReady()
                "handoff" -> {
                    val host = frame.ws_host ?: return
                    val port = frame.ws_port ?: return
                    onHandoff(host, port)
                    webSocket.close(1000, "Handoff complete")
                }
                "error"   -> onError(frame.error ?: "Errore sconosciuto dal router")
            }
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            // Binary frame = audio cue WAV
            onAudioCue(bytes.toByteArray())
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            onError("Connessione al router persa: ${t.message}")
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            onClosed()
        }
    }
}
