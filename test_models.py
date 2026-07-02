#!/usr/bin/env python3
import urllib.request, json

with urllib.request.urlopen("http://localhost:3333/v1/models") as f:
    d = json.load(f)
    print(f"Models: {len(d['data'])}")
    print([m['id'] for m in d['data'][:5]])