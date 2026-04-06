# orchestration_service/run.py

import sys
import os

current_dir  = os.path.dirname(os.path.abspath(__file__))
services_dir = os.path.dirname(current_dir)
project_dir  = os.path.dirname(services_dir)

sys.path.insert(0, current_dir)
sys.path.insert(0, project_dir)

# ──► Force set the correct .env path BEFORE importing anything
os.environ["ENV_FILE"] = os.path.join(project_dir, ".env")

# ──► Also directly set TOOLS_BASE_URL to be safe
os.environ["TOOLS_BASE_URL"] = "http://34.236.125.125:8082"

print(f"\n{'='*60}")
print(f"   Project dir  : {project_dir}")
print(f"   Current dir  : {current_dir}")
print(f"   Shared exists: {os.path.exists(os.path.join(project_dir, 'shared'))}")
print(f"   .env exists  : {os.path.exists(os.path.join(project_dir, '.env'))}")
print(f"   TOOLS_BASE_URL: {os.environ.get('TOOLS_BASE_URL')}")
print(f"{'='*60}\n")

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8003,
        reload=True,
        log_level="debug",
    )