from flask import Flask, request
import requests
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from collections import defaultdict

load_dotenv()
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
    try:
        data = request.get_json(force=True)
        symbol = data.get("symbol", "UNKNOWN")
        signal_text = str(data.get("signal", "No signal"))
        exchange = data.get("exchange", "Unknown Exchange")
        log_signal(data)

        msg = f"🚨 Signal Received!\n📈 {symbol} ({exchange})\n💬 {signal_text}"
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg},
            timeout=3
        )
        print("✅ Telegram mesajı gönderildi.")
        return "OK", 200
    except Exception as e:
        print("❌ Signal error:", e)
        return "Internal Server Error", 500

@app.route("/ozet", methods=["GET"])
def ozet():
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

    sinyaller = defaultdict(list)
    for log in logs:
        symbol = log.get("symbol", log.get("ticker", "")).upper()
        signal_raw = str(log.get("signal", log.get("message", "")))
        signal = signal_raw.upper()
        exchange = log.get("exchange", log.get("source", "UNKNOWN")).upper()
        sinyaller[symbol].append({"signal": signal, "exchange": exchange})

    güçlü_sinyaller = []
    kairi_30 = []
    kairi_20 = []
    mukemmel_alis = []
    mukemmel_satis = []
    alis_sayimi = []
    satis_sayimi = []

    for symbol, entries in sinyaller.items():
        has_kairi = False
        has_alis = False
        exchange = "UNKNOWN"

        for entry in entries:
            signal_text = entry["signal"]
            exchange = entry["exchange"]

            # KAIRI kontrolü
            if "KAIRI" in signal_text:
                try:
                    val = float(signal_text.split("KAIRI")[1].split()[0])
                    if val <= -30:
                        kairi_30.append(f"{symbol} ({exchange}): {val}")
                    elif val <= -20:
                        kairi_20.append(f"{symbol} ({exchange}): {val}")
                    if val <= -20:
                        has_kairi = True
                except:
                    pass

            if "ALIŞ" in signal_text:
                has_alis = True
            if "MÜKEMMEL ALIŞ" in signal_text:
                mukemmel_alis.append(f"{symbol} ({exchange})")
            if "MÜKEMMEL SATIŞ" in signal_text:
                mukemmel_satis.append(f"{symbol} ({exchange})")
            if "ALIŞ SAYIMI" in signal_text:
                alis_sayimi.append(f"{symbol} ({exchange})")
            if "SATIŞ SAYIMI" in signal_text:
                satis_sayimi.append(f"{symbol} ({exchange})")

        if has_kairi and has_alis:
            güçlü_sinyaller.append(f"✅ {symbol} ({exchange})")

    # Mesajın yapısını oluştur
    msg = "📊 GÜÇLÜ EŞLEŞEN SİNYALLER:\n"
    if güçlü_sinyaller:
        msg += "\n".join(güçlü_sinyaller)
    else:
        msg += "Bugün eşleşen güçlü sinyal bulunamadı."
    msg += "\n\n"

    if kairi_30:
        msg += "🔴 KAIRI ≤ -30:\n" + "\n".join(kairi_30) + "\n\n"
    if kairi_20:
        msg += "🟠 KAIRI ≤ -20:\n" + "\n".join(kairi_20) + "\n\n"
    if mukemmel_alis:
        msg += "🟢 Mükemmel Alış:\n" + "\n".join(mukemmel_alis) + "\n\n"
    if mukemmel_satis:
        msg += "🔵 Mükemmel Satış:\n" + "\n".join(mukemmel_satis) + "\n\n"
    if alis_sayimi:
        msg += "🟣 Alış Sayımı Tamamlandı:\n" + "\n".join(alis_sayimi) + "\n\n"
    if satis_sayimi:
        msg += "🟤 Satış Sayımı Tamamlandı:\n" + "\n".join(satis_sayimi) + "\n\n"

    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg},
            timeout=3
        )
    except Exception as e:
        print("❌ Telegram gönderim hatası:", e)
    return "Ozet gönderildi", 200

@app.route("/telegram", methods=["POST"])
def telegram_update():
    update = request.get_json()
    print("📩 TELEGRAM POST:", update)
    if update and "message" in update:
        message = update["message"]
        text = message.get("text", "").strip().lower()
        if text.startswith("/ozet"):
            try:
                requests.get("http://localhost:10000/ozet", timeout=3)
            except:
                print("❌ /ozet çağrısı başarısız oldu.")
    return "OK", 200

@app.route("/")
def home():
    return "Webhook aktif", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
