#!/usr/bin/env bash

set -Eeuo pipefail

readonly GUI_URL='http://localhost:6080/vnc.html?autoconnect=true&resize=scale'

case "$(uname -s)" in
    Darwin)
        open "${GUI_URL}"
        ;;
    Linux)
        xdg-open "${GUI_URL}"
        ;;
    *)
        printf 'Unsupported operating system. Open this URL in a browser:\n%s\n' "${GUI_URL}" >&2
        exit 1
        ;;
esac
