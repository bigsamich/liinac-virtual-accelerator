# EPICS PVA gateway: p4p SharedPV server bridging redis (NOT an IOC)
FROM python:3.11-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ make && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY pip2va ./pip2va
RUN pip install --no-cache-dir . && pip install --no-cache-dir p4p
CMD ["python", "-m", "pip2va.services.epics_gateway.main"]
