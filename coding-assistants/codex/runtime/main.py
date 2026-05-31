# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

"""AgentCore Runtime health server."""

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()


@app.get("/ping")
@app.get("/health")
async def health():
    return JSONResponse({"status": "healthy"})


@app.post("/invocations")
async def invocations():
    return JSONResponse({"status": "ok"})


if __name__ == "__main__":
    print("Agent health server starting on port 8080", flush=True)
    uvicorn.run(app, host="0.0.0.0", port=8080)
