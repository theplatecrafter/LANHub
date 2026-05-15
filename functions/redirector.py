"""functions/redirector.py - GitHub URL redirector management."""

import os
import datetime
from git import Repo
from glob_vars import REDIRECTOR_PATH, PORT, git_log

HTML_FILENAME = "index.html"


def redirector_update(ip: str, port: int = PORT) -> bool:
    """Update the GitHub redirector page with new IP/port."""
    try:
        repo = Repo(REDIRECTOR_PATH)

        repo.remotes.origin.fetch()
        repo.git.reset("--hard", "origin/main")
        repo.git.clean("-fd")

        # Generate HTML redirector page
        new_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
    <meta http-equiv="Pragma" content="no-cache">
    <meta http-equiv="Expires" content="0">
    <title>HansHub Redirector</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; text-align: center; padding: 50px; background-color: #f4f4f9; color: #333; }}
        .card {{ max-width: 500px; margin: auto; background: white; padding: 30px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.1); }}
        .error-box {{ display: none; color: #721c24; background-color: #f8d7da; border: 1px solid #f5c6cb; padding: 15px; border-radius: 8px; margin-top: 20px; }}
        .loading-spinner {{ border: 4px solid #f3f3f3; border-top: 4px solid #3498db; border-radius: 50%; width: 30px; height: 30px; animation: spin 1s linear infinite; margin: 20px auto; }}
        @keyframes spin {{ 0% {{ transform: rotate(0deg); }} 100% {{ transform: rotate(360deg); }} }}
        a {{ color: #3498db; text-decoration: none; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="card">
        <h2>🛰️ HansHub Gateway</h2>

        <div id="checking">
            <p>Verifying connection to <b>{ip}</b>...</p>
            <div class="loading-spinner"></div>
        </div>

        <div id="error-msg" class="error-box">
            <h3>🚫 Connection Failed</h3>
            <p>You must be connected to the <b>same LAN (or Wi-Fi)</b> as the server to access this page.</p>
            <p>Current Target: <a href="http://{ip}:{port}">http://{ip}:{port}</a></p>
        </div>

        <p style="font-size: 0.9em; color: #666; margin-top: 20px;">
            If you aren't redirected in 5 seconds, you are likely on the wrong network or the server is offline.
        </p>
    </div>

    <script>
        const targetUrl = "http://{ip}:{port}";

        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 4000);

        fetch(targetUrl + "/static/pixel.png", {{ mode: 'no-cors', signal: controller.signal }})
            .then(() => {{
                window.location.replace(targetUrl);
            }})
            .catch((err) => {{
                document.getElementById("checking").style.display = "none";
                document.getElementById("error-msg").style.display = "block";
                console.log("Connection failed: ", err);
            }});
    </script>
</body>
</html>"""

        file_path = os.path.join(REDIRECTOR_PATH, HTML_FILENAME)
        with open(file_path, "w") as f:
            f.write(new_html)

        repo.index.add([HTML_FILENAME])
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        repo.index.commit(f"Update redirect to {ip}:{port} at {timestamp}")

        origin = repo.remote(name="origin")
        origin.push(force=True)

        git_log.info(f"Successfully updated GitHub redirect to http://{ip}:{port}")
        return True

    except Exception as e:
        git_log.error(f"Failed to update GitHub: {e}")
        return False
