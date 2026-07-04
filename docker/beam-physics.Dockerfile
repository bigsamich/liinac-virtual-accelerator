# GPU physics image (CUDA 13 runtime, arm64/sbsa for DGX Spark)
FROM nvcr.io/nvidia/cuda:13.0.1-runtime-ubuntu24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /venv
ENV PATH=/venv/bin:$PATH

WORKDIR /app
COPY pyproject.toml README.md ./
COPY pip2va ./pip2va
# [ctk] pulls CUDA toolkit headers via pip so CuPy can JIT in a runtime image
RUN pip install --no-cache-dir . "cupy-cuda13x[ctk]"

CMD ["python", "-m", "pip2va.services.beam_physics.main"]
