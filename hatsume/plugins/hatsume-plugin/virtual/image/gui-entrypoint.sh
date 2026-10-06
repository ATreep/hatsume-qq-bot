#!/usr/bin/env bash
set -Eeuo pipefail
export DISPLAY="${DISPLAY:-:99}"
export SCREEN_WIDTH="${SCREEN_WIDTH:-1280}" SCREEN_HEIGHT="${SCREEN_HEIGHT:-800}" SCREEN_DEPTH="${SCREEN_DEPTH:-24}"
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/xdg-runtime}"
mkdir -p "$XDG_RUNTIME_DIR" /tmp/.X11-unix /work/gui-screenshots
chmod 700 "$XDG_RUNTIME_DIR"
if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
    printf 'Reusing active X server on %s.\n' "$DISPLAY"
else
    display_number="${DISPLAY#*:}"
    display_number="${display_number%%.*}"
    rm -f "/tmp/.X${display_number}-lock" "/tmp/.X11-unix/X${display_number}"
    Xvfb "$DISPLAY" -screen 0 "${SCREEN_WIDTH}x${SCREEN_HEIGHT}x${SCREEN_DEPTH}" -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
fi
for _ in $(seq 1 50); do xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 && break; sleep 0.1; done
xdpyinfo -display "$DISPLAY" >/dev/null 2>&1 || { cat /tmp/xvfb.log >&2; exit 1; }
install -d -m 755 /run/hatsume
export DBUS_SESSION_BUS_ADDRESS="unix:path=/run/hatsume/desktop-bus"
dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --fork
export GTK_MODULES="${GTK_MODULES:+${GTK_MODULES}:}gail:atk-bridge"
export QT_ACCESSIBILITY=1
/usr/libexec/at-spi-bus-launcher --launch-immediately >/tmp/at-spi.log 2>&1 &
DISPLAY="$DISPLAY" openbox --sm-disable >/tmp/openbox.log 2>&1 &
x11vnc -display "$DISPLAY" -forever -shared -rfbport 5900 -nopw -quiet >/tmp/x11vnc.log 2>&1 &
if command -v websockify >/dev/null 2>&1 && [ -d /usr/share/novnc ]; then websockify --web=/usr/share/novnc 6080 localhost:5900 >/tmp/novnc.log 2>&1 & fi
exec /work/hatsume/.container/supervise.sh
