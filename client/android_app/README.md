# jarvis.ai Android

Kotlin / Jetpack Compose Android client for the **jarvis.ai** voice assistant backend.  
Mirrors the web app (home.js / chats.js) feature-for-feature as a native Android app.

---

## Project structure

```
app/src/main/java/com/jarvisai/app/
├── audio/
│   ├── MicRecorder.kt       – AudioRecord wrapper (PCM 16-bit mono at 16 kHz)
│   └── AudioPlayer.kt       – Sequential WAV chunk playback via AudioTrack
├── data/
│   ├── Models.kt            – ChatSession, ChatMessage, ConversationTurn
│   ├── SessionManager.kt    – SharedPreferences credential store
│   └── network/
│       └── ApiService.kt    – login, signup, routerAuth, fetchChats (OkHttp)
├── ui/
│   ├── theme/
│   │   ├── Color.kt         – Design tokens (matches web CSS variables)
│   │   ├── Type.kt          – Typography
│   │   └── Theme.kt         – MaterialTheme wrapper
│   ├── auth/
│   │   ├── AuthViewModel.kt
│   │   └── AuthScreen.kt    – Sign-in / Create-account card
│   ├── home/
│   │   ├── HomeViewModel.kt – Full WebSocket state machine (router → main phases)
│   │   └── HomeScreen.kt    – Phase panels, waveform, silence ring, conversation
│   └── chats/
│       ├── ChatsViewModel.kt – Fuzzy search + session loading
│       └── ChatsScreen.kt    – Expandable session cards with full Q&A thread
└── MainActivity.kt          – Single-activity host, Compose navigation, VM factory
```

---

## Setup

### 1. Server address

Open `MainActivity.kt` and change:

```kotlin
private val WEB_BASE_URL = "http://192.168.1.100:8005"
```

to the LAN IP (or hostname) of the machine running `website.py` (port **8005**).  
The router WebSocket host is entered at runtime in the Home screen connection field.

### 2. Backend ports (default)

| Service     | Port | Purpose                         |
|-------------|------|---------------------------------|
| website.py  | 8005 | HTTP API (login, signup, chats) |
| router.py   | 8000 | Wake-word WebSocket + /auth     |
| main.py     | 8002 | AI voice pipeline WebSocket     |

### 3. Build

```bash
# Android Studio → Sync Project with Gradle Files → Run
# or
./gradlew assembleDebug
```

Minimum SDK: **26** (Android 8.0).  
Target SDK: **35**.

---

## How it maps to the web app

| Web (JS)                         | Android (Kotlin)                        |
|----------------------------------|-----------------------------------------|
| `sessionStorage` (username/pwd)  | `SessionManager` (SharedPreferences)    |
| `connectRouterWs()`              | `HomeViewModel.connectRouterWs()`       |
| `switchToMain()`                 | `HomeViewModel.switchToMain()`          |
| `clearConvo()` on disconnect     | `clearConversation()` in close/cleanup  |
| `addUserTurn()` / `fillTranscript()` | `addPendingUserTurn()` / `fillTranscript()` |
| `enqueueAudio()` / `drainAudioQueue()` | `AudioPlayer.enqueue()` / drain loop  |
| `onSearch()` fuzzy filter        | `ChatsViewModel.fuzzyFilter()`          |
| Expandable chat cards            | `SessionCard` with `AnimatedVisibility` |

---

## Adding the transcript to main.py

The `done` message sent by `main.py` should include the transcript so the user
bubble can be filled in. Add `"transcript"` to the send call:

```python
await websocket.send_json({
    "type":      "done",
    "full_text": full_text,
    "transcript": transcript,   # ← add this line
})
```

---

## Permissions

```xml
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.RECORD_AUDIO" />
<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />
```

The mic permission is requested automatically on the Home screen.  
Connection itself is user-triggered via the "Connect & Start" button.
