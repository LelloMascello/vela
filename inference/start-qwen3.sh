./llama-server \
  --model /home/leo/vela/inference/models/Qwen3VL-8B-Instruct-Q4_K_M.gguf \
  --mmproj /home/leo/vela/inference/models/mmproj-Qwen3VL-8B-Instruct-F16.gguf \
  --n-gpu-layers 99 \
  --ctx-size 8192 \
  --batch-size 256 \
  --host 0.0.0.0 \
  --port 8080