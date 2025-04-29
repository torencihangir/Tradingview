# -*- coding: utf-8 -*-
from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime, timedelta
import pytz # Zaman dilimi için
from dotenv import load_dotenv
import traceback # Hata ayıklama için
import math # Analiz sıralaması için sonsuzluk kullanma ihtimaline karşı

# .env dosyasını yükle (Script ile aynı dizinde veya üst dizinlerde olmalı)
load_dotenv()

app = Flask(__name__)

# --- Global Değişkenler ve Ayarlar ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")
try:
    TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Istanbul"))
except pytz.exceptions.UnknownTimeZoneError:
    print(f"❌ Uyarı: .env TIMEZONE '{os.getenv('TIMEZONE')}' geçersiz. 'Europe/Istanbul' kullanılacak.")
    TIMEZONE = pytz.timezone("Europe/Istanbul")

# Bellekte verileri tutmak için
signals_data = {}
analiz_data = {}
bist_analiz_data = {}
last_signal_time = {}

# Eşzamanlılık için Kilitler
signals_lock = threading.Lock()
analiz_lock = threading.Lock()
bist_analiz_lock = threading.Lock()

# --- Yardımcı Fonksiyonlar ---

def escape_markdown_v2(text):
    """Telegram MarkdownV2 için özel karakterleri kaçırır."""
    if not isinstance(text, str):
        text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    text = text.replace('\\', '\\\\')
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

def send_telegram_message(message):
    """Telegram'a mesaj gönderir ve uzun mesajları böler (MarkdownV2)."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Hata: BOT_TOKEN veya CHAT_ID ayarlanmamış."); return
    escaped_message = message
    max_length = 4096
    for i in range(0, len(escaped_message), max_length):
        chunk = escaped_message[i:i+max_length]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": chunk, "parse_mode": "MarkdownV2"}
        try:
            r = requests.post(url, json=data, timeout=30)
            r.raise_for_status()
            print(f"✅ Telegram yanıtı: {r.status_code}")
            time.sleep(0.5)
        except requests.exceptions.Timeout: print(f"❌ Telegram API zaman aşımına uğradı.")
        except requests.exceptions.HTTPError as http_err:
            error_response = r.text
            print(f"❌ Telegram HTTP Hatası: {http_err} - Yanıt: {error_response}")
            print(f"❌ Gönderilemeyen mesaj parçası (ilk 100kr): {chunk[:100]}...")
        except requests.exceptions.RequestException as e: print(f"❌ Telegram'a mesaj gönderilemedi (RequestException): {e}")
        except Exception as e: print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}"); print(traceback.format_exc())

def load_json_file(filepath):
    """Genel JSON dosyası yükleme fonksiyonu."""
    try:
        if not filepath: print("❌ Hata: Geçersiz dosya yolu."); return None
        if not os.path.exists(filepath): print(f"⚠️ Uyarı: {filepath} bulunamadı."); return {}
        if os.path.getsize(filepath) == 0: print(f"⚠️ Uyarı: {filepath} boş."); return {}
        with open(filepath, "r", encoding="utf-8") as file: data = json.load(file)
        print(f"✅ {filepath} yüklendi."); return data
    except Exception as e:
        print(f"❌ Hata ({filepath} okuma): {e}")
        if isinstance(e, json.JSONDecodeError):
            try:
                with open(filepath, "r", encoding="utf-8") as f_err: print(f"Dosya başı: {f_err.read(200)}...")
            except Exception: pass
        print(traceback.format_exc()); return {}

def save_json_file(filepath, data):
    """Genel JSON dosyası kaydetme fonksiyonu."""
    try:
        if not filepath: print("❌ Hata: Geçersiz dosya yolu."); return False
        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory): os.makedirs(directory); print(f"ℹ️ Dizin oluşturuldu: {directory}")
        with open(filepath, "w", encoding="utf-8") as file: json.dump(data, file, ensure_ascii=False, indent=4)
        print(f"✅ Veri kaydedildi: {filepath}"); return True
    except Exception as e: print(f"❌ Hata ({filepath} yazma): {e}"); print(traceback.format_exc()); return False

def load_signals():
    """signals.json dosyasını yükler."""
    global signals_data, last_signal_time
    print(f"🔄 Sinyal verileri yükleniyor: {SIGNALS_FILE}")
    with signals_lock:
        loaded_data = load_json_file(SIGNALS_FILE)
        if loaded_data is not None:
            signals_data = loaded_data
            last_signal_time = {}
            for borsa, signal_list in signals_data.items():
                if signal_list:
                    try:
                        latest_signal = max(signal_list, key=lambda s: datetime.strptime(s.get('time', '1970-01-01 00:00:00 +0000')[:19], "%Y-%m-%d %H:%M:%S"))
                        last_signal_time[borsa] = latest_signal.get('time')
                    except Exception as dt_err: print(f"⚠️ {borsa} son sinyal zamanı hatası: {dt_err}")
            print(f"✅ Sinyal verileri yüklendi: {list(signals_data.keys())}")
        else:
            print("❌ Sinyal dosyası okuma hatası."); signals_data = signals_data or {}

def save_signals():
    """Bellekteki signals_data'yı dosyaya kaydeder."""
    print(f"💾 Sinyal verileri kaydediliyor: {SIGNALS_FILE}")
    with signals_lock:
        if not save_json_file(SIGNALS_FILE, signals_data): print(f"❌ Sinyal verileri kaydedilemedi: {SIGNALS_FILE}")

def load_analiz_data():
    """analiz.json dosyasını yükler."""
    global analiz_data
    print(f"🔄 Analiz verileri yükleniyor: {ANALIZ_FILE}")
    with analiz_lock:
        loaded_data = load_json_file(ANALIZ_FILE)
        if loaded_data is not None: analiz_data = loaded_data; print(f"✅ Analiz verileri yüklendi: {len(analiz_data)} kayıt.")
        else: print("❌ Analiz dosyası okuma hatası."); analiz_data = analiz_data or {}

def load_bist_analiz_data():
    """analiz_sonuclari.json dosyasını yükler."""
    global bist_analiz_data
    print(f"🔄 BIST Analiz verileri yükleniyor: {ANALIZ_SONUCLARI_FILE}")
    with bist_analiz_lock:
        loaded_data = load_json_file(ANALIZ_SONUCLARI_FILE)
        if loaded_data is not None: bist_analiz_data = loaded_data; print(f"✅ BIST Analiz verileri yüklendi: {len(bist_analiz_data)} kayıt.")
        else: print("❌ BIST Analiz dosyası okuma hatası."); bist_analiz_data = bist_analiz_data or {}

def parse_signal_line(line):
    """Gelen alert mesajını ayrıştırır (KAIRI, Matisay ve flag'leri de içerecek şekilde güncellenmeli)."""
    line = line.strip()
    if not line: return None

    # TEMEL ALANLAR (Mevcut koddan)
    data = {"raw": line, "borsa": "unknown", "symbol": "N/A", "type": "INFO", "source": "Belirtilmemiş",
            "kairi_value": None, "matisay_value": None, "alis_sinyali_flag": False,
            "mukemmel_alis_flag": False, "alis_sayimi_tamam_flag": False,
            "mukemmel_satis_flag": False, "satis_sayimi_tamam_flag": False}

    # 1. Borsa
    borsa_match = re.match(r"^(\w+)[:\s]+", line, re.IGNORECASE)
    if borsa_match:
        borsa_raw = borsa_match.group(1).lower()
        borsa_map = {"bist": "bist", "xu100": "bist", "nasdaq": "nasdaq", "ndx": "nasdaq",
                     "binance": "binance", "crypto": "binance", "bats": "bats", "us": "bats"}
        data["borsa"] = borsa_map.get(borsa_raw, borsa_raw)
        line = line[len(borsa_match.group(0)):].strip()

    # 2. Sembol
    symbol_match = re.search(r"\b([A-Z0-9\./-]{2,})\b", line)
    if symbol_match:
        data["symbol"] = symbol_match.group(1).upper()

    # 3. Sinyal Tipi
    if re.search(r"\b(AL|ALIM|LONG|BUY)\b", line, re.IGNORECASE): data["type"] = "BUY"
    elif re.search(r"\b(SAT|SATIM|SHORT|SELL)\b", line, re.IGNORECASE): data["type"] = "SELL"

    # 4. Zaman
    # ... (Mevcut zaman ayrıştırma kodu buraya eklenebilir) ...
    data["time"] = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z") # Şimdilik varsayılan

    # 5. Kaynak
    # ... (Mevcut kaynak ayrıştırma kodu buraya eklenebilir) ...

    # ----- YENİ ALANLARI AYRIŞTIRMA (ÖRNEK - Kendi alert formatınıza göre düzenleyin!) -----
    # Örnek alert: BIST:CWENE AL KAIRI:-28.67 Matisay:-15 flag:GucluAlis flag:MukemmelAlis
    try:
        kairi_match = re.search(r"KAIRI:?([-\d\.]+)", line, re.IGNORECASE)
        if kairi_match: data["kairi_value"] = float(kairi_match.group(1))

        matisay_match = re.search(r"Matisay:?([-\d\.]+)", line, re.IGNORECASE)
        if matisay_match: data["matisay_value"] = float(matisay_match.group(1))

        # Flag'leri kontrol et
        line_lower = line.lower()
        if "alış sinyali" in line_lower or "guclualis" in line_lower: data["alis_sinyali_flag"] = True # Güçlü Eşleşen için
        if "mükemmel alış" in line_lower or "mukemmelalis" in line_lower: data["mukemmel_alis_flag"] = True
        if "alış sayımı tamam" in line_lower or "alissayimtamam" in line_lower: data["alis_sayimi_tamam_flag"] = True
        if "mükemmel satış" in line_lower or "mukemmelsatis" in line_lower: data["mukemmel_satis_flag"] = True
        if "satış sayımı tamam" in line_lower or "satissayimtamam" in line_lower: data["satis_sayimi_tamam_flag"] = True

    except ValueError:
        print(f"⚠️ Sayısal değerler (KAIRI/Matisay) ayrıştırılamadı: {line}")
    except Exception as e:
         print(f"❌ Flag/Değer ayrıştırma hatası: {e} - Satır: {line}")

    # Zorunlu alan kontrolü
    if data["borsa"] == "unknown" or data["symbol"] == "N/A":
        print(f"❌ Ayrıştırma başarısız (borsa/sembol eksik): {data}")
        return None

    print(f"ℹ️ Ayrıştırılan Sinyal Verisi: {data}") # Ayrıştırılan tüm veriyi logla
    return data

def clear_signals():
    """Verileri temizler."""
    # (Kod aynı)
    global signals_data, analiz_data, bist_analiz_data, last_signal_time
    print("🧹 Tüm veriler temizleniyor...")
    success = True
    with signals_lock: signals_data, last_signal_time = {}, {}; success &= save_json_file(SIGNALS_FILE, {})
    with analiz_lock: analiz_data = {}; success &= (not os.path.exists(ANALIZ_FILE) or save_json_file(ANALIZ_FILE, {}))
    with bist_analiz_lock: bist_analiz_data = {}; success &= (not os.path.exists(ANALIZ_SONUCLARI_FILE) or save_json_file(ANALIZ_SONUCLARI_FILE, {}))
    print("✅ Temizlik sonucu:", "Başarılı" if success else "Hatalı")
    return success

def clear_signals_daily():
    """Günlük temizlik."""
    # (Kod aynı)
    CLEANUP_HOUR, CLEANUP_MINUTE = int(os.getenv("CLEANUP_HOUR", 0)), int(os.getenv("CLEANUP_MINUTE", 5))
    print(f"📅 Günlük temizlik: {CLEANUP_HOUR:02d}:{CLEANUP_MINUTE:02d}")
    while True:
        try:
            now = datetime.now(TIMEZONE)
            next_run = now.replace(hour=CLEANUP_HOUR, minute=CLEANUP_MINUTE, second=0, microsecond=0)
            if now >= next_run: next_run += timedelta(days=1)
            wait_seconds = (next_run - now).total_seconds()
            print(f"🌙 Sonraki temizlik: {next_run:%Y-%m-%d %H:%M:%S %Z} ({wait_seconds:.0f}s)")
            if wait_seconds > 0: time.sleep(wait_seconds) else: time.sleep(60); continue
            print(f"⏰ {datetime.now(TIMEZONE):%Y-%m-%d %H:%M:%S} - Temizlik başlıyor...")
            if clear_signals(): send_telegram_message("🧹 Günlük veriler temizlendi\\.")
            else: send_telegram_message("❌ Günlük temizlik hatası\\!")
            print("✅ Günlük temizlik tamamlandı."); time.sleep(60)
        except Exception as e: print(f"❌ Günlük temizlik hatası: {e}"); print(traceback.format_exc()); send_telegram_message("🚨 Temizlik görevinde hata\\!"); time.sleep(3600)

# --- Çekirdek Fonksiyonlar (Komut Yanıtları - GÜNCELLENDİ) ---

def generate_summary(target_borsa=None):
    """İstenen formata göre sinyal özeti oluşturur."""
    with signals_lock:
        # Filtrele (hedef borsa varsa)
        relevant_signals = []
        if target_borsa:
            target_borsa_lower = target_borsa.lower()
            # BIST_DLY ve BIST aynı kabul edilebilir
            if target_borsa_lower in ["bist_dly", "bist"]:
                 relevant_signals.extend(signals_data.get("bist", []))
                 # relevant_signals.extend(signals_data.get("bist_dly", [])) # Ayrıysa bunu da ekle
            elif target_borsa_lower in signals_data:
                 relevant_signals = signals_data.get(target_borsa_lower, [])
        else: # Tüm borsalar
            for signal_list in signals_data.values():
                relevant_signals.extend(signal_list)

        if not relevant_signals:
            if target_borsa:
                return f"ℹ️ `{escape_markdown_v2(target_borsa.upper())}` için kayıtlı sinyal bulunmamaktadır\\."
            else:
                return "ℹ️ Henüz kayıtlı sinyal bulunmamaktadır\\."

        # Sinyalleri kategorilere ayır
        guclu_eslesen = []
        kairi_neg30 = []
        kairi_neg20 = []
        matisay_neg25 = []
        mukemmel_alis = []
        alis_sayim = []
        mukemmel_satis = []
        satis_sayim = []

        for signal in relevant_signals:
            symbol = signal.get("symbol", "N/A")
            borsa = signal.get("borsa", "unknown").upper()
            kairi_val = signal.get("kairi_value")
            matisay_val = signal.get("matisay_value")
            alis_sinyali = signal.get("alis_sinyali_flag", False)
            mukemmel_alis_flag = signal.get("mukemmel_alis_flag", False)
            alis_sayimi_tamam_flag = signal.get("alis_sayimi_tamam_flag", False)
            mukemmel_satis_flag = signal.get("mukemmel_satis_flag", False)
            satis_sayimi_tamam_flag = signal.get("satis_sayimi_tamam_flag", False)

            # Güvenli Sayı Kontrolü
            kairi_num = None
            if kairi_val is not None:
                try: kairi_num = float(kairi_val)
                except (ValueError, TypeError): pass

            matisay_num = None
            if matisay_val is not None:
                try: matisay_num = float(matisay_val)
                except (ValueError, TypeError): pass

            # Kategorilere Ekleme
            if alis_sinyali and kairi_num is not None:
                 # Format: ✅ CWENE (BIST) \- KAIRI: -28.67 & Alış Sinyali
                 escaped_sym = escape_markdown_v2(symbol)
                 escaped_borsa = escape_markdown_v2(borsa)
                 escaped_kairi = escape_markdown_v2(f"{kairi_num:.2f}")
                 guclu_eslesen.append(f"✅ `{escaped_sym}` \\({escaped_borsa}\\) \\- KAIRI: {escaped_kairi} & Alış Sinyali")

            if kairi_num is not None:
                 escaped_sym = escape_markdown_v2(symbol)
                 escaped_borsa = escape_markdown_v2(borsa)
                 escaped_kairi = escape_markdown_v2(f"{kairi_num:.2f}")
                 if kairi_num <= -30:
                      # Format: AGROT (BIST): KAIRI -37.84
                     kairi_neg30.append(f"`{escaped_sym}` \\({escaped_borsa}\\): KAIRI {escaped_kairi}")
                 elif kairi_num <= -20:
                     # Format: ADBE (NASDAQ): KAIRI -22.79
                     kairi_neg20.append(f"`{escaped_sym}` \\({escaped_borsa}\\): KAIRI {escaped_kairi}")

            if matisay_num is not None and matisay_num < -25:
                 escaped_sym = escape_markdown_v2(symbol)
                 escaped_borsa = escape_markdown_v2(borsa)
                 escaped_matisay = escape_markdown_v2(f"{matisay_num:.2f}")
                 # Format: EUPWR (BIST): Matisay -25.82
                 matisay_neg25.append(f"`{escaped_sym}` \\({escaped_borsa}\\): Matisay {escaped_matisay}")

            if mukemmel_alis_flag:
                mukemmel_alis.append(f"`{escape_markdown_v2(symbol)}` \\({escape_markdown_v2(borsa)}\\)")
            if alis_sayimi_tamam_flag:
                alis_sayim.append(f"`{escape_markdown_v2(symbol)}` \\({escape_markdown_v2(borsa)}\\)")
            if mukemmel_satis_flag:
                mukemmel_satis.append(f"`{escape_markdown_v2(symbol)}` \\({escape_markdown_v2(borsa)}\\)")
            if satis_sayimi_tamam_flag:
                satis_sayim.append(f"`{escape_markdown_v2(symbol)}` \\({escape_markdown_v2(borsa)}\\)")


        # Çıktıyı Oluştur
        response_parts = []

        def add_section(title, items):
            if items:
                response_parts.append(f"{title}\n" + "\n".join(items))

        add_section("*📊 GÜÇLÜ EŞLEŞEN SİNYALLER:*", guclu_eslesen)
        add_section("*🔴 KAIRI ≤ \\-30:*", kairi_neg30)
        add_section("*🟠 KAIRI ≤ \\-20 \\(ama > \\-30\\):*", kairi_neg20)
        add_section("*🟣 Matisay < \\-25:*", matisay_neg25)
        add_section("*🟢 Mükemmel Alış:*", mukemmel_alis)
        add_section("*📈 Alış Sayımı Tamamlananlar:*", alis_sayim)
        add_section("*🔵 Mükemmel Satış:*", mukemmel_satis)
        add_section("*📉 Satış Sayımı Tamamlananlar:*", satis_sayim)

        if not response_parts: # Eğer hiçbir kategoriye giren sinyal yoksa
             if target_borsa:
                  return f"ℹ️ `{escape_markdown_v2(target_borsa.upper())}` için özetlenecek özel sinyal bulunamadı\\."
             else:
                  return "ℹ️ Özetlenecek özel sinyal bulunamadı\\."

        return "\n\n".join(response_parts)

def generate_analiz_response(tickers):
    """analiz.json'dan veri çeker, formatlar ve puana göre sıralar."""
    with analiz_lock:
        if not analiz_data:
             return f"⚠️ Genel Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_FILE))}`) yüklenemedi veya boş\\."

        results = []
        not_found = []

        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper()
            data = analiz_data.get(ticker)
            if data:
                try:
                    # Puanı sayısal değere çevir (sıralama için), hata durumunda -sonsuz
                    puan_val = float(data.get("puan", -math.inf))
                except (ValueError, TypeError):
                    puan_val = -math.inf # Sayısal olmayan puanlar en sona gelsin
                results.append({"ticker": ticker, "puan": puan_val, "data": data})
            else:
                not_found.append(ticker)

        # Sonuçları puana göre büyükten küçüğe sırala
        results.sort(key=lambda x: x["puan"], reverse=True)

        response_lines = []
        for result in results:
            data = result["data"]
            ticker = result["ticker"] # Orijinal ticker ismini kullanabiliriz

            # Verileri al ve escape et
            symbol = escape_markdown_v2(ticker) # Başlıkta ticker kullanılıyor örnekte
            puan_str = escape_markdown_v2(data.get("puan", "N/A"))
            yorum = escape_markdown_v2(data.get("yorum", "_Yorum bulunamadı_"))
            detaylar_list = data.get("detaylar", [])

            formatted_detaylar = ""
            if detaylar_list and isinstance(detaylar_list, list):
                escaped_detaylar = [escape_markdown_v2(d) for d in detaylar_list]
                formatted_detaylar = "\n".join(escaped_detaylar)
            else:
                formatted_detaylar = "_Detay bulunamadı\\._"

            # İstenen formata göre mesajı oluştur
            response_lines.append(
                f"📊 *{symbol}* Analiz Sonuçları \\(Puan: {puan_str}\\):\n" # Başlık
                f"{formatted_detaylar}\n\n" # Detaylar listesi ve boşluk
                f"{yorum}" # Yorum
            )

        # Bulunamayanları ekle
        for nf_ticker in not_found:
            response_lines.append(f"❌ `{escape_markdown_v2(nf_ticker)}` için temel analiz bulunamadı\\.")

        return "\n\n---\n\n".join(response_lines) # Analizler arasına ayırıcı ekle


def generate_bist_analiz_response(tickers):
    """analiz_sonuclari.json'dan veri çeker, istenen formatta listeler."""
    with bist_analiz_lock:
        if not bist_analiz_data:
             return f"⚠️ Detaylı BIST Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_SONUCLARI_FILE))}`) yüklenemedi veya boş\\."

        response_lines = []
        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper()
            data = bist_analiz_data.get(ticker)

            if data:
                # Verileri al ve escape et
                symbol = escape_markdown_v2(ticker) # Başlıkta ticker kullanılıyor
                score_str = escape_markdown_v2(data.get("score", "N/A"))
                classification = escape_markdown_v2(data.get("classification", "_Belirtilmemiş_"))
                comments = data.get("comments", [])

                formatted_comments_list = []
                if comments and isinstance(comments, list):
                    for comment in comments:
                        if not isinstance(comment, str): continue
                        # Yorumları escape et ve başına '- ' ekle
                        escaped_comment = escape_markdown_v2(comment)
                        formatted_comments_list.append(f"\\- {escaped_comment}") # Markdown tire için \-
                    formatted_comments = "\n".join(formatted_comments_list)
                else:
                    formatted_comments = "_Yorum bulunamadı\\._"

                # İstenen formata göre mesajı oluştur
                response_lines.append(
                    f"📊 *{symbol}* Detaylı Analiz:\n\n" # Başlık ve boş satır
                    f"📈 *Puan:* {score_str}\n"
                    f"🏅 *Sınıflandırma:* {classification}\n\n" # Boş satır
                    f"📝 *Öne Çıkanlar:*\n"
                    f"{formatted_comments}" # Yorum listesi
                )
            else:
                response_lines.append(f"❌ `{escape_markdown_v2(ticker)}` için detaylı BIST analizi bulunamadı\\.")

        return "\n\n---\n\n".join(response_lines) # Analizler arasına ayırıcı ekle

# --- Flask Endpointleri ---
# (Bu kısımlar önceki versiyonla aynı, değişiklik yok)

@app.route("/", methods=["GET"])
def home():
    signal_counts = {b: len(s) for b, s in signals_data.items()}
    return f"Bot Aktif! Sinyaller: {escape_markdown_v2(str(signal_counts))}", 200

@app.route("/signal", methods=["POST"])
def receive_signal():
    signal_text = request.data.decode("utf-8")
    print(f"--- Gelen Sinyal Raw ---\n{signal_text}\n------------------------")
    if not signal_text.strip(): print("⚠️ Boş sinyal verisi."); return "Boş veri", 400
    processed_count, new_signal_details = 0, []
    for line in signal_text.strip().split('\n'):
        if not line.strip(): continue
        parsed_data = parse_signal_line(line) # Güncellenmiş parse fonksiyonunu kullanır
        if parsed_data:
            borsa, symbol, signal_type, timestamp, source = parsed_data["borsa"].lower(), parsed_data["symbol"], parsed_data["type"], parsed_data["time"], parsed_data["source"]
            with signals_lock:
                signals_data.setdefault(borsa, []).append(parsed_data)
                last_signal_time[borsa] = timestamp
            icon = "🟢" if signal_type == "BUY" else ("🔴" if signal_type == "SELL" else "ℹ️")
            new_signal_details.append(
                f"{icon} *{escape_markdown_v2(borsa.upper())}* \\- `{escape_markdown_v2(symbol)}` "
                f"*{escape_markdown_v2(signal_type)}* "
                f"_(Kaynak: {escape_markdown_v2(source)})_ "
                f"\\({escape_markdown_v2(timestamp)}\\)"
            )
            processed_count += 1
            print(f"✅ Sinyal işlendi: {parsed_data}")
        else: print(f"⚠️ Sinyal ayrıştırılamadı: {line}")
    if processed_count > 0:
        save_signals()
        if new_signal_details: send_telegram_message("🚨 *Yeni Sinyal(ler) Alındı:*\n\n" + "\n".join(new_signal_details))
        return f"{processed_count} sinyal işlendi.", 200
    else:
        send_telegram_message(f"⚠️ Geçersiz formatta sinyal alındı:\n```\n{escape_markdown_v2(signal_text)}\n```")
        return "Gelen veride geçerli sinyal bulunamadı.", 400

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    webhook_start_time = time.time()
    try:
        update = request.json
        if not update: print("Boş JSON verisi."); return "ok", 200
        message = update.get("message") or update.get("edited_message")
        if not message: update_type = next((k for k in update if k != 'update_id'), '?'); print(f"Desteklenmeyen '{update_type}'."); return "ok", 200
        text, chat_info, user_info = message.get("text", "").strip(), message.get("chat"), message.get("from")
        if not chat_info or not user_info: print("❌ Sohbet/kullanıcı bilgisi eksik."); return "ok", 200
        chat_id, user_id, first_name, username = chat_info.get("id"), user_info.get("id"), user_info.get("first_name", ""), user_info.get("username", "N/A")
        if str(chat_id) != CHAT_ID: print(f"⚠️ Yetkisiz sohbet ID: {chat_id}"); return "ok", 200
        if not text: print("Boş mesaj."); return "ok", 200
        print(f">>> Mesaj (Chat:{chat_id}, User:{first_name}[{username}/{user_id}]): {text}")
        response_message, command_processed = None, False
        # Komut İşleme - Artık güncellenmiş generate fonksiyonlarını çağıracak
        if text.lower().startswith("/ozet"):
            command_processed = True; print(">>> /ozet komutu...")
            parts = text.split(maxsplit=1); keyword = parts[1].lower() if len(parts) > 1 else None
            # BIST_DLY'yi BIST olarak kabul et
            if keyword == "bist_dly": keyword = "bist"
            allowed_keywords = ["bist", "nasdaq", "bats", "binance"]
            if keyword and keyword not in allowed_keywords:
                 allowed_str = ", ".join([f"`{k}`" for k in allowed_keywords])
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{escape_markdown_v2(keyword)}`\\. İzin verilenler: {allowed_str} veya boş bırakın\\."
            else: response_message = generate_summary(keyword)
        elif text.lower().startswith("/analiz"):
            command_processed = True; print(">>> /analiz komutu...")
            tickers_input = text[len("/analiz"):].strip()
            if not tickers_input: response_message = "Lütfen hisse kodu belirtin\\. Örn: `/analiz GOOGL,AAPL`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers: response_message = "Geçerli hisse kodu bulunamadı\\. Örn: `/analiz GOOGL,AAPL`"
                else: print(f"Analiz istenen hisseler (/analiz): {tickers}"); response_message = generate_analiz_response(tickers)
        elif text.lower().startswith("/bist_analiz"):
            command_processed = True; print(">>> /bist_analiz komutu...")
            tickers_input = text[len("/bist_analiz"):].strip()
            if not tickers_input: response_message = "Lütfen BIST hisse kodu belirtin\\. Örn: `/bist_analiz EREGL,TUPRS`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers: response_message = "Geçerli hisse kodu bulunamadı\\. Örn: `/bist_analiz EREGL,TUPRS`"
                else: print(f"Detaylı analiz istenen hisseler (/bist_analiz): {tickers}"); response_message = generate_bist_analiz_response(tickers)
        elif text.lower().startswith("/clear_signals"):
             command_processed = True; print(">>> /clear_signals komutu...")
             if clear_signals(): response_message = "✅ Tüm veriler başarıyla temizlendi\\."
             else: response_message = "❌ Veriler temizlenirken hata oluştu\\."
        elif text.lower().startswith("/start") or text.lower().startswith("/help"):
            command_processed = True; print(">>> /start veya /help komutu...")
            response_message = ("👋 *Merhaba\\!* Komutlar:\n\n"
                                "• `/ozet`: Tüm özet\\.\n"
                                "• `/ozet [borsa]`: Belirli borsa \\(`bist`, `nasdaq`\\.\\.\\)\\.\n"
                                "• `/analiz [HİSSE,\\.\\.]`: Temel analiz \\(Örn: `/analiz AAPL`\\)\\.\n"
                                "• `/bist_analiz [HİSSE,\\.\\.]`: Detaylı BIST analizi \\(Örn: `/bist_analiz EREGL`\\)\\.\n"
                                "• `/clear_signals`: Verileri siler \\(Dikkat\\!\\)\\.\n"
                                "• `/help`: Bu yardım mesajı\\.")
        # Yanıt gönder
        if response_message: send_telegram_message(response_message)
        elif not command_processed: print(f"Bilinmeyen komut/metin: {text}")
        processing_time = time.time() - webhook_start_time
        print(f"<<< /telegram endpoint tamamlandı ({processing_time:.3f} saniye)")
        return "ok", 200
    except Exception as e:
        print(f"❌ /telegram endpoint hatası: {e}"); print(traceback.format_exc())
        try:
             if 'chat_id' in locals() and str(chat_id) == CHAT_ID: send_telegram_message("🤖 Kritik hata oluştu\\!")
        except Exception as inner_e: print(f"❌ Hata mesajı gönderilemedi: {inner_e}")
        return "Internal Server Error", 500

@app.route("/clear_signals_endpoint", methods=["POST"])
def clear_signals_endpoint():
    """Manuel temizlik için endpoint."""
    # GÜVENLİK KONTROLÜ EKLE!
    print(">>> /clear_signals_endpoint tetiklendi")
    if clear_signals(): send_telegram_message("🧹 Manuel temizlik yapıldı\\."); return "OK", 200
    else: send_telegram_message("❌ Manuel temizlik hatası\\!"); return "Hata", 500

# --- Uygulama Başlangıcı ---
if __name__ == "__main__":
    print("*"*50 + "\n🚀 Flask Sinyal/Analiz Botu Başlatılıyor...\n" + "*"*50)
    if not BOT_TOKEN or not CHAT_ID: print("❌ BOT_TOKEN veya CHAT_ID eksik!"); exit()
    print(f"🔧 Ayarlar: TZ='{TIMEZONE}', Cleanup='{os.getenv('CLEANUP_HOUR', 0)}:{os.getenv('CLEANUP_MINUTE', 5)}'")
    print(f"📂 Dosyalar: Sinyal='{SIGNALS_FILE}', Analiz='{ANALIZ_FILE}', BIST='{ANALIZ_SONUCLARI_FILE}'")
    for fp in [SIGNALS_FILE, ANALIZ_FILE, ANALIZ_SONUCLARI_FILE]:
        if fp and not os.path.exists(fp): print(f"ℹ️ {fp} oluşturuluyor..."); save_json_file(fp, {})
        elif fp and os.path.exists(fp) and os.path.getsize(fp) == 0: print(f"ℹ️ {fp} boş, {{}} yazılıyor."); save_json_file(fp, {})
    print("\n--- Veri Yükleme ---"); load_signals(); load_analiz_data(); load_bist_analiz_data(); print("--- Yükleme Tamamlandı ---\n")
    try:
        threading.Thread(target=clear_signals_daily, name="DailyCleanup", daemon=True).start()
        print("✅ Günlük temizlik görevi başlatıldı.")
    except Exception as thread_err: print(f"❌ Temizlik thread hatası: {thread_err}")
    port = int(os.getenv("PORT", 5000)); debug = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t"); host = "0.0.0.0"
    print(f"\n🌍 Sunucu: http://{host}:{port} (Debug: {debug})"); print("🚦 Bot hazır.")
    if debug: print("⚠️ DİKKAT: Debug modu aktif!")
    app.run(host=host, port=port, debug=debug)
