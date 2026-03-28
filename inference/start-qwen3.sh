#!/usr/bin/env bash
# start-qwen3.sh  –  Avvio llama-server ottimizzato per Ryzen 7 8840HS + AMD 780M iGPU
#
# NOTA SULLA GPU:
#   Il tuo laptop dispone di una iGPU AMD Radeon 780M con 4 GB VRAM dedicati.
#   llama.cpp supporta l'accelerazione AMD tramite il backend Vulkan (stabile)
#   o HIP/ROCm (richiede compilazione con -DGGML_HIP=ON e il driver ROCm installato).
#
#   Per abilitare Vulkan (raccomandato, funziona subito su Linux/Windows):
#     cmake .. -DGGML_VULKAN=ON
#   Poi usa --n-gpu-layers come già fai.
#
#   Verifica che l'accelerazione GPU sia attiva guardando i log di avvio:
#     "ggml_vulkan: Found 1 Vulkan device" → OK
#     "ggml_cuda: no CUDA devices found" → usa CPU (ricompila con Vulkan)

./llama-server \
  --model   /home/leo/vela/inference/models/Qwen3VL-8B-Instruct-Q4_K_M.gguf \
  --mmproj  /home/leo/vela/inference/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf \
  --n-gpu-layers 99 \
  --ctx-size 4096 \
  --batch-size 512 \
  --ubatch-size 512 \
  --threads 4 \
  --threads-batch 8 \
  --host 0.0.0.0 \
  --port 8080 \
  --no-mmap
#
# Variazioni rispetto all'originale:
#   --ctx-size 4096        → ridotto da 8192; per domande vocali brevi è più che sufficiente
#                            e libera VRAM/RAM per più layer GPU
#   --batch-size 512       → batch più grande → prefill più veloce (prima risposta)
#   --ubatch-size 512      → micro-batch allineato al batch (riduce overhead)
#   --threads 4            → thread per la generazione token (decoding): 4 core fisici
#                            sono ottimali; troppi = contesa di cache L3
#   --threads-batch 8      → thread per il prefill (prompt processing): usa tutti i core
#   --no-mmap              → carica il modello in RAM evitando page fault durante l'inferenza