package com.vela.app

import android.Manifest
import android.content.pm.PackageManager
import android.os.Bundle
import android.view.View
import androidx.activity.result.contract.ActivityResultContracts
import androidx.activity.viewModels
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.lifecycle.lifecycleScope
import com.vela.app.databinding.ActivityMainBinding
import com.vela.app.model.VelaState
import com.vela.app.ui.VelaViewModel
import kotlinx.coroutines.launch

class MainActivity : AppCompatActivity() {

    private lateinit var binding : ActivityMainBinding
    private val vm               : VelaViewModel by viewModels()

    // ── Permission launcher ───────────────────────────────────────────────────

    private val requestMic = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) startSession()
        else showPermissionError()
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        setupUi()
        observeState()

        // Auto-connect on first launch (credentials come from LoginActivity)
        if (savedInstanceState == null) {
            checkMicPermission()
        }
    }

    private fun setupUi() {
        binding.btnDisconnect.setOnClickListener {
            vm.disconnect()
            finish()  // go back to LoginActivity
        }

        binding.btnRetry.setOnClickListener {
            checkMicPermission()
        }
    }

    // ── State observation ─────────────────────────────────────────────────────

    private fun observeState() {
        lifecycleScope.launch {
            vm.ui.collect { state ->

                // Status label
                binding.tvStatus.text = state.statusText

                // Error card
                if (state.errorMessage != null) {
                    binding.cardError.visibility  = View.VISIBLE
                    binding.tvError.text          = state.errorMessage
                } else {
                    binding.cardError.visibility  = View.GONE
                }

                // Transcript
                if (state.transcript.isNotBlank()) {
                    binding.cardTranscript.visibility = View.VISIBLE
                    binding.tvTranscript.text          = state.transcript
                } else {
                    binding.cardTranscript.visibility = View.GONE
                }

                // Mic animation (pulse when actively streaming)
                val streaming = state.state == VelaState.LISTENING || state.state == VelaState.ACTIVE
                binding.ivMic.animate()
                    .scaleX(if (streaming) 1.15f else 1.0f)
                    .scaleY(if (streaming) 1.15f else 1.0f)
                    .setDuration(300)
                    .start()

                // State-specific icon tint
                val tintRes = when (state.state) {
                    VelaState.LISTENING      -> R.color.state_listening
                    VelaState.WAKE_DETECTED,
                    VelaState.ACTIVE         -> R.color.state_active
                    VelaState.RESPONDING     -> R.color.state_responding
                    VelaState.ERROR          -> R.color.state_error
                    else                     -> R.color.state_idle
                }
                binding.ivMic.setColorFilter(ContextCompat.getColor(this@MainActivity, tintRes))

                // Buttons
                binding.btnDisconnect.isEnabled = state.canDisconnect
                binding.btnRetry.visibility =
                    if (state.state == VelaState.ERROR) View.VISIBLE else View.GONE

                // Loading spinner
                binding.progressBar.visibility =
                    if (state.state == VelaState.CONNECTING) View.VISIBLE else View.GONE
            }
        }
    }

    // ── Permission + session start ────────────────────────────────────────────

    private fun checkMicPermission() {
        when {
            ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                    == PackageManager.PERMISSION_GRANTED -> startSession()
            shouldShowRequestPermissionRationale(Manifest.permission.RECORD_AUDIO) -> {
                // Show rationale, then request
                binding.cardError.visibility = View.VISIBLE
                binding.tvError.text = "L'app ha bisogno del microfono per funzionare. " +
                        "Premi Riprova per concedere il permesso."
                binding.btnRetry.visibility = View.VISIBLE
                binding.btnRetry.setOnClickListener {
                    requestMic.launch(Manifest.permission.RECORD_AUDIO)
                }
            }
            else -> requestMic.launch(Manifest.permission.RECORD_AUDIO)
        }
    }

    private fun startSession() {
        val piHost   = intent.getStringExtra("pi_host")   ?: return
        val username = intent.getStringExtra("username")  ?: return
        val password = intent.getStringExtra("password")  ?: return
        vm.connect(piHost, username, password)
    }

    private fun showPermissionError() {
        binding.cardError.visibility = View.VISIBLE
        binding.tvError.text = "Permesso microfono negato. " +
                "Abilitalo nelle impostazioni dell'app."
        binding.btnRetry.visibility  = View.GONE
        binding.btnDisconnect.isEnabled = true
    }

    override fun onBackPressed() {
        vm.disconnect()
        super.onBackPressed()
    }
}
