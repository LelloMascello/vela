package com.vela.app

import android.content.Intent
import android.content.SharedPreferences
import android.os.Bundle
import android.view.View
import android.view.inputmethod.EditorInfo
import androidx.appcompat.app.AppCompatActivity
import com.vela.app.databinding.ActivityLoginBinding

class LoginActivity : AppCompatActivity() {

    private lateinit var binding: ActivityLoginBinding
    private lateinit var prefs: SharedPreferences

    companion object {
        private const val PREFS_NAME   = "vela_prefs"
        private const val KEY_PI_HOST  = "pi_host"
        private const val KEY_USERNAME = "username"
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityLoginBinding.inflate(layoutInflater)
        setContentView(binding.root)

        prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)

        // Restore last-used values
        binding.etPiHost.setText(prefs.getString(KEY_PI_HOST, ""))
        binding.etUsername.setText(prefs.getString(KEY_USERNAME, ""))

        // Allow login via keyboard "Done" action on password field
        binding.etPassword.setOnEditorActionListener { _, actionId, _ ->
            if (actionId == EditorInfo.IME_ACTION_DONE) {
                attemptLogin()
                true
            } else false
        }

        binding.btnLogin.setOnClickListener { attemptLogin() }
    }

    private fun attemptLogin() {
        val piHost   = binding.etPiHost.text.toString().trim()
        val username = binding.etUsername.text.toString().trim()
        val password = binding.etPassword.text.toString()

        // Basic validation
        var valid = true

        if (piHost.isEmpty()) {
            binding.tilPiHost.error = "Inserisci l'indirizzo IP del Raspberry Pi"
            valid = false
        } else {
            binding.tilPiHost.error = null
        }

        if (username.isEmpty()) {
            binding.tilUsername.error = "Inserisci il nome utente"
            valid = false
        } else {
            binding.tilUsername.error = null
        }

        if (password.isEmpty()) {
            binding.tilPassword.error = "Inserisci la password"
            valid = false
        } else {
            binding.tilPassword.error = null
        }

        if (!valid) return

        // Save for next time
        prefs.edit()
            .putString(KEY_PI_HOST, piHost)
            .putString(KEY_USERNAME, username)
            .apply()

        // Pass credentials to MainActivity; the ViewModel will handle the HTTP login
        val intent = Intent(this, MainActivity::class.java).apply {
            putExtra("pi_host",  piHost)
            putExtra("username", username)
            putExtra("password", password)
        }
        startActivity(intent)
    }
}
