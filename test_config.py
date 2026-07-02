#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/mrnova420/unified-router/src')

from unified_router.config import configure_opencode, detect_api_key, _get_windows_home

print("Testing _get_windows_home...")
win_home = _get_windows_home()
print(f"Windows home: {win_home}")

print("\nTesting configure_opencode...")
ok, msg = configure_opencode()
print(f"Result: {ok} - {msg}")

print("\nTesting detect_api_key...")
# Test with a sample provider config
pcfg = {"env_key": "NVIDIA_API_KEY"}
key = detect_api_key(pcfg)
print(f"NVIDIA key detected: {key[:20] if key else 'None'}...")

pcfg = {"env_key": "OPENROUTER_API_KEY"}
key = detect_api_key(pcfg)
print(f"OpenRouter key detected: {key[:20] if key else 'None'}...")

pcfg = {"env_key": "GROQ_API_KEY"}
key = detect_api_key(pcfg)
print(f"Groq key detected: {key[:20] if key else 'None'}...")

pcfg = {"env_key": "GEMINI_API_KEY"}
key = detect_api_key(pcfg)
print(f"Gemini key detected: {key[:20] if key else 'None'}...")

pcfg = {"env_key": "OPENCODE_API_KEY"}
key = detect_api_key(pcfg)
print(f"OpenCode Zen key detected: {key[:20] if key else 'None'}...")