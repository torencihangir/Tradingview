from flask import Flask, request
import requests
import os

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
