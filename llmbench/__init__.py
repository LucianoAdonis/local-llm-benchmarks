"""llmbench: repeatable speed tests for local LLM runtimes.

Dependency-free (Python 3.9+ standard library only) so the same file set runs on
Windows, macOS and Linux against any OpenAI-compatible endpoint: Strata, LM Studio,
llama.cpp, Ollama, MLX-LM, vLLM.
"""

__version__ = "0.1.0"

# Bump PROTOCOL_VERSION when metric definitions change so old and new results are
# never compared silently. Bump WORKLOAD_VERSION when generated prompt text changes.
PROTOCOL_VERSION = "2.0"
WORKLOAD_VERSION = "2.0"
RESULT_SCHEMA = "llmbench-result/2"
