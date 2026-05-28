# OkHttp / WebSocket
-dontwarn okhttp3.**
-dontwarn okio.**
-keep class okhttp3.** { *; }

# Gson
-keep class com.google.gson.** { *; }
-keepattributes Signature
-keepattributes *Annotation*

# Flow.AI data models
-keep class com.jarvis.app.data.** { *; }
