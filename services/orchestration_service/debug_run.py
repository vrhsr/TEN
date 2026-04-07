# orchestration_service/debug_run.py
import sys
import os

current_dir  = os.path.dirname(os.path.abspath(__file__))
services_dir = os.path.dirname(current_dir)
project_dir  = os.path.dirname(services_dir)

sys.path.insert(0, current_dir)
sys.path.insert(0, project_dir)

os.environ["ENV_FILE"] = os.path.join(project_dir, ".env")
# Tools URL is loaded from .env
# os.environ["TOOLS_BASE_URL"] = "https://app.staging.trillium.health/temporal-rcm-workflow"

import uvicorn
from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8005,
        reload=False,
        log_level="debug",
    )
