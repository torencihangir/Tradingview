
from flask import Flask, request
import requests
import os
import json
from datetime import datetime

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")
LOG_FILE = "signals.json"

def log_signal(data):
    # Zaman damgası ekle
    data["timestamp"] = datetime.now().isoformat()
    # Eski logları oku
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

    logs.append(data)

    with open(LOG_FILE, "w") as f:
        json.dump(logs, f, indent=2)

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json()
    symbol = data.get("symbol", "UNKNOWN")
    signal_text = data.get("signal", "Sinyal Yok")
    exchange = data.get("exchange", "Borsa Bilinmiyor")

    log_signal(data)

    msg = f"🚨 Sinyal Geldi!
📈 {symbol} ({exchange})
💬 {signal_text}"
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg}
    )
    return "OK", 200

@app.route("/")
def home():
    return "Webhook çalışıyor!", 200
