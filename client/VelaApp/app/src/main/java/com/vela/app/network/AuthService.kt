package com.vela.app.network

import com.google.gson.Gson
import com.vela.app.model.LoginError
import com.vela.app.model.LoginRequest
import com.vela.app.model.LoginResponse
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

/**
 * Handles POST /auth/login against auth.py (port 5001).
 */
class AuthService(private val piHost: String) {

    private val gson   = Gson()
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    private val JSON = "application/json; charset=utf-8".toMediaType()

    /** @return LoginResponse on success, throws on failure. */
    suspend fun login(username: String, password: String): LoginResponse =
        kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
            val body = gson.toJson(LoginRequest(username, password))
                .toRequestBody(JSON)

            val request = Request.Builder()
                .url("http://$piHost:5001/auth/login")
                .post(body)
                .build()

            client.newCall(request).execute().use { response ->
                val raw = response.body?.string() ?: ""
                when (response.code) {
                    200  -> gson.fromJson(raw, LoginResponse::class.java)
                    401  -> {
                        val err = runCatching { gson.fromJson(raw, LoginError::class.java) }
                            .getOrNull()?.error ?: "Credenziali non valide"
                        throw AuthException(err)
                    }
                    else -> throw AuthException("Errore server: HTTP ${response.code}")
                }
            }
        }
}

class AuthException(message: String) : Exception(message)
