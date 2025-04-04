from flask import Flask, request
import requests
import os
import json
import openai
import yfinance as yf
from datetime import datetime
from collections import defaultdict

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN", "TOKEN_YOK")
CHAT_ID = os.getenv("CHAT_ID", "CHAT_ID_YOK")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "YOK")
LOG_FILE = "signals.json"

openai.api_key = OPENAI_API_KEY

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

@app.route("/ozet", methods=["GET", "POST"])
def ozet():
    filtre = request.args.get("filter", "").upper()

    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

    sinyaller = defaultdict(list)
    for log in logs:
        symbol = log.get("symbol", "")
        signal = log.get("signal", "").upper()
        exchange = log.get("exchange", "")
        sinyaller[symbol].append({"signal": signal, "exchange": exchange})

    güçlü_sinyaller = []
    kairi_20, kairi_30 = [], []
    mukemmel_alis, mukemmel_satis = [], []
    alis_sayim, satis_sayim = [], []

    for symbol, entries in sinyaller.items():
        has_kairi = False
        has_alis = False
        kairi_val = None
        exchange = "Bilinmiyor"

        for entry in entries:
            signal_text = entry["signal"]
            exchange = entry["exchange"]

            if filtre and filtre not in signal_text.upper() and filtre not in exchange.upper():
                continue

            if "KAIRI" in signal_text:
                try:
                    val = float(signal_text.split("KAIRI")[1].split()[0])
                    kairi_val = val
                    if val <= -30:
                        kairi_30.append(f"{symbol} ({exchange}): {val}")
                    elif val <= -20:
                        kairi_20.append(f"{symbol} ({exchange}): {val}")
                    if val <= -20:
                        has_kairi = True
                except:
                    continue

            if "MÜKEMMEL ALIŞ" in signal_text:
                mukemmel_alis.append(f"{symbol} ({exchange})")
                has_alis = True
            if "ALIŞ SAYIMI" in signal_text:
                alis_sayim.append(f"{symbol} ({exchange})")
                has_alis = True
            if "MÜKEMMEL SATIŞ" in signal_text:
                mukemmel_satis.append(f"{symbol} ({exchange})")
            if "SATIŞ SAYIMI" in signal_text:
                satis_sayim.append(f"{symbol} ({exchange})")

        if has_kairi and has_alis:
            güçlü_sinyaller.append(f"✅ {symbol} ({exchange}) - KAIRI: {kairi_val} ve Alış sinyali birlikte geldi")

    ozet_msg = "📊 <b>GÜÇLÜ EŞLEŞEN SİNYALLER:</b>\n\n"
    if güçlü_sinyaller:
        ozet_msg += "\n".join(güçlü_sinyaller) + "\n\n"
    else:
        ozet_msg += "Bugün eşleşen güçlü sinyal bulunamadı.\n\n"

    if kairi_30:
        ozet_msg += "🔴 <b>KAIRI ≤ -30:</b>\n" + "\n".join(kairi_30) + "\n\n"
    if kairi_20:
        ozet_msg += "🟠 <b>KAIRI ≤ -20:</b>\n" + "\n".join(kairi_20) + "\n\n"
    if mukemmel_alis:
        ozet_msg += "🟢 <b>Mükemmel Alış:</b>\n" + "\n".join(mukemmel_alis) + "\n\n"
    if alis_sayim:
        ozet_msg += "📈 <b>Alış Sayımı Tamamlananlar:</b>\n" + "\n".join(alis_sayim) + "\n\n"
    if mukemmel_satis:
        ozet_msg += "🔵 <b>Mükemmel Satış:</b>\n" + "\n".join(mukemmel_satis) + "\n\n"
    if satis_sayim:
        ozet_msg += "📉 <b>Satış Sayımı Tamamlananlar:</b>\n" + "\n".join(satis_sayim) + "\n\n"

    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={
            "chat_id": CHAT_ID,
            "text": ozet_msg,
            "parse_mode": "HTML"
        }
    )
    return "Ozet gönderildi", 200

@app.route("/telegram", methods=["POST"])
def telegram_update():
    update = request.get_json()
    if update and "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        if text.lower().startswith("/ozet"):
            free_text = text[len("/ozet"):].strip()
            if free_text:
                requests.get(f"http://localhost:10000/ozet?filter={free_text}")
            else:
                requests.get("http://localhost:10000/ozet")

        elif text.lower().startswith("/analiz"):
            borsa = text[len("/analiz"):].strip().upper()
            if not borsa:
                borsa = "NASDAQ"
            requests.get(f"http://localhost:10000/analiz?borsa={borsa}")
    return "OK", 200

@app.route("/")
def home():
    return "Webhook aktif", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
