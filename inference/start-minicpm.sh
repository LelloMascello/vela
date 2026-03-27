#!/bin/bash
#cd "$(dirname "$0")"
#
#export LD_LIBRARY_PATH="$(dirname "$0"):$LD_LIBRARY_PATH"
#
./llama-server \
  --model ./models/ggml-model-Q4_K_M.gguf \
  --mmproj ./models/mmproj-model-f16.gguf \
  --n-gpu-layers 32 \
  --ctx-size 1024 \
  --batch-size 128 \
  --threads 8 \
  --threads-batch 8 \
  --mlock \
  --host 0.0.0.0 \
  --port 8080