from flask import Flask, request
import requests
import os

app = Flask(__name__)

# Ortam değişkenlerinden token ve chat ID al
BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")

@app.route("/signal", methods=["POST"])
def signal():
    data = request.get_json()
    symbol = data.get("symbol", "UNKNOWN")
    signal_text = data.get("signal", "Sinyal Yok")

    # Telegram mesajı
    msg = f"🚨 Sinyal Geldi!\n📈 {symbol} - {signal_text}"

    # ✅ DÜZELTİLMİŞ SATIR: params artık doğru formatta
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={
            "chat_id": CHAT_ID,
            "text": msg
        }
    )
    return "OK", 200

@app.route("/")
def home():
    return "Webhook çalışıyor!", 200

if __name__ == "__main__":
    # Render bu portu verir, Flask bunu dinlemeli
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
