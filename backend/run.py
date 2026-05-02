"""Server launcher script."""

import os
import uvicorn
from app.config import settings

if __name__ == "__main__":
    is_container = os.getenv("RUNNING_IN_DOCKER", "false").lower() == "true"
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=not is_container,
        log_level="info",
    )
