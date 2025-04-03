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

def generate_ozet_msg(filter_keyword=None):
    try:
        with open(LOG_FILE, "r") as f:
            logs = json.load(f)
    except:
        logs = []

    # Eğer filtre parametresi verilmişse, önce büyük harfe çevirip kontrol edelim.
    if filter_keyword:
        filter_keyword_upper = filter_keyword.upper()
        # Bilinen borsa isimleri (listeyi ihtiyaçlarınıza göre genişletebilirsiniz)
        known_exchanges = ["BINANCE", "OKX", "COINBASE", "BITTREX", "HUOBI"]
        if filter_keyword_upper in known_exchanges:
            # Sadece ilgili borsadan gelen sinyalleri alalım.
            logs = [log for log in logs if log.get("exchange", "").upper() == filter_keyword_upper]
        else:
            # Aksi halde, filtreyi sinyal tipi olarak kabul edip logun sinyal kısmında arayalım.
            logs = [log for log in logs if filter_keyword_upper in log.get("signal", "").upper()]

    kairi_20, kairi_30 = [], []
    mukemmel_alis, mukemmel_satis = [], []
    alis_sayim, satis_sayim = [], []

    for log in logs:
        signal_text = log.get("signal", "")
        symbol = log.get("symbol", "")
        exchange = log.get("exchange", "Bilinmiyor")

        if "KAIRI" in signal_text.upper():
            try:
                # Signal metninde "KAIRI" kelimesinden sonraki değeri çekiyoruz.
                kairi_val = float(signal_text.upper().split("KAIRI")[1].split()[0])
                if kairi_val <= -30:
                    kairi_30.append(f"{symbol} ({exchange}): {kairi_val}")
                elif kairi_val <= -20:
                    kairi_20.append(f"{symbol} ({exchange}): {kairi_val}")
            except:
                continue
        elif "MÜKEMMEL ALIŞ" in signal_text.upper():
            mukemmel_alis.append(f"{symbol} ({exchange})")
        elif "MÜKEMMEL SATIŞ" in signal_text.upper():
            mukemmel_satis.append(f"{symbol} ({exchange})")
        elif "ALIŞ SAYIMI" in signal_text.upper():
            alis_sayim.append(f"{symbol} ({exchange})")
        elif "SATIŞ SAYIMI" in signal_text.upper():
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
    return ozet_msg

@app.route("/ozet", methods=["GET", "POST"])
def ozet():
    ozet_msg = generate_ozet_msg()
    requests.get(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        params={
            "chat_id": CHAT_ID, 
            "text": ozet_msg,
            "parse_mode": "HTML"
        }
    )
    return "Özet gönderildi.", 200

@app.route("/telegram", methods=["POST"])
def telegram_update():
    update = request.get_json()
    if update and "message" in update:
        message = update["message"]
        chat_id = message["chat"]["id"]
        text = message.get("text", "").strip()

        if text.startswith("/ozet"):
            # "/ozet" komutundan sonra girilen serbest metni alıyoruz.
            free_text = text[len("/ozet"):].strip()  # Örneğin: "BINANCE" veya "KAIRI"
            ozet_msg = generate_ozet_msg(free_text) if free_text else generate_ozet_msg()
            requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                params={
                    "chat_id": chat_id,
                    "text": ozet_msg,
                    "parse_mode": "HTML"
                }
            )
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
