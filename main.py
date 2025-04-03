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
    data["timestamp"] = datetime.now().isoformat()
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

    msg = f"🚨 Sinyal Geldi!\n📈 {symbol} ({exchange})\n💬 {signal_text}"
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={"chat_id": CHAT_ID, "text": msg}
    )
    return "OK", 200

@app.route("/")
def home():
    return "Webhook çalışıyor!", 200

@app.route("/ozet", methods=["GET", "POST"])
def ozet():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

    kairi_20, kairi_30 = [], []
    mukemmel_alis, mukemmel_satis = [], []
    alis_sayim, satis_sayim = [], []

    for log in logs:
        signal_text = log.get("signal", "")
        symbol = log.get("symbol", "")
        exchange = log.get("exchange", "Bilinmiyor")

        if "KAIRI" in signal_text:
            try:
                kairi_val = float(signal_text.split("KAIRI")[1].split()[0])
                if kairi_val <= -30:
                    kairi_30.append(f"{symbol} ({exchange}): {kairi_val}")
                elif kairi_val <= -20:
                    kairi_20.append(f"{symbol} ({exchange}): {kairi_val}")
            except:
                continue
        elif "Mükemmel Alış" in signal_text:
            mukemmel_alis.append(f"{symbol} ({exchange})")
        elif "Mükemmel Satış" in signal_text:
            mukemmel_satis.append(f"{symbol} ({exchange})")
        elif "ALIŞ SAYIMI" in signal_text:
            alis_sayim.append(f"{symbol} ({exchange})")
        elif "SATIŞ SAYIMI" in signal_text:
            satis_sayim.append(f"{symbol} ({exchange})")

    ozet_msg = "📊 <b>Sinyal Özetin:</b>\n\n"

    if kairi_30:
        ozet_msg += "🔴 <b>KAIRI ≤ -30:</b>\n" + "\n".join(kairi_30) + "\n\n"
    if kairi_20:
        ozet_msg += "🟠 <b>KAIRI ≤ -20:</b>\n" + "\n".join(kairi_20) + "\n\n"
    if mukemmel_alis:
        ozet_msg += "🟢 <b>Mükemmel Alış:</b>\n" + "\n".join(mukemmel_alis) + "\n\n"
    if mukemmel_satis:
        ozet_msg += "🔵 <b>Mükemmel Satış:</b>\n" + "\n".join(mukemmel_satis) + "\n\n"
    if alis_sayim:
        ozet_msg += "📈 <b>Alış Sayımı Tamamlananlar:</b>\n" + "\n".join(alis_sayim) + "\n\n"
    if satis_sayim:
        ozet_msg += "📉 <b>Satış Sayımı Tamamlananlar:</b>\n" + "\n".join(satis_sayim) + "\n\n"

    if ozet_msg == "📊 <b>Sinyal Özetin:</b>\n\n":
        ozet_msg += "Henüz sinyal gelmemiş."

    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={
            "chat_id": CHAT_ID, 
            "text": ozet_msg,
            "parse_mode": "HTML"
        }
    )

    return "Özet gönderildi.", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
