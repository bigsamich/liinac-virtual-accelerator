#!/bin/bash
# Virtual display -> real PyQt GUI -> VNC -> browser (noVNC).
set -e
export DISPLAY=:1
export LIBGL_ALWAYS_SOFTWARE=1
export GALLIUM_DRIVER=llvmpipe
export PIP2VA_SOFT_GL=1
export PIP2VA_MAXIMIZE=1
Xvfb :1 -screen 0 1920x1080x24 &
sleep 1
x11vnc -display :1 -forever -shared -nopw -quiet -noxdamage &
# root URL auto-scales the desktop to the browser (no right-side clipping)
cat > /usr/share/novnc/index.html <<'HTML'
<!doctype html><meta http-equiv="refresh"
 content="0; url=vnc.html?autoconnect=true&resize=scale&reconnect=true&show_dot=true">
HTML
# FORCE noVNC local scaling for every client (noVNC 1.6 ignores
# mandatory.json — it only honors options.settings). Patch ui.js so the
# 'resize' setting is mandatory=scale: the whole desktop always fits the
# browser window, no clipping, at any client resolution.
UIJS=/usr/share/novnc/app/ui.js
sed -i "s/UI.customSettings.mandatory = {};/UI.customSettings.mandatory = {resize: 'scale'};/" "$UIJS"
sed -i "s/UI.initSetting('resize', 'off')/UI.initSetting('resize', 'scale')/" "$UIJS"
grep -q "resize: 'scale'" "$UIJS" && echo 'noVNC scaling forced' || echo 'WARN: noVNC patch missed'
websockify --web /usr/share/novnc 6080 localhost:5900 &
python -m pip2va.mobile &
# restart the GUI if it ever exits; the display session persists
while true; do
    pip2va-gui || true
    echo "GUI exited; restarting in 3 s"
    sleep 3
done
