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
import math # Analiz sıralaması için

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# --- Global Değişkenler ve Ayarlar ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json") # NASDAQ
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json") # BIST
try:
    TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Istanbul"))
except pytz.exceptions.UnknownTimeZoneError:
    print(f"❌ Uyarı: .env TIMEZONE '{os.getenv('TIMEZONE')}' geçersiz. 'Europe/Istanbul' kullanılacak.")
    TIMEZONE = pytz.timezone("Europe/Istanbul")

signals_data = {}
analiz_data = {}
bist_analiz_data = {}
last_signal_time = {}

signals_lock = threading.Lock()
analiz_lock = threading.Lock()
bist_analiz_lock = threading.Lock()

# --- Yardımcı Fonksiyonlar ---

def escape_markdown_v2(text):
    """Telegram MarkdownV2 için özel karakterleri kaçırır."""
    if not isinstance(text, str): text = str(text)
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    text = text.replace('\\', '\\\\')
    for char in escape_chars: text = text.replace(char, f'\\{char}')
    return text

def send_telegram_message(message):
    """Telegram'a mesaj gönderir (MarkdownV2)."""
    if not BOT_TOKEN or not CHAT_ID: print("❌ Hata: BOT_TOKEN veya CHAT_ID ayarlanmamış."); return
    escaped_message = message
    max_length = 4096
    for i in range(0, len(escaped_message), max_length):
        chunk = escaped_message[i:i+max_length]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {"chat_id": CHAT_ID, "text": chunk, "parse_mode": "MarkdownV2"}
        try:
            r = requests.post(url, json=data, timeout=30)
            r.raise_for_status(); print(f"✅ Telegram yanıtı: {r.status_code}"); time.sleep(0.5)
        except requests.exceptions.Timeout: print(f"❌ Telegram API zaman aşımına uğradı.")
        except requests.exceptions.HTTPError as http_err:
            print(f"❌ Telegram HTTP Hatası: {http_err} - Yanıt: {r.text}"); print(f"❌ Mesaj: {chunk[:100]}...")
        except requests.exceptions.RequestException as e: print(f"❌ Telegram RequestException: {e}")
        except Exception as e: print(f"❌ Telegram gönderim hatası: {e}"); print(traceback.format_exc())

def load_json_file(filepath):
    """Genel JSON dosyası yükleme fonksiyonu."""
    try:
        if not filepath: print("❌ Hata: Geçersiz dosya yolu."); return None
        if not os.path.exists(filepath): print(f"⚠️ {filepath} bulunamadı."); return {}
        if os.path.getsize(filepath) == 0: print(f"⚠️ {filepath} boş."); return {}
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
    """signals.json yükler."""
    global signals_data, last_signal_time
    print(f"🔄 Sinyal verileri: {SIGNALS_FILE}")
    with signals_lock:
        loaded_data = load_json_file(SIGNALS_FILE)
        if loaded_data is not None:
            signals_data = loaded_data; last_signal_time = {}
            for borsa, signal_list in signals_data.items():
                if signal_list:
                    try:
                        latest_signal = max(signal_list, key=lambda s: datetime.strptime(s.get('time', '1970-01-01 00:00:00 +0000')[:19], "%Y-%m-%d %H:%M:%S"))
                        last_signal_time[borsa] = latest_signal.get('time')
                    except Exception as dt_err: print(f"⚠️ {borsa} son sinyal zamanı hatası: {dt_err}")
            print(f"✅ Sinyaller yüklendi: {list(signals_data.keys())}")
        else: print("❌ Sinyal okuma hatası."); signals_data = signals_data or {}

def save_signals():
    """signals.json kaydeder."""
    print(f"💾 Sinyal verileri: {SIGNALS_FILE}")
    with signals_lock:
        if not save_json_file(SIGNALS_FILE, signals_data): print(f"❌ Sinyal kaydetme hatası: {SIGNALS_FILE}")

def load_analiz_data():
    """analiz.json (NASDAQ verileri) yükler."""
    global analiz_data
    print(f"🔄 NASDAQ Analiz verileri: {ANALIZ_FILE}")
    with analiz_lock:
        loaded_data = load_json_file(ANALIZ_FILE)
        if loaded_data is not None: analiz_data = loaded_data; print(f"✅ NASDAQ Analiz yüklendi: {len(analiz_data)} kayıt.")
        else: print("❌ NASDAQ Analiz okuma hatası."); analiz_data = analiz_data or {}

def load_bist_analiz_data():
    """analiz_sonuclari.json (BIST verileri) yükler."""
    global bist_analiz_data
    print(f"🔄 BIST Analiz verileri: {ANALIZ_SONUCLARI_FILE}")
    with bist_analiz_lock:
        loaded_data = load_json_file(ANALIZ_SONUCLARI_FILE)
        if loaded_data is not None: bist_analiz_data = loaded_data; print(f"✅ BIST Analiz yüklendi: {len(bist_analiz_data)} kayıt.")
        else: print("❌ BIST Analiz okuma hatası."); bist_analiz_data = bist_analiz_data or {}

# ----- parse_signal_line GÜNCELLENDİ -----
def parse_signal_line(alert_json_string):
    """Gelen JSON formatındaki alert mesajını ayrıştırır."""
    try:
        alert_data = json.loads(alert_json_string)
    except json.JSONDecodeError as e:
        print(f"❌ JSON Ayrıştırma Hatası: {e} - Gelen Veri: {alert_json_string[:200]}...")
        return None

    # Temel verileri al
    symbol = alert_data.get("symbol", "N/A").upper()
    exchange_raw = alert_data.get("exchange", "UNKNOWN").lower()
    signal_text = alert_data.get("signal", "")

    # Borsa adını standartlaştır
    borsa_map = {"bist": "bist", "xu100": "bist",
                 "nasdaq": "nasdaq", "ndx": "nasdaq",
                 "binance": "binance", "crypto": "binance",
                 "bats": "bats", "us": "bats"}
    borsa = borsa_map.get(exchange_raw, exchange_raw if exchange_raw != "unknown" else "unknown")

    if borsa == "unknown" or symbol == "N/A":
        print(f"❌ Geçersiz Borsa veya Sembol: {alert_data}")
        return None

    # Sonuç sözlüğünü hazırla
    data = {
        "raw": alert_json_string, # Orijinal JSON string'i
        "symbol": symbol,
        "borsa": borsa,
        "time": datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z"),
        "type": "INFO", # Varsayılan
        "source": "TradingView Signal", # Kaynak belli
        "kairi_value": None,
        "matisay_value": None,
        "alis_sinyali_flag": False,      # Güçlü eşleşen için (Mükemmel Alış ile tetiklenecek varsayımı)
        "mukemmel_alis_flag": False,
        "alis_sayimi_tamam_flag": False,
        "mukemmel_satis_flag": False,
        "satis_sayimi_tamam_flag": False
    }

    # Signal metnini analiz et
    signal_lower = signal_text.lower()

    # 1. KAIRI Değeri
    try:
        kairi_match = re.search(r"kairi\s+([-\d\.]+)", signal_lower)
        if kairi_match:
            data["kairi_value"] = float(kairi_match.group(1))
    except (ValueError, TypeError):
        print(f"⚠️ KAIRI değeri float'a çevrilemedi: {signal_text}")

    # 2. Matisay Değeri
    try:
        matisay_match = re.search(r"matisay\s+([-\d\.]+)", signal_lower)
        if matisay_match:
            data["matisay_value"] = float(matisay_match.group(1))
    except (ValueError, TypeError):
        print(f"⚠️ Matisay değeri float'a çevrilemedi: {signal_text}")

    # 3. Flag'ler ve Sinyal Tipi
    if "alış sayımı tamamlandı" in signal_lower:
        data["alis_sayimi_tamam_flag"] = True
        data["type"] = "BUY" # veya INFO kalabilir, isteğe bağlı
    elif "satış sayımı tamamlandı" in signal_lower:
        data["satis_sayimi_tamam_flag"] = True
        data["type"] = "SELL" # veya INFO kalabilir
    elif "mükemmel alış kurulumu tamamlandı" in signal_lower:
        data["mukemmel_alis_flag"] = True
        data["alis_sinyali_flag"] = True # Güçlü eşleşen varsayımı
        data["type"] = "BUY"
    elif "mükemmel satış kurulumu tamamlandı" in signal_lower:
        data["mukemmel_satis_flag"] = True
        data["type"] = "SELL"

    # Gerekirse diğer signal metinleri için ek elif blokları eklenebilir

    print(f"ℹ️ Ayrıştırılan Sinyal: {data}")
    return data


def clear_signals():
    """Verileri temizler."""
    global signals_data, analiz_data, bist_analiz_data, last_signal_time
    print("🧹 Tüm veriler temizleniyor...")
    success = True
    with signals_lock: signals_data, last_signal_time = {}, {}; success &= save_json_file(SIGNALS_FILE, {})
    with analiz_lock: analiz_data = {}; success &= (not os.path.exists(ANALIZ_FILE) or save_json_file(ANALIZ_FILE, {}))
    with bist_analiz_lock: bist_analiz_data = {}; success &= (not os.path.exists(ANALIZ_SONUCLARI_FILE) or save_json_file(ANALIZ_SONUCLARI_FILE, {}))
    print("✅ Temizlik sonucu:", "Başarılı" if success else "Hatalı")
    return success

# --- Çekirdek Fonksiyonlar ---

def generate_summary(target_borsa=None):
    """İstenen formata göre sinyal özeti oluşturur."""
    with signals_lock:
        relevant_signals = []
        if target_borsa:
            target_borsa_lower = target_borsa.lower()
            if target_borsa_lower in ["bist_dly", "bist"]: relevant_signals.extend(signals_data.get("bist", []))
            elif target_borsa_lower in signals_data: relevant_signals = signals_data.get(target_borsa_lower, [])
        else:
            for signal_list in signals_data.values(): relevant_signals.extend(signal_list)
        if not relevant_signals: return f"ℹ️ `{escape_markdown_v2(target_borsa.upper() if target_borsa else 'Tüm Borsalar')}` için sinyal yok\\."
        guclu_eslesen, kairi_neg30, kairi_neg20, matisay_neg25, mukemmel_alis, alis_sayim, mukemmel_satis, satis_sayim = [],[],[],[],[],[],[],[]
        for signal in relevant_signals:
            symbol, borsa = signal.get("symbol", "N/A"), signal.get("borsa", "?").upper()
            kairi_val, matisay_val = signal.get("kairi_value"), signal.get("matisay_value")
            alis_sinyali, muk_alis, alis_say, muk_satis, satis_say = signal.get("alis_sinyali_flag", False), signal.get("mukemmel_alis_flag", False), signal.get("alis_sayimi_tamam_flag", False), signal.get("mukemmel_satis_flag", False), signal.get("satis_sayimi_tamam_flag", False)
            kairi_num, matisay_num = None, None
            if kairi_val is not None:
                try: kairi_num = float(kairi_val)
                except (ValueError, TypeError): pass
            if matisay_val is not None:
                try: matisay_num = float(matisay_val)
                except (ValueError, TypeError): pass
            esc_sym, esc_borsa = escape_markdown_v2(symbol), escape_markdown_v2(borsa)
            if alis_sinyali and kairi_num is not None: guclu_eslesen.append(f"✅ `{esc_sym}` \\({esc_borsa}\\) \\- KAIRI: {escape_markdown_v2(f'{kairi_num:.2f}')} & Alış Sinyali")
            if kairi_num is not None:
                 esc_kairi = escape_markdown_v2(f"{kairi_num:.2f}")
                 if kairi_num <= -30: kairi_neg30.append(f"`{esc_sym}` \\({esc_borsa}\\): KAIRI {esc_kairi}")
                 elif kairi_num <= -20: kairi_neg20.append(f"`{esc_sym}` \\({esc_borsa}\\): KAIRI {esc_kairi}")
            if matisay_num is not None and matisay_num < -25: matisay_neg25.append(f"`{esc_sym}` \\({esc_borsa}\\): Matisay {escape_markdown_v2(f'{matisay_num:.2f}')}")
            if muk_alis: mukemmel_alis.append(f"`{esc_sym}` \\({esc_borsa}\\)")
            if alis_say: alis_sayim.append(f"`{esc_sym}` \\({esc_borsa}\\)")
            if muk_satis: mukemmel_satis.append(f"`{esc_sym}` \\({esc_borsa}\\)")
            if satis_say: satis_sayim.append(f"`{esc_sym}` \\({esc_borsa}\\)")
        response_parts = []
        def add_section(title, items):
            if items: response_parts.append(f"{title}\n" + "\n".join(sorted(items)))
        add_section("*📊 GÜÇLÜ EŞLEŞEN SİNYALLER:*", guclu_eslesen)
        add_section("*🔴 KAIRI ≤ \\-30:*", kairi_neg30)
        add_section("*🟠 KAIRI ≤ \\-20 \\(ama > \\-30\\):*", kairi_neg20)
        add_section("*🟣 Matisay < \\-25:*", matisay_neg25)
        add_section("*🟢 Mükemmel Alış:*", mukemmel_alis)
        add_section("*📈 Alış Sayımı Tamamlananlar:*", alis_sayim)
        add_section("*🔵 Mükemmel Satış:*", mukemmel_satis)
        add_section("*📉 Satış Sayımı Tamamlananlar:*", satis_sayim)
        if not response_parts: return f"ℹ️ `{escape_markdown_v2(target_borsa.upper() if target_borsa else 'Tüm Borsalar')}` için özel sinyal yok\\."
        return "\n\n".join(response_parts)

def generate_analiz_response(tickers):
    """analiz.json'dan (NASDAQ) veri çeker, formatlar ve sıralar."""
    with analiz_lock:
        if not analiz_data: return f"⚠️ NASDAQ Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_FILE))}`) yüklenemedi\\."
        results, not_found = [], []
        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper(); data = analiz_data.get(ticker)
            if data:
                try: puan_val = float(data.get("puan", -math.inf))
                except (ValueError, TypeError): puan_val = -math.inf
                results.append({"ticker": ticker, "puan": puan_val, "data": data})
            else: not_found.append(ticker)
        results.sort(key=lambda x: x["puan"], reverse=True)
        response_lines = []
        for result in results:
            data, ticker = result["data"], result["ticker"]
            symbol, puan_str = escape_markdown_v2(ticker), escape_markdown_v2(data.get("puan", "N/A"))
            yorum = escape_markdown_v2(data.get("yorum", "_Yorum yok_"))
            detaylar_list = data.get("detaylar", [])
            formatted_detaylar = "\n".join([escape_markdown_v2(d) for d in detaylar_list]) if detaylar_list else "_Detay yok\\._"
            response_lines.append(f"📊 *{symbol}* Analiz Sonuçları \\(Puan: {puan_str}\\):\n{formatted_detaylar}\n\n{yorum}")
        for nf_ticker in not_found: response_lines.append(f"❌ `{escape_markdown_v2(nf_ticker)}` analizi bulunamadı\\.")
        separator = "\n\n---\n\n"; return separator.join(response_lines)

def generate_bist_analiz_response(tickers):
    """analiz_sonuclari.json'dan (BIST) veri çeker, formatlar."""
    with bist_analiz_lock:
        if not bist_analiz_data: return f"⚠️ Detaylı BIST Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_SONUCLARI_FILE))}`) yüklenemedi\\."
        response_lines = []
        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper(); data = bist_analiz_data.get(ticker)
            if data:
                symbol, score_str = escape_markdown_v2(ticker), escape_markdown_v2(data.get("score", "N/A"))
                classification = escape_markdown_v2(data.get("classification", "_Belirtilmemiş_"))
                comments = data.get("comments", [])
                formatted_comments = "\n".join([f"\\- {escape_markdown_v2(c)}" for c in comments if isinstance(c, str)]) if comments else "_Yorum yok\\._"
                response_lines.append(f"📊 *{symbol}* Detaylı Analiz:\n\n📈 *Puan:* {score_str}\n🏅 *Sınıflandırma:* {classification}\n\n📝 *Öne Çıkanlar:*\n{formatted_comments}")
            else: response_lines.append(f"❌ `{escape_markdown_v2(ticker)}` için detaylı BIST analizi bulunamadı\\.")
        separator = "\n\n---\n\n"; return separator.join(response_lines)

# --- Flask Endpointleri ---
@app.route("/", methods=["GET"])
def home():
    signal_counts = {b: len(s) for b, s in signals_data.items()}
    return f"Bot Aktif! Sinyaller: {escape_markdown_v2(str(signal_counts))}", 200

@app.route("/signal", methods=["POST"])
def receive_signal():
    signal_text = request.data.decode("utf-8") # Gelen veri JSON string
    print(f"--- Gelen Sinyal Raw ---\n{signal_text}\n------------------------")
    if not signal_text.strip(): print("⚠️ Boş sinyal verisi."); return "Boş veri", 400

    # Sinyali ayrıştır (JSON formatı için güncellendi)
    parsed_data = parse_signal_line(signal_text)

    if parsed_data:
        borsa = parsed_data["borsa"].lower()
        symbol = parsed_data["symbol"]
        timestamp = parsed_data["time"] # parse_signal_line zamanı kendi ekliyor

        # Belleği ve dosyayı güncelle
        with signals_lock:
            signals_data.setdefault(borsa, []).append(parsed_data)
            last_signal_time[borsa] = timestamp
        save_signals() # Her başarılı sinyal sonrası kaydet

        # Telegram'a bildirim gönder (İsteğe bağlı - formatı değiştirebilirsiniz)
        signal_type = parsed_data.get("type", "INFO")
        source = parsed_data.get("source", "TradingView") # Kaynak artık biliniyor
        icon = "🟢" if signal_type == "BUY" else ("🔴" if signal_type == "SELL" else "ℹ️")
        message_detail = (
            f"{icon} *{escape_markdown_v2(borsa.upper())}* \\- `{escape_markdown_v2(symbol)}` "
            f"*{escape_markdown_v2(signal_type)}* "
            # KAIRI/Matisay veya flag bilgisini de ekleyebilirsiniz:
            f"_(Detay: {escape_markdown_v2(parsed_data.get('signal', 'N/A'))})_ "
            f"\\({escape_markdown_v2(timestamp)}\\)"
        )
        # Tek sinyal geldiği için direkt gönderilebilir veya biriktirilebilir
        send_telegram_message("🚨 *Yeni Sinyal Alındı:*\n" + message_detail)

        print(f"✅ Sinyal işlendi ve kaydedildi: {parsed_data}")
        return f"Sinyal işlendi: {symbol}", 200
    else:
        print(f"⚠️ Sinyal ayrıştırılamadı veya geçersiz: {signal_text}")
        send_telegram_message(f"⚠️ Geçersiz formatta sinyal alındı:\n```\n{escape_markdown_v2(signal_text)}\n```")
        return "Sinyal ayrıştırılamadı veya geçersiz.", 400

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    webhook_start_time = time.time()
    try:
        update = request.json
        if not update: print("Boş JSON."); return "ok", 200
        message = update.get("message") or update.get("edited_message")
        if not message: update_type = next((k for k in update if k != 'update_id'), '?'); print(f"Desteklenmeyen '{update_type}'."); return "ok", 200
        text, chat_info, user_info = message.get("text", "").strip(), message.get("chat"), message.get("from")
        if not chat_info or not user_info: print("❌ Sohbet/kullanıcı eksik."); return "ok", 200
        chat_id, user_id, first_name, username = chat_info.get("id"), user_info.get("id"), user_info.get("first_name", ""), user_info.get("username", "N/A")
        if str(chat_id) != CHAT_ID: print(f"⚠️ Yetkisiz sohbet ID: {chat_id}"); return "ok", 200
        if not text: print("Boş mesaj."); return "ok", 200
        print(f">>> Mesaj (Chat:{chat_id}, User:{first_name}[{username}/{user_id}]): {text}")
        response_message, command_processed = None, False
        # Komut İşleme
        if text.lower().startswith("/ozet"):
            command_processed = True; print(">>> /ozet komutu...")
            parts = text.split(maxsplit=1); keyword = parts[1].lower() if len(parts) > 1 else None
            if keyword == "bist_dly": keyword = "bist"
            allowed = ["bist", "nasdaq", "bats", "binance"]
            if keyword and keyword not in allowed: response_message = f"⚠️ Geçersiz borsa: `{escape_markdown_v2(keyword)}`\\. İzin verilenler: {', '.join(f'`{k}`' for k in allowed)}\\."
            else: response_message = generate_summary(keyword)
        elif text.lower().startswith("/analiz"):
            command_processed = True; print(">>> /analiz komutu...")
            tickers_input = text[len("/analiz"):].strip()
            if not tickers_input: response_message = "Lütfen NASDAQ hisse kodu belirtin\\. Örn: `/analiz AAPL`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers: response_message = "Geçerli hisse kodu yok\\. Örn: `/analiz AAPL`"
                else: print(f"Analiz: {tickers}"); response_message = generate_analiz_response(tickers)
        elif text.lower().startswith("/bist_analiz"):
            command_processed = True; print(">>> /bist_analiz komutu...")
            tickers_input = text[len("/bist_analiz"):].strip()
            if not tickers_input: response_message = "Lütfen BIST kodu belirtin\\. Örn: `/bist_analiz EREGL`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers: response_message = "Geçerli BIST kodu yok\\. Örn: `/bist_analiz EREGL`"
                else: print(f"BIST Analiz: {tickers}"); response_message = generate_bist_analiz_response(tickers)
        elif text.lower().startswith("/clear_signals"):
             command_processed = True; print(">>> /clear_signals komutu...")
             if clear_signals(): response_message = "✅ Veriler temizlendi\\."
             else: response_message = "❌ Temizleme hatası\\."
        elif text.lower().startswith("/start") or text.lower().startswith("/help"):
            command_processed = True; print(">>> /start veya /help komutu...")
            response_message = ("👋 *Merhaba\\!* Komutlar:\n\n"
                                "• `/ozet`: Tüm özet\\.\n"
                                "• `/ozet [borsa]`: Belirli borsa \\(`bist`, `nasdaq`\\.\\.\\)\\.\n"
                                "• `/analiz [HİSSE,\\.\\.]`: NASDAQ analizi \\(Örn: `/analiz AAPL`\\)\\.\n"
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
    print(f"🔧 Ayarlar: TZ='{TIMEZONE}'")
    print(f"📂 Dosyalar: Sinyal='{SIGNALS_FILE}', NASDAQ Analiz='{ANALIZ_FILE}', BIST Analiz='{ANALIZ_SONUCLARI_FILE}'")
    for fp in [SIGNALS_FILE, ANALIZ_FILE, ANALIZ_SONUCLARI_FILE]:
        if fp and not os.path.exists(fp): print(f"ℹ️ {fp} oluşturuluyor..."); save_json_file(fp, {})
        elif fp and os.path.exists(fp) and os.path.getsize(fp) == 0: print(f"ℹ️ {fp} boş, {{}} yazılıyor."); save_json_file(fp, {})
    print("\n--- Veri Yükleme ---"); load_signals(); load_analiz_data(); load_bist_analiz_data(); print("--- Yükleme Tamamlandı ---\n")
    # Arka plan temizlik thread başlatma kodu kaldırıldı.
    port = int(os.getenv("PORT", 5000)); debug = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t"); host = "0.0.0.0"
    print(f"\n🌍 Sunucu: http://{host}:{port} (Debug: {debug})"); print("🚦 Bot hazır.")
    if debug: print("⚠️ DİKKAT: Debug modu aktif!")
    app.run(host=host, port=port, debug=debug)
