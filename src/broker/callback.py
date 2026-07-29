"""
OAuth callback catcher for Upstox daily 2FA re-authentication.

Runs on EC2 at http://127.0.0.1:5000 behind nginx.
Nginx forwards:
    https://auth.vaniti.in/live/callback     → this app
    https://auth.vaniti.in/sandbox/callback  → this app

When Upstox redirects after login, it sends:
    https://auth.vaniti.in/<env>/callback?code=<auth_code>

This app:
1. Captures the auth code from the query string.
2. Writes it to a well-known file (/tmp/upstox_auth_code.txt) so the
   trading engine can read it and exchange it for an access token.
3. Returns a human-readable response so you can confirm it worked in a browser.

Deploy path on EC2: ~/apps/oauth-catcher/callback.py
Run with:
    source ~/apps/oauth-catcher/venv/bin/activate
    python callback.py
(use tmux so it survives SSH disconnect)
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from flask import Flask, request

app = Flask(__name__)

# The engine reads the auth code from this file after the OAuth redirect.
AUTH_CODE_FILE = Path("/tmp/upstox_auth_code.txt")


@app.route("/live/callback")
@app.route("/sandbox/callback")
def oauth_callback():
    code = request.args.get("code")
    env = "live" if request.path.startswith("/live") else "sandbox"

    if not code:
        return (
            f"<h2>No code received.</h2>"
            f"<p>Path: {request.path}</p>"
            f"<p>Args: {dict(request.args)}</p>",
            400,
        )

    # Write code + metadata atomically so the engine never reads a partial file.
    timestamp = datetime.now(timezone.utc).isoformat()
    content = f"code={code}\nenv={env}\ntimestamp={timestamp}\n"
    AUTH_CODE_FILE.write_text(content, encoding="utf-8")

    app.logger.info("Auth code captured for env=%s at %s", env, timestamp)

    return (
        f"<h2>✅ Auth code captured ({env}).</h2>"
        f"<p>You can close this tab. The trading engine will exchange "
        f"this code for an access token automatically.</p>"
        f"<p><small>Captured at {timestamp}</small></p>"
    )


@app.route("/health")
def health():
    """Simple liveness check — curl https://auth.vaniti.in/health"""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


if __name__ == "__main__":
    # Bind to localhost only — nginx handles TLS and forwards here.
    app.run(host="127.0.0.1", port=5000, debug=False)
