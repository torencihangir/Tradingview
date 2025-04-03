from flask import Flask, request
import requests
import os

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json()
    symbol = data.get("symbol", "UNKNOWN")
    signal_text = data.get("signal", "Sinyal Yok")

    msg = f"🚨 Sinyal Geldi!\n📈 {symbol} - {signal_text}"
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", params={{
        "chat_id": CHAT_ID,
        "text": msg
    }})
    return "OK", 200

@app.route("/")
def home():
    return "Webhook çalışıyor!", 200
