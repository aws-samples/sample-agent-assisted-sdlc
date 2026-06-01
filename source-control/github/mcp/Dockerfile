FROM public.ecr.aws/docker/library/golang:1.25-alpine AS build

WORKDIR /build

RUN apk add --no-cache git

# Clone the official GitHub MCP server (pinned to release tag)
ARG GITHUB_MCP_VERSION=v1.1.1
RUN git clone --branch ${GITHUB_MCP_VERSION} --depth 1 https://github.com/github/github-mcp-server.git .

RUN CGO_ENABLED=0 go build -ldflags="-s -w" \
    -o /bin/github-mcp-server ./cmd/github-mcp-server

FROM public.ecr.aws/docker/library/python:3.14-slim

RUN pip install --no-cache-dir boto3==1.43.18 "PyJWT[crypto]==2.13.0" "aws-opentelemetry-distro==0.17.1"

COPY --from=build /bin/github-mcp-server /usr/local/bin/github-mcp-server
COPY main.py /server/main.py

WORKDIR /server

# AgentCore MCP Runtime service contract port
EXPOSE 8000

CMD ["opentelemetry-instrument", "python3", "main.py"]
