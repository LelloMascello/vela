package com.jarvisai.app.ui.auth

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.jarvisai.app.data.SessionManager
import com.jarvisai.app.data.network.ApiResult
import com.jarvisai.app.data.network.ApiService
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class AuthUiState(
    val isLoading:   Boolean = false,
    val message:     String  = "",
    val isError:     Boolean = false,
    val navigateHome: Boolean = false,
)

class AuthViewModel(
    private val session:    SessionManager,
    private val webBaseUrl: String,
) : ViewModel() {

    private val api = ApiService(webBaseUrl)

    private val _uiState = MutableStateFlow(AuthUiState())
    val uiState: StateFlow<AuthUiState> = _uiState.asStateFlow()

    fun login(username: String, password: String) {
        if (username.isBlank() || password.isBlank()) {
            _uiState.update { it.copy(message = "Please fill in all fields.", isError = true) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = "Signing in…", isError = false) }
            when (val result = api.login(username, password)) {
                is ApiResult.Success -> {
                    session.username = result.data
                    session.password = password
                    _uiState.update { it.copy(isLoading = false, navigateHome = true) }
                }
                is ApiResult.Error -> {
                    _uiState.update { it.copy(isLoading = false, message = result.message, isError = true) }
                }
            }
        }
    }

    fun signup(username: String, password: String) {
        if (username.isBlank() || password.isBlank()) {
            _uiState.update { it.copy(message = "Please fill in all fields.", isError = true) }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isLoading = true, message = "Creating account…", isError = false) }
            when (val result = api.signup(username, password)) {
                is ApiResult.Success -> {
                    _uiState.update {
                        it.copy(isLoading = false,
                            message = "Account created for ${result.data}! You can now sign in.",
                            isError = false)
                    }
                }
                is ApiResult.Error -> {
                    _uiState.update { it.copy(isLoading = false, message = result.message, isError = true) }
                }
            }
        }
    }

    fun clearNavigation() { _uiState.update { it.copy(navigateHome = false) } }
}
