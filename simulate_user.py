import os
import subprocess
import time
import httpx
import json
from pathlib import Path

# 1. Setup environment
os.environ['OPENROUTER_API_KEY'] = 'sk-sim-openrouter'
os.environ['GROQ_API_KEY'] = 'gsk-sim-groq'

print('--- Simulating New User Installation ---')
# 2. Run init --auto
subprocess.run(['python3', '-m', 'unified_router', 'init', '--auto', '--force'], check=True)
print('Init complete.')

# 3. Manually trigger OpenCode config (simulating user saying Yes)
from unified_router.config import configure_opencode
success, msg = configure_opencode()
print(f'OpenCode config: {success}, {msg}')

# 4. Start server in background
print('Starting server...')
server_proc = subprocess.Popen(['python3', '-m', 'unified_router', 'start'], 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
time.sleep(3) # Give it time to start

try:
    client = httpx.Client(base_url='http://127.0.0.1:3333', timeout=10.0)
    
    # 5. Verify Endpoints
    print('\n--- Verifying Endpoints ---')
    for endpoint in ['/', '/admin', '/analytics', '/settings', '/usage', '/health']:
        r = client.get(endpoint)
        print(f'{endpoint}: {r.status_code}')

    # 6. Simulate a request (This will fail in reality because keys are dummy, but we check the router's response)
    print('\n--- Simulating Request ---')
    payload = {
        'model': 'auto',
        'messages': [{'role': 'user', 'content': 'Hello!'}]
    }
    r = client.post('/v1/chat/completions', json=payload)
    print(f'Request status: {r.status_code}')
    
    # 7. Verify Analytics
    print('\n--- Verifying Analytics ---')
    u = client.get('/usage').json()
    print(f'Lifetime requests: {u.get("lifetime_requests")}')
    print(f'Lifetime tokens: {u.get("lifetime_tokens")}')
    
    # 8. Verify Settings Discovery
    print('\n--- Verifying Settings Discovery ---')
    s = client.get('/settings/api').json()
    prov_count = len(s.get('providers', {}))
    print(f'Providers found in settings: {prov_count}')
    if prov_count < 40:
        print(f'FAILURE: Expected 40+ providers, found {prov_count}')
    else:
        print('SUCCESS: All providers discovered.')

finally:
    server_proc.terminate()
    print('\nSimulation finished.')
