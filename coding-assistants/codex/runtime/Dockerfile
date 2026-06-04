FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y --allowerasing \
    git curl python3 python3-pip nodejs npm jq tar gzip which findutils openssh-clients \
 && dnf clean all

ARG CODEX_VERSION=0.137.0
RUN npm install -g @openai/codex@${CODEX_VERSION}

RUN useradd -m -d /home/agent -u 1000 agent

RUN pip3 install --quiet fastapi==0.115.12 uvicorn==0.34.3

COPY --chown=agent:agent main.py /app/main.py

WORKDIR /app
EXPOSE 8080

USER agent
CMD ["python3", "/app/main.py"]
