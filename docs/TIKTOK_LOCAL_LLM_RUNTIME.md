# TikTok Local LLM Runtime

## Purpose

TikTok LIVE requires low response latency. The local LLM path is therefore optimized for short, direct, streamable answers rather than long-form reasoning.

This mode is intended as an optional local provider alongside the existing cloud provider. The TikTok bridge remains responsible for LIVE connectivity, event normalization and TTS playback.

## Runtime target

Current development target on VM01:

- Runtime: LM Studio local server
- API: OpenAI-compatible endpoint
- Base URL: `http://127.0.0.1:1234/v1`
- GPU: NVIDIA GeForce RTX 3060 12 GB
- Model class: Gemma 4 12B GGUF
- Current test model: Gemma 4 12B Coder Fable5
- Preferred quantization: `Q4_K_M`
- GPU offload: maximum/full where VRAM allows

The provider and model must remain configurable. The implementation must not hard-code one model name.

## TikTok inference profile

Default live profile:

```yaml
mode: tiktok-live
reasoning: false
thinking: false
stream: true
context_length: 8192
max_output_tokens: 120
temperature: 0.6
gpu_offload: max
```

Allowed tuning range:

- Context: `8192` to `16384`
- Max output: roughly `80` to `150` tokens
- Temperature: approximately `0.5` to `0.7`

Do not enable long reasoning or chain-of-thought generation for ordinary TikTok chat responses. The system should request final answers only.

## Latency policy

The live path should be:

```text
TikTok event
  -> normalize message
  -> classify / prioritize
  -> local LLM
  -> stream final answer
  -> TTS queue
```

The live path should not become:

```text
TikTok event
  -> long reasoning pass
  -> secondary analysis pass
  -> long answer
  -> TTS
```

For normal chat, latency has priority over exhaustive reasoning.

## Answer policy

TikTok responses should:

- start quickly;
- be concise enough for spoken TTS;
- avoid long preambles;
- avoid exposing internal reasoning;
- avoid unnecessary lists unless the user explicitly asks for one;
- remain conversational and suitable for LIVE playback;
- stop generation when the answer is complete instead of filling the token budget.

## Streaming

Streaming must be enabled for the local provider whenever supported. The bridge should be able to forward partial final-answer text to the TTS pipeline in controlled chunks rather than waiting for an unnecessarily long complete response.

Chunking must not send raw reasoning, hidden-thought fields or incomplete tool-call payloads to TTS.

## Provider fallback

The local model is the default for ordinary low-risk LIVE chat once enabled.

Escalate to a stronger cloud model only when required, for example:

- complex multi-step reasoning;
- requests that exceed the local model's reliable capability;
- local provider failure or timeout;
- context overflow;
- operator-selected cloud mode.

A local failure must not block the TikTok event loop indefinitely. Apply a bounded timeout and continue processing queued LIVE events.

## Performance checks

Before enabling local inference for a stream, verify:

1. LM Studio server responds on `127.0.0.1:1234`.
2. The configured model is loaded successfully.
3. GPU offload is active.
4. `nvidia-smi` shows the LM Studio `llama-server` process using the RTX 3060.
5. VRAM remains below the stability limit.
6. A short generation test returns within the configured latency budget.

Do not silently fall back to CPU inference for the 12B TikTok model. CPU fallback is considered an unhealthy runtime state because it can stall VM01 and increase LIVE latency dramatically.

## Configuration requirement

Expose the live inference profile through configuration or the operator UI. At minimum the operator must be able to change:

- provider;
- endpoint;
- model identifier;
- context length;
- max output tokens;
- temperature;
- streaming on/off;
- reasoning/thinking on/off;
- timeout;
- cloud fallback on/off.

TikTok mode should default to reasoning/thinking disabled even when another NOEMA workload uses the same model with reasoning enabled.
