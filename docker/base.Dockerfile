# CPU service image (timing, rf-sim, magnet-sim, diag-sim, mps)
FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY pip2va ./pip2va
RUN pip install --no-cache-dir .

# service selected by compose `command:`
CMD ["python", "-m", "pip2va.services.timing.main"]
