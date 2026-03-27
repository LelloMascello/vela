#!/bin/bash
#cd "$(dirname "$0")"
#export LD_LIBRARY_PATH="$(dirname "$0"):$LD_LIBRARY_PATH"
./llama-server \
  --model ./models/Qwen2-VL-7B-Instruct-Q8_0.gguf \
  --mmproj ./models/mmproj-Qwen2-VL-7B-Instruct-f16.gguf \
  --n-gpu-layers 32 \
  --ctx-size 2048 \
  --batch-size 512 \
  --mlock \
  --host 0.0.0.0 \
  --port 8080