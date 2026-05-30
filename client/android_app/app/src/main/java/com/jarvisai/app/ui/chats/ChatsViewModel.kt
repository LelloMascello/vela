package com.jarvisai.app.ui.chats

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jarvisai.app.data.ChatSession
import com.jarvisai.app.data.SessionManager
import com.jarvisai.app.data.network.ApiResult
import com.jarvisai.app.data.network.ApiService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ChatsUiState(
    val isLoading:    Boolean           = true,
    val sessions:     List<ChatSession> = emptyList(),
    val filtered:     List<ChatSession> = emptyList(),
    val query:        String            = "",
    val errorMessage: String            = "",
    val deletedId:    String?           = null,
)

class ChatsViewModel(
    private val session:    SessionManager,
    private val webBaseUrl: String,
) : ViewModel() {

    private val api = ApiService(webBaseUrl)

    private val _ui = MutableStateFlow(ChatsUiState())
    val uiState: StateFlow<ChatsUiState> = _ui.asStateFlow()

    init { load() }

    fun load() {
        val username = session.username ?: return
        viewModelScope.launch {
            _ui.update { it.copy(isLoading = true, errorMessage = "") }
            when (val r = api.fetchChats(webBaseUrl, username)) {
                is ApiResult.Success -> {
                    val sorted = r.data.sortedByDescending { resolveTimestamp(it.createdAt) }
                    _ui.update { it.copy(isLoading = false, sessions = sorted, filtered = sorted) }
                }
                is ApiResult.Error -> {
                    _ui.update { it.copy(isLoading = false, errorMessage = r.message) }
                }
            }
        }
    }

    fun search(query: String) {
        _ui.update { state ->
            val filtered = if (query.isBlank()) state.sessions
            else fuzzyFilter(state.sessions, query)
            state.copy(query = query, filtered = filtered)
        }
    }

    fun clearSearch() = search("")

    fun deleteSession(chatId: String) {
        viewModelScope.launch {
            _ui.update { it.copy(errorMessage = "") }
            when (val r = api.deleteChat(webBaseUrl, chatId)) {
                is ApiResult.Success -> {
                    _ui.update { state ->
                        val newSessions = state.sessions.filter { it.resolveId() != chatId }
                        val newFiltered = state.filtered.filter { it.resolveId() != chatId }
                        state.copy(sessions = newSessions, filtered = newFiltered)
                    }
                }
                is ApiResult.Error -> {
                    _ui.update { it.copy(errorMessage = "Eliminazione fallita: ${r.message}") }
                }
            }
        }
    }

    // ── Helpers ───────────────────────────────────────────────────────────

    companion object {
        fun resolveTimestamp(raw: Any?): Long = when (raw) {
            is Long   -> raw
            is Double -> raw.toLong()
            is Map<*, *> -> (raw["\$date"] as? Long) ?: 0L
            else -> 0L
        }

        fun fuzzyScore(text: String, pattern: String): Int {
            if (pattern.isEmpty()) return 1
            val t = text.lowercase(); val p = pattern.lowercase()
            if (t.contains(p)) return 1000 - t.indexOf(p)
            var score = 0; var pi = 0; var consec = 0; var last = -1
            for (ti in t.indices) {
                if (pi >= p.length) break
                if (t[ti] == p[pi]) {
                    consec++
                    score += consec * 2 + (if (last == ti - 1) 4 else 0)
                    if (ti == 0 || t[ti - 1] == ' ') score += 6
                    last = ti; pi++
                } else consec = 0
            }
            return if (pi == p.length) score else 0
        }

        fun chatToSearchString(s: ChatSession): String =
            buildString {
                append(s.username); append(' ')
                s.chat.forEach { append(it.content); append(' ') }
            }

        fun fuzzyFilter(sessions: List<ChatSession>, query: String): List<ChatSession> =
            sessions
                .map { it to fuzzyScore(chatToSearchString(it), query.trim()) }
                .filter { it.second > 0 }
                .sortedByDescending { it.second }
                .map { it.first }
    }
}
