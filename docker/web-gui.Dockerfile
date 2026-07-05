# Full PyQt6 control-room GUI served in the browser via noVNC.
# Xvfb virtual display -> x11vnc -> websockify/noVNC on :6080.
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc novnc websockify \
        libgl1 libegl1 libglx-mesa0 libgl1-mesa-dri libglib2.0-0 \
        libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-keysyms1 \
        libxcb-shape0 libxcb-render-util0 libxcb-image0 libxcb-xkb1 \
        libdbus-1-3 libfontconfig1 fonts-dejavu-core && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY pip2va ./pip2va
RUN pip install --no-cache-dir ".[gui]" PyOpenGL flask

COPY docker/web-gui-entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
EXPOSE 6080 6081
CMD ["/entrypoint.sh"]
