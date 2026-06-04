FROM public.ecr.aws/amazonlinux/amazonlinux:2023

RUN dnf install -y --allowerasing \
    git curl python3 python3-pip nodejs npm jq tar gzip which findutils openssh-clients unzip \
 && dnf clean all

RUN useradd -m -d /home/agent -u 1000 agent

USER agent
ENV HOME=/home/agent
# Download installer separately for auditability; verify sha256 if Kiro publishes checksums
RUN curl -fsSL -o /tmp/kiro-install.sh https://cli.kiro.dev/install && \
    bash /tmp/kiro-install.sh && \
    rm /tmp/kiro-install.sh
USER root

RUN pip3 install --quiet fastapi==0.115.12 uvicorn==0.34.3

COPY --chown=agent:agent main.py /app/main.py
COPY --chown=agent:agent log.py /app/log.py

ENV PATH="/home/agent/.local/bin:${PATH}"
WORKDIR /app
EXPOSE 8080

USER agent
CMD ["python3", "/app/main.py"]
