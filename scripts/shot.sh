#!/bin/bash
# Screenshot an Officina page in headless Chrome (for agents checking their UI work).  shot.sh "<url or /path>" <out.png> [width] [height] [wait ms]
. "$(dirname "$0")/_env.sh"
U="$1"; [[ "$U" == /* ]] && U="http://127.0.0.1:$PORT$U"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless=new --hide-scrollbars=false \
  --window-size="${3:-1600},${4:-1000}" --timeout="${5:-6000}" --screenshot="$2" "$U" >/dev/null 2>&1
[ -f "$2" ] && echo "$2" || echo "screenshot failed"
