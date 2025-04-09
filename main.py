
from flask import Flask, request
import json
import requests
import os

app = Flask(__name__)

# Sabit Token ve Chat ID
BOT_TOKEN = "7760965138:AAH4ZdrJjnXJ36UWZUh1f0-VWL-FyUBgh54"
CHAT_ID = "5686330513"

# Telegram'a mesaj gönderme fonksiyonu
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=data)

# Webhook'tan gelen TradingView sinyali buraya düşer
@app.route("/signal", methods=["POST"])
def receive_signal():
    data = request.json
    with open("signals.json", "a") as f:
        f.write(json.dumps(data) + "\n")

    symbol = data.get("symbol")
    exchange = data.get("exchange")
    signal = data.get("signal")

    message = f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({exchange})\n📍 _{signal}_"
    send_telegram_message(message)

    return "ok", 200

# Telegram komutu: /ozet
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    message = request.json["message"]
    text = message.get("text", "")
    chat_id = message["chat"]["id"]

    if text.startswith("/ozet"):
        summary = generate_summary()
        send_telegram_message(summary)

    return "ok", 200

# Sinyallerden özet çıkar (şimdilik dummy, sonra geliştirilecek)
def generate_summary():
    return "📊 GÜÇLÜ EŞLEŞEN SİNYALLER:\n\n(Burada özet mesaj olacak, daha sonra geliştireceğiz.)"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
