#!/bin/bash
# Подготовка облачной сессии Claude Code: зависимости парсера, тесты и доверие CA прокси для Chromium.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR"

python3 -m pip install -q -r requirements.txt patchright pytest

# Исходящий HTTPS в облаке идёт через прокси со своим CA; Chromium читает NSS-хранилище ~/.pki/nssdb.
CA=/root/.ccr/agent-proxy-ca.crt
if [ -f "$CA" ]; then
  if ! command -v certutil >/dev/null 2>&1; then
    (apt-get install -y -q libnss3-tools >/dev/null 2>&1 || (apt-get update -q >/dev/null 2>&1 && apt-get install -y -q libnss3-tools >/dev/null 2>&1)) || true
  fi
  if command -v certutil >/dev/null 2>&1; then
    mkdir -p "$HOME/.pki/nssdb"
    [ -f "$HOME/.pki/nssdb/cert9.db" ] || certutil -d "sql:$HOME/.pki/nssdb" -N --empty-password
    certutil -d "sql:$HOME/.pki/nssdb" -L -n "CCR Agent Proxy CA" >/dev/null 2>&1 \
      || certutil -d "sql:$HOME/.pki/nssdb" -A -t "C,," -n "CCR Agent Proxy CA" -i "$CA"
  fi
fi

# Предустановленный Chromium, чтобы не передавать --chromium каждый раз
if [ -x /opt/pw-browsers/chromium ] && [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/opt/pw-browsers/chromium' >> "$CLAUDE_ENV_FILE"
fi
