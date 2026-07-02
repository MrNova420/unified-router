#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/mrnova420/unified-router/src')

from unified_router.main import app
print("import ok")

# Check if port 3333 is in use
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
result = sock.connect_ex(('127.0.0.1', 3333))
sock.close()
print(f"Port 3333 in use: {result == 0}")