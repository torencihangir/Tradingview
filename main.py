# -*- coding: utf-8 -*-
from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime
import pytz
from dotenv import load_dotenv
import traceback # Hata ayıklama için eklendi

# Ortam değişkenlerini yükle
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
BIST_ANALIZ_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")

app = Flask(__name__)

def load_json_file(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"❌ JSON yükleme hatası ({path}):", e)
        return {}

def send_telegram_message(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        }
        r = requests.post(url, json=data, timeout=10)
        print("📤 Telegram'a gönderildi:", r.status_code)
    except Exception as e:
        print("🚨 Telegram gönderim hatası:", e)

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print("🔥 /telegram tetiklendi!")  # Bu satırı göreceğiz mi?
    try:
        return "ok", 200
    except Exception as e:
        print("💥 HATA:", e)
        return "error", 500

def generate_analiz_response(tickers):
    data = load_json_file(ANALIZ_FILE)
    result_lines = []
    hisseler = []

    for t in tickers:
        hisse = data.get(t)
        if not hisse:
            result_lines.append(f"❌ {t} için veri bulunamadı.")
            continue

        puan = hisse.get("puan", 0)
        detaylar = hisse.get("detaylar", [])
        yorum = hisse.get("yorum", "")
        sektor = hisse.get("sektor", "")
        endustri = hisse.get("endustri", "")
        hedef_fiyat = hisse.get("hedef_fiyat", "?")
        fiyat = hisse.get("fiyat", "?")
        potansiyel = hisse.get("potansiyel", "?")
        analist_sayisi = hisse.get("analist_sayisi", "?")

        detay_text = "\n".join(detaylar)
        result_lines.append(f"📊 *{t} Analiz Sonuçları (Puan: {puan}):*\n{detay_text}\n🎯 Hedef Fiyat: {hedef_fiyat} / Fiyat: {fiyat}\n🚀 Potansiyel: %{potansiyel}\n👨‍💼 Analist Sayısı: {analist_sayisi}\n🏢 Sektör: {sektor}\n⚙️ Endüstri: {endustri}\n\n{t} için analiz tamamlandı. Toplam puan: {puan}.")
        hisseler.append((t, puan))

    # Puan sıralı liste
    hisseler.sort(key=lambda x: x[1], reverse=True)
    return "\n\n".join([x[1] for x in sorted(zip(hisseler, result_lines), key=lambda y: y[0][1], reverse=True)])

def generate_bist_analiz_response(tickers):
    data = load_json_file(BIST_ANALIZ_FILE)
    results = []
    emoji_map = {
        "peg oranı": "🎯",
        "f/k oranı": "💰",
        "net borç/favök": "🏦",
        "net dönem karı": "📈",
        "finansal borç": "📉",
        "net borç": "💸",
        "dönen varlıklar": "🔄",
        "duran varlıklar": "🏢",
        "toplam varlıklar": "🏛️",
        "özkaynak": "🧱",
        "default": "➡️"
    }

    for t in tickers:
        hisse = data.get(t)
        if not hisse:
            results.append(f"❌ {t} için detaylı analiz bulunamadı.")
            continue

        sembol = hisse.get("symbol", t)
        puan = hisse.get("score", "N/A")
        sinif = hisse.get("classification", "Belirtilmemiş")
        yorumlar = hisse.get("comments", [])

        yorum_lines = []
        for y in yorumlar:
            eklenecek = emoji_map["default"]
            for k, v in emoji_map.items():
                if k in y.lower():
                    eklenecek = v
                    break
            yorum_lines.append(f"{eklenecek} {y}")

        yorum_text = "\n".join(yorum_lines)
        results.append(f"📊 BİST Detaylı Analiz\n\n🏷️ Sembol: {sembol}\n📈 Puan: {puan}\n🏅 Sınıflandırma: {sinif}\n\n📝 Öne Çıkanlar:\n{yorum_text}")

    return "\n\n".join(results)

@app.route("/", methods=["GET"])
def index():
    return "SignalCihangir Bot Aktif!", 200

@app.route("/test", methods=["GET"])
def test():
    return "Test başarılı!", 200

if __name__ == "__main__":
    print("✅ Flask bot başlatılıyor...")
    app.run(host="0.0.0.0", port=5000)
