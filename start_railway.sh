#!/bin/bash
# Railway startup script.
# Writes secret files from environment variables, then starts the app.
set -e

# Write token.json from env var (paste the file contents into Railway env vars)
if [ -n "$TOKEN_JSON" ]; then
    echo "$TOKEN_JSON" > token.json
    echo "[startup] token.json written"
else
    echo "[startup] WARNING: TOKEN_JSON env var not set"
fi

# Write credentials file from env var
if [ -n "$CREDENTIALS_JSON" ]; then
    echo "$CREDENTIALS_JSON" > credentials.json
    echo "[startup] credentials.json written"
else
    echo "[startup] WARNING: CREDENTIALS_JSON env var not set"
fi

python run.py
