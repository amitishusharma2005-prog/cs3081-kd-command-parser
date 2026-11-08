#!/usr/bin/env bash
DEST="${1:?usage: wsl_copy_back.sh WINDOWS_FOLDER_AS_WSL_PATH}"
F="$HOME/cs3081-kd-command-parser/230103033.zip"
if [ -f "$F" ]; then cp -f "$F" "$DEST/" && echo copied; else echo "no zip yet"; exit 1; fi
