import urllib.request, json

for model in ["groq/llama-3.3-70b-versatile", "nvidia/meta/llama-3.1-8b-instruct", "openrouter/google/gemma-2-9b-it:free"]:
    print(f"\n--- Testing {model} ---")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Say hi in 3 words"}],
        "max_tokens": 20
    }).encode()
    req = urllib.request.Request("http://localhost:3333/v1/chat/completions", data=payload, headers={"Authorization": "Bearer unified-router", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as f:
            resp = json.load(f)
            print(f"OK - Model: {resp.get('model','?')}")
            print(f"Reply: {resp['choices'][0]['message']['content'][:100]}")
            break
    except urllib.error.HTTPError as e:
        body = e.read().decode()[:200]
        print(f"HTTP {e.code}: {body}")
    except Exception as e:
        print(f"Error: {e}")