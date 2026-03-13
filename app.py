from flask import Flask, jsonify, send_from_directory, abort
import os

app = Flask(__name__)

# Update these values when releasing a new version
VERSION = "2.6"
DOWNLOAD_URL = ""  # Leave empty to serve from this server, or set an external URL

UPDATES_DIR = os.path.dirname(__file__)


@app.route("/version")
def version():
    """Returns version info as JSON. ChessGym reads this to check for updates."""
    download_url = DOWNLOAD_URL if DOWNLOAD_URL else "https://chessgym-server.onrender.com/download"
    return jsonify({
        "version": VERSION,
        "download_url": download_url,
    })


@app.route("/download")
def download():
    """Serves main.py directly as a file download."""
    main_py = os.path.join(UPDATES_DIR, "main.py")
    if not os.path.isfile(main_py):
        abort(404, "main.py not found")
    return send_from_directory(
        UPDATES_DIR,
        "main.py",
        as_attachment=True,
        mimetype="text/x-python",
    )


@app.route("/")
def index():
    return "ChessGym Update Server"


if __name__ == "__main__":
    os.makedirs(UPDATES_DIR, exist_ok=True)
    app.run(host="0.0.0.0", port=5000, debug=True)
