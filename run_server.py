#!/usr/bin/env python3
import sys
sys.path.insert(0, '/home/mrnova420/unified-router/src')

import uvicorn
from unified_router.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=3333, log_level="info")