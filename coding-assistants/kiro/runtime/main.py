# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""AgentCore Runtime health server."""

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from log import get_logger

logger = get_logger(__name__)

app = FastAPI()


@app.get("/ping")
@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


@app.post("/invocations")
async def invocations():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    logger.info("health_server_starting", extra={"port": 8080})
    uvicorn.run(app, host="0.0.0.0", port=8080)
