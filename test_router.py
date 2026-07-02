import urllib.request, json

req = urllib.request.Request("http://localhost:3333/v1/models", headers={"Authorization": "Bearer unified-router"})
with urllib.request.urlopen(req) as f:
    d = json.load(f)
    print(f"{len(d['data'])} models")
    for m in d['data'][:3]:
        print(f"  {m['id']}")

print("\n--- Test chat completion ---")
payload = json.dumps({
    "model": "openrouter/anthropic/claude-sonnet-5",
    "messages": [{"role": "user", "content": "Say hi in 3 words"}],
    "max_tokens": 20
}).encode()
req2 = urllib.request.Request("http://localhost:3333/v1/chat/completions", data=payload, headers={"Authorization": "Bearer unified-router", "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req2, timeout=30) as f:
        resp = json.load(f)
        print(f"Status: OK")
        print(f"Model: {resp.get('model','?')}")
        print(f"Reply: {resp['choices'][0]['message']['content'][:80]}")
except Exception as e:
    print(f"Error: {e}")