#!/bin/bash
# Virtual display -> real PyQt GUI -> VNC -> browser (noVNC).
set -e
export DISPLAY=:1
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export PIP2VA_SOFT_GL=1
Xvfb :1 -screen 0 1920x1080x24 &
sleep 1
x11vnc -display :1 -forever -shared -nopw -quiet -noxdamage &
websockify --web /usr/share/novnc 6080 localhost:5900 &
python -m pip2va.mobile &
# restart the GUI if it ever exits; the display session persists
while true; do
    pip2va-gui || true
    echo "GUI exited; restarting in 3 s"
    sleep 3
done
