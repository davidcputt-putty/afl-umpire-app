"""Flask app serving the AFL Umpire Free Kick Tracker.

Usage:
    python web/app.py

Then visit http://localhost:5000
"""

import json
import os
from pathlib import Path

from flask import Flask, jsonify, render_template

app = Flask(__name__)
DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/round")
def api_round():
    """Fixtures with umpire analysis baked in."""
    path = DATA_DIR / "round_analysis.json"
    if not path.exists():
        return jsonify({"error": "No round analysis data. Run: python pipeline.py --round 1"}), 404
    data = json.loads(path.read_text())
    return jsonify(data)


@app.route("/api/appointments")
def api_appointments():
    """Raw appointment data (includes boundary/goal umpires)."""
    path = DATA_DIR / "appointments.json"
    if not path.exists():
        return jsonify([])
    data = json.loads(path.read_text())
    return jsonify(data)


@app.route("/api/meta")
def api_meta():
    """Dataset metadata for the UI."""
    profiles_path = DATA_DIR / "umpire_profiles.json"
    analysis_path = DATA_DIR / "round_analysis.json"
    return jsonify({
        "profiles_updated": os.path.getmtime(str(profiles_path)) if profiles_path.exists() else None,
        "analysis_updated": os.path.getmtime(str(analysis_path)) if analysis_path.exists() else None,
    })


if __name__ == "__main__":
    app.run(debug=True, port=5000)
