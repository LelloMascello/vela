#!/bin/bash

~/llama.cpp/build/bin/llama-server \
  --model ~/models/google-gemma-4-E2B-it-Q4_K_M.gguf \
  --mmproj ~/models/mmproj-BF16.gguf \
  --n-gpu-layers 99 \
  --ctx-size 8192 \
  --reasoning off