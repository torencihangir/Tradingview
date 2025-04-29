# -*- coding: utf-8 -*-
from flask import Flask, request
import json
import requests
import os
import time
import re
import threading
from datetime import datetime, timedelta
import pytz
from dotenv import load_dotenv
import traceback # Hata ayıklama için eklendi

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# --- Global Değişkenler ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json")
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")
TIMEZONE = pytz.timezone("Europe/Istanbul") # Zaman dilimini ayarla

# Sinyalleri ve analizleri saklamak için (bellekte)
# Daha büyük uygulamalar için veritabanı veya daha sağlam bir depolama düşünülmeli
signals_data = {}
analiz_data = {}
bist_analiz_data = {}
last_signal_time = {} # Her borsa için son sinyal zamanını tutar

# Kilitler (Eşzamanlılık yönetimi için)
signals_lock = threading.Lock()
analiz_lock = threading.Lock()
bist_analiz_lock = threading.Lock()

# --- Yardımcı Fonksiyonlar ---

def escape_markdown_v2(text):
    """
    Telegram MarkdownV2 için özel karakterleri kaçırır.
    """
    if not isinstance(text, str): # Gelen verinin string olduğundan emin ol
        text = str(text)
    # Önce ters eğik çizgiyi kaçır, sonra diğerlerini
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    text = text.replace('\\', '\\\\') # Ters eğik çizgiyi kaçır
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

def send_telegram_message(message):
    """Telegram'a mesaj gönderir, MarkdownV2 kaçırma işlemi yapar ve uzun mesajları böler."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Hata: BOT_TOKEN veya CHAT_ID ayarlanmamış. Mesaj gönderilemiyor.")
        return

    # Markdown'dan kaçırılacak metinler için güvenli hale getirme
    # Not: Tüm mesajı kaçırmak yerine, sadece değişken kısımları kaçırmak daha iyi olabilir.
    # Ancak şimdilik tüm mesajı kaçıralım.
    escaped_message = escape_markdown_v2(message)
    max_length = 4096

    # Mesajı 4096 karakterlik parçalara böl
    for i in range(0, len(escaped_message), max_length):
        chunk = escaped_message[i:i+max_length]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        try:
            # Timeout süresini artırabilir veya yeniden deneme mekanizması ekleyebilirsiniz
            r = requests.post(url, json=data, timeout=30)
            r.raise_for_status() # HTTP hataları için exception fırlatır
            print(f"✅ Telegram yanıtı: {r.status_code}")
            # Başarılı gönderimler arasında kısa bir bekleme eklemek API limitlerini aşmayı önleyebilir
            time.sleep(0.5)
        except requests.exceptions.Timeout:
            print(f"❌ Telegram API zaman aşımına uğradı.")
        except requests.exceptions.HTTPError as http_err:
            print(f"❌ Telegram HTTP Hatası: {http_err} - Yanıt: {r.text}")
            # Yanıt metnini de loglamak hata ayıklamada yardımcı olabilir
            print(f"❌ Gönderilemeyen mesaj parçası (escaped): {chunk[:100]}...") # İlk 100 karakter
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi (RequestException): {e}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")
            print(traceback.format_exc()) # Detaylı hata izi

def load_json_file(filepath):
    """Genel JSON dosyası yükleme fonksiyonu."""
    try:
        # Dosya yolu boş veya None ise hata ver
        if not filepath:
            print(f"❌ Hata: Geçersiz dosya yolu: {filepath}")
            return None

        # Dosya yoksa uyarı ver ve boş dict dön
        if not os.path.exists(filepath):
             print(f"⚠️ Uyarı: {filepath} dosyası bulunamadı. Boş veri döndürülüyor.")
             return {} # Boş dict döndürmek genellikle daha güvenlidir

        # Dosya boşsa uyarı ver ve boş dict dön
        if os.path.getsize(filepath) == 0:
            print(f"⚠️ Uyarı: {filepath} dosyası boş.")
            return {}

        with open(filepath, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        # Bu durum yukarıda handle edildi ama yine de burada kalabilir
        print(f"⚠️ Uyarı: {filepath} dosyası bulunamadı.")
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ Hata: {filepath} dosyası geçerli bir JSON formatında değil. Hata: {e}")
        # Hatalı dosyanın içeriğini loglamak yardımcı olabilir
        try:
             with open(filepath, "r", encoding="utf-8") as f_err:
                 print(f"Dosyanın başı: {f_err.read(200)}...") # İlk 200 karakter
        except Exception as read_err:
            print(f"❌ Hata dosyasını okuma hatası: {read_err}")
        return {} # Hatalı durumda da boş dict dön
    except IOError as e:
        print(f"❌ G/Ç Hatası ({filepath} okuma): {e}")
        return {}
    except Exception as e:
        print(f"❌ Beklenmedik Hata ({filepath} okuma): {e}")
        print(traceback.format_exc()) # Detaylı hata izi
        return {}

def save_json_file(filepath, data):
    """Genel JSON dosyası kaydetme fonksiyonu."""
    try:
        # Dosya yolu boş veya None ise hata ver
        if not filepath:
            print(f"❌ Hata: Geçersiz dosya yolu: {filepath}")
            return False
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        return True
    except IOError as e:
        print(f"❌ G/Ç Hatası ({filepath} yazma): {e}")
        return False
    except TypeError as e:
        print(f"❌ Tip Hatası (JSON serileştirme): {e}. Veri: {str(data)[:200]}...") # Verinin başını logla
        return False
    except Exception as e:
        print(f"❌ Beklenmedik Hata ({filepath} yazma): {e}")
        print(traceback.format_exc()) # Detaylı hata izi
        return False

def load_signals():
    """signals.json dosyasını güvenli bir şekilde yükler."""
    global signals_data
    with signals_lock:
        loaded_data = load_json_file(SIGNALS_FILE)
        if loaded_data is not None: # Sadece başarılı yüklemede güncelle
             signals_data = loaded_data
        else:
             print("❌ Sinyal dosyası yüklenemedi, mevcut bellek verisi korunuyor (varsa).")
             signals_data = signals_data or {} # Eğer hiç yüklenmediyse boş dict yap

def save_signals():
    """Bellekteki sinyalleri signals.json dosyasına kaydeder."""
    with signals_lock:
        if not save_json_file(SIGNALS_FILE, signals_data):
            print("❌ Sinyal verileri dosyaya kaydedilemedi.")

def load_analiz_data():
    """analiz.json dosyasını yükler."""
    global analiz_data
    with analiz_lock:
        loaded_data = load_json_file(ANALIZ_FILE)
        if loaded_data is not None:
            analiz_data = loaded_data
        else:
            print("❌ Analiz dosyası yüklenemedi, mevcut bellek verisi korunuyor (varsa).")
            analiz_data = analiz_data or {}

def load_bist_analiz_data():
    """analiz_sonuclari.json dosyasını yükler."""
    global bist_analiz_data
    with bist_analiz_lock:
        loaded_data = load_json_file(ANALIZ_SONUCLARI_FILE)
        if loaded_data is not None:
            bist_analiz_data = loaded_data
        else:
            print("❌ BIST Analiz dosyası yüklenemedi, mevcut bellek verisi korunuyor (varsa).")
            bist_analiz_data = bist_analiz_data or {}

# Başlangıçta verileri yükle
load_signals()
load_analiz_data()
load_bist_analiz_data()

def parse_signal_line(line):
    """TradingView alert mesajını ayrıştırır."""
    # Örnek Formatlar (Esnek olmalı):
    # 1. BIST: MIATK AL Strategy: SuperTrend Time: 2023-10-27T10:30:00Z
    # 2. NASDAQ: AAPL SAT Kaynak: RSI Divergence
    # 3. BINANCE: BTCUSDT LONG Price: 40000 Time: 1678886400
    # 4. BATS: SPY ALIM Nedeni: Destek Kırılımı

    line = line.strip()
    if not line:
        return None

    data = {"raw": line} # Orijinal mesajı da saklayalım

    # 1. Borsa Adını Bulma (İlk kelime genellikle)
    borsa_match = re.match(r"^(\w+):", line, re.IGNORECASE)
    if borsa_match:
        borsa_raw = borsa_match.group(1).lower()
        # Borsa isimlerini standartlaştır
        if borsa_raw in ["bist", "xu100"]: data["borsa"] = "bist"
        elif borsa_raw in ["nasdaq", "ndx"]: data["borsa"] = "nasdaq"
        elif borsa_raw in ["binance", "crypto"]: data["borsa"] = "binance"
        elif borsa_raw in ["bats", "us"]: data["borsa"] = "bats"
        # Diğer bilinen borsa/piyasa adları eklenebilir
        else: data["borsa"] = borsa_raw # Bilinmiyorsa olduğu gibi al
        line = line[len(borsa_match.group(0)):].strip() # Borsa kısmını kaldır
    else:
        # Borsa adı bulunamazsa, içeriğe göre tahmin etmeye çalış veya 'unknown' de
        # (Bu kısım daha karmaşık hale getirilebilir)
        data["borsa"] = "unknown"
        print(f"⚠️ Sinyal satırında borsa adı bulunamadı: {data['raw']}")

    # 2. Sembolü Bulma (Genellikle borsadan sonraki ilk büyük harf grubu)
    # \b kelime sınırı demek, $ gibi özel karakterleri hisse kodundan ayırır
    symbol_match = re.search(r"\b([A-Z0-9\.]+)\b", line) # AAPL, MIATK, BTCUSDT, TUPRS.IS gibi
    if symbol_match:
        data["symbol"] = symbol_match.group(1).upper()
        # Opsiyonel: Sembol sonrası metni de ayıklayabiliriz
        # line = line[symbol_match.end():].strip()
    else:
        data["symbol"] = "N/A"
        print(f"⚠️ Sinyal satırında sembol bulunamadı: {data['raw']}")


    # 3. Sinyal Tipini Bulma (AL, SAT, LONG, SHORT, BUY, SELL vb.)
    # Kelime sınırları (\b) ile tam eşleşme ara
    signal_type_match = re.search(r"\b(AL|ALIM|BUY|LONG)\b", line, re.IGNORECASE)
    if signal_type_match:
        data["type"] = "BUY"
    else:
        signal_type_match = re.search(r"\b(SAT|SATIM|SELL|SHORT)\b", line, re.IGNORECASE)
        if signal_type_match:
            data["type"] = "SELL"
        else:
            data["type"] = "INFO" # Yön belirtmiyorsa INFO olabilir

    # 4. Zaman Bilgisini Bulma (Opsiyonel)
    # ISO 8601 formatı (TradingView sık kullanır) veya Unix timestamp
    time_match_iso = re.search(r"Time: (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", line, re.IGNORECASE)
    time_match_unix = re.search(r"Time: (\d{10,})", line, re.IGNORECASE) # Unix timestamp
    if time_match_iso:
        try:
            # UTC zamanını alıp yerel saate çevirelim
            utc_time = datetime.strptime(time_match_iso.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            local_time = utc_time.astimezone(TIMEZONE)
            data["time"] = local_time.strftime("%Y-%m-%d %H:%M:%S %Z%z")
        except ValueError:
            print(f"⚠️ Geçersiz ISO zaman formatı: {time_match_iso.group(1)} in {data['raw']}")
            data["time"] = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z") # Hata durumunda şimdiki zaman
    elif time_match_unix:
         try:
            utc_time = datetime.fromtimestamp(int(time_match_unix.group(1)), tz=pytz.utc)
            local_time = utc_time.astimezone(TIMEZONE)
            data["time"] = local_time.strftime("%Y-%m-%d %H:%M:%S %Z%z")
         except ValueError:
            print(f"⚠️ Geçersiz Unix timestamp: {time_match_unix.group(1)} in {data['raw']}")
            data["time"] = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z") # Hata durumunda şimdiki zaman
    else:
        data["time"] = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z") # Zaman yoksa şimdiki zaman

    # 5. Kaynak/Strateji Bilgisini Bulma (Opsiyonel)
    source_match = re.search(r"(?:Strategy|Kaynak|Nedeni|Indicator): (.+)", line, re.IGNORECASE)
    if source_match:
        data["source"] = source_match.group(1).strip()
    else:
        # Zaman, sinyal tipi, sembol gibi bilinen kısımları çıkarıp kalan metni kaynak olarak almayı deneyebiliriz
        # Bu kısım daha karmaşık ve hataya açık olabilir
        remaining_text = line
        if data.get("symbol") != "N/A": remaining_text = remaining_text.replace(data["symbol"], "")
        if signal_type_match: remaining_text = remaining_text.replace(signal_type_match.group(0), "")
        if time_match_iso: remaining_text = remaining_text.replace(time_match_iso.group(0), "")
        if time_match_unix: remaining_text = remaining_text.replace(time_match_unix.group(0), "")
        # ':' gibi ayırıcıları ve boşlukları temizle
        remaining_text = re.sub(r'\b(Time|Strategy|Kaynak|Nedeni|Indicator):\s*', '', remaining_text, flags=re.IGNORECASE).strip()
        remaining_text = remaining_text.strip(': ')
        if remaining_text and len(remaining_text) > 2: # Çok kısa kalıntıları alma
             data["source"] = remaining_text
        else:
             data["source"] = "Belirtilmemiş"

    # Eksik zorunlu alanlar varsa None dön (veya logla)
    if not data.get("borsa") or not data.get("symbol") or data["symbol"] == "N/A":
        print(f"❌ Ayrıştırma başarısız, zorunlu alan eksik: {data}")
        return None

    return data

def clear_signals():
    """Bellekteki ve dosyalarındaki tüm sinyal ve analiz verilerini temizler."""
    global signals_data, analiz_data, bist_analiz_data, last_signal_time
    print("🧹 Sinyal ve analiz verileri temizleniyor...")
    with signals_lock:
        signals_data = {}
        last_signal_time = {}
        if not save_json_file(SIGNALS_FILE, {}):
            print(f"❌ {SIGNALS_FILE} dosyası temizlenirken hata oluştu.")
        else:
            print(f"✅ {SIGNALS_FILE} başarıyla temizlendi.")
    with analiz_lock:
        analiz_data = {}
        if os.path.exists(ANALIZ_FILE): # Sadece varsa silmeyi dene
            if not save_json_file(ANALIZ_FILE, {}):
                print(f"❌ {ANALIZ_FILE} dosyası temizlenirken hata oluştu.")
            else:
                print(f"✅ {ANALIZ_FILE} başarıyla temizlendi.")
    with bist_analiz_lock:
        bist_analiz_data = {}
        if os.path.exists(ANALIZ_SONUCLARI_FILE): # Sadece varsa silmeyi dene
            if not save_json_file(ANALIZ_SONUCLARI_FILE, {}):
                print(f"❌ {ANALIZ_SONUCLARI_FILE} dosyası temizlenirken hata oluştu.")
            else:
                print(f"✅ {ANALIZ_SONUCLARI_FILE} başarıyla temizlendi.")
    print("✅ Tüm veriler başarıyla temizlendi.")
    return True

def clear_signals_daily():
    """Her gece yarısı sinyalleri temizlemek için zamanlanmış görev."""
    while True:
        now = datetime.now(TIMEZONE)
        # Gece yarısını hedefle (örneğin 00:01)
        next_run_time = (now + timedelta(days=1)).replace(hour=0, minute=1, second=0, microsecond=0)
        wait_seconds = (next_run_time - now).total_seconds()

        print(f"🌙 Sonraki günlük temizlik: {next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')} ({wait_seconds:.0f} saniye sonra)")
        time.sleep(wait_seconds)

        print(f"⏰ {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')} - Günlük temizlik başlıyor...")
        if clear_signals():
            # Temizlik sonrası bilgi mesajı gönderilebilir
            send_telegram_message("🧹 Günlük sinyal ve analiz verileri temizlendi.")
        else:
            send_telegram_message("❌ Günlük temizlik sırasında bir hata oluştu!")
        print("✅ Günlük temizlik tamamlandı.")
        # Bir sonraki döngü için kısa bir bekleme ekleyelim
        time.sleep(60)


# --- Özet ve Analiz Fonksiyonları ---

def generate_summary(target_borsa=None):
    """
    Bellekteki sinyalleri kullanarak özet oluşturur.
    target_borsa belirtilirse sadece o borsayı özetler.
    """
    with signals_lock:
        if not signals_data:
            return "ℹ️ Henüz kayıtlı sinyal bulunmamaktadır."

        summary_lines = []
        borsa_list = sorted(signals_data.keys()) # Alfabetik sırala

        active_borsa_list = [] # Sinyali olan borsa listesi

        for borsa in borsa_list:
            # Eğer belirli bir borsa istenmişse ve bu o değilse atla
            if target_borsa and borsa.lower() != target_borsa.lower():
                continue

            signals = signals_data[borsa]
            if not signals: # Bu borsa için sinyal yoksa atla
                continue

            active_borsa_list.append(borsa) # Bu borsada sinyal var

            buy_signals = [s['symbol'] for s in signals if s.get('type') == 'BUY']
            sell_signals = [s['symbol'] for s in signals if s.get('type') == 'SELL']
            info_signals = [s['symbol'] for s in signals if s.get('type') == 'INFO'] # Varsa INFO sinyalleri

            # Kaçırılması gereken karakterler için sembolleri güvenli hale getir
            safe_buy_str = ", ".join([escape_markdown_v2(s) for s in buy_signals]) if buy_signals else "Yok"
            safe_sell_str = ", ".join([escape_markdown_v2(s) for s in sell_signals]) if sell_signals else "Yok"
            safe_info_str = ", ".join([escape_markdown_v2(s) for s in info_signals]) if info_signals else ""

            summary_lines.append(f"*{escape_markdown_v2(borsa.upper())}*") # Borsa adını kalın yap
            summary_lines.append(f"🟢 AL: {safe_buy_str}")
            summary_lines.append(f"🔴 SAT: {safe_sell_str}")
            if safe_info_str: # Sadece varsa INFO satırını ekle
                summary_lines.append(f"ℹ️ INFO: {safe_info_str}")
            summary_lines.append("") # Borsalar arasına boşluk ekle

        if not active_borsa_list:
            if target_borsa:
                return f"ℹ️ `{escape_markdown_v2(target_borsa.upper())}` için kayıtlı sinyal bulunmamaktadır."
            else:
                return "ℹ️ Henüz kayıtlı sinyal bulunmamaktadır." # Bu durum aslında yukarıda yakalanmalı

        title = "📈 Sinyal Özeti"
        if target_borsa:
            title += f" \\({escape_markdown_v2(target_borsa.upper())}\\)" # Borsa adını parantez içinde ekle

        # Son sinyal zamanını ekle (varsa)
        time_info_lines = []
        if target_borsa:
             last_time = last_signal_time.get(target_borsa.lower())
             if last_time:
                  time_info_lines.append(f"⏳ Son Sinyal ({escape_markdown_v2(target_borsa.upper())}): {escape_markdown_v2(last_time)}")
        else:
             # Genel özet için en son sinyalin zamanını bul
             latest_timestamp = None
             latest_borsa = None
             for b, t_str in last_signal_time.items():
                 try:
                    # Zaman string'ini datetime objesine çevir (timezone bilgisiyle)
                    # Format: "%Y-%m-%d %H:%M:%S %Z%z"
                    t = TIMEZONE.localize(datetime.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S")) # Zaman dilimi bilgisini ekle
                    if latest_timestamp is None or t > latest_timestamp:
                        latest_timestamp = t
                        latest_borsa = b
                 except ValueError:
                     print(f"⚠️ Geçersiz zaman formatı işlenemedi: {t_str}")
                     continue # Hatalı formatı atla
             if latest_timestamp and latest_borsa:
                 time_info_lines.append(f"⏳ En Son Sinyal ({escape_markdown_v2(latest_borsa.upper())}): {escape_markdown_v2(latest_timestamp.strftime('%Y-%m-%d %H:%M:%S'))}")


        # Başlık, zaman bilgisi ve özet satırlarını birleştir
        full_summary = f"{title}\n\n"
        if time_info_lines:
            full_summary += "\n".join(time_info_lines) + "\n\n"
        full_summary += "\n".join(summary_lines)

        return full_summary.strip() # Sondaki boşlukları temizle

def generate_analiz_response(tickers):
    """
    Verilen hisse listesi için analiz.json'dan (bellekten) veri çeker ve formatlar.
    """
    with analiz_lock: # Veriye erişirken kilitle
        if not analiz_data:
             return f"⚠️ Genel Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_FILE))}`) yüklenemedi veya boş\\."

        response_lines = []

        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper() # Temizle ve büyük harfe çevir
            data = analiz_data.get(ticker)

            if data:
                # Verileri güvenli bir şekilde al, yoksa varsayılan değer ata
                symbol = escape_markdown_v2(data.get("symbol", ticker))
                score = escape_markdown_v2(data.get("score", "N/A"))
                yorum = escape_markdown_v2(data.get("yorum", "Yorum bulunamadı.")) # 'yorum' veya 'comment' olabilir

                # Mesajı oluştur
                response_lines.append(
                    f"📊 *Temel Analiz*\n\n"
                    f"🏷️ *Sembol:* {symbol}\n"
                    f"📈 *Puan:* {score}\n"
                    f"💬 *Yorum:* {yorum}"
                )
            else:
                response_lines.append(f"❌ `{escape_markdown_v2(ticker)}` için temel analiz bulunamadı\\.")

        return "\n\n---\n\n".join(response_lines) # Analizler arasına ayırıcı ekle

def generate_bist_analiz_response(tickers):
    """
    Verilen hisse listesi için analiz_sonuclari.json'dan (bellekten) veri çeker.
    'Öne Çıkanlar' listesindeki her madde için içeriğe göre farklı emoji kullanır.
    """
    with bist_analiz_lock: # Veriye erişirken kilitle
        if not bist_analiz_data:
             return f"⚠️ Detaylı BIST Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_SONUCLARI_FILE))}`) yüklenemedi veya boş\\."

        response_lines = []

        # Anahtar kelimelere göre emoji eşleştirme (daha spesifik olanlar önce gelmeli)
        emoji_map = {
            "peg oranı": "🎯",
            "f/k oranı": "💰",
            "pd/dd": "⚖️",
            "net borç/favök": "🏦",
            "cari oran": "💧",
            "likidite oranı": "🩸",
            "net dönem karı": "📈", # Artış/Azalışa göre emoji değişebilir
            "net kar marjı": "💸",
            "favök marjı": "🛠️",
            "brüt kar marjı": "🛒",
            "finansal borç": "📉",
            "net borç": "💳",
            "dönen varlıklar": "🔄",
            "duran varlıklar": "🏢",
            "toplam varlıklar": "🏛️",
            "özkaynak": "🧱",
            "aktif karlılık": "💡",
            "özkaynak karlılığı": "🔥",
            "büyüme": "🚀",
            "temettü": " dividend ", # Boşluklar kelime eşleşmesi için
            # Eşleşme bulunamazsa kullanılacak varsayılan emoji
            "default": "➡️"
        }

        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper() # Temizle ve büyük harfe çevir
            analiz_data = bist_analiz_data.get(ticker)

            if analiz_data:
                # Verileri güvenli bir şekilde al ve escape et
                symbol = escape_markdown_v2(analiz_data.get("symbol", ticker))
                score = escape_markdown_v2(analiz_data.get("score", "N/A"))
                classification = escape_markdown_v2(analiz_data.get("classification", "Belirtilmemiş"))
                comments = analiz_data.get("comments", []) # Yorumlar liste olmalı

                formatted_comments_list = []
                if comments and isinstance(comments, list):
                    for comment in comments:
                        if not isinstance(comment, str): continue # Yorum string değilse atla
                        comment_lower = comment.lower() # Küçük harfe çevirerek kontrol
                        chosen_emoji = emoji_map["default"] # Varsayılan emoji ile başla

                        # En uygun emojiyi bul
                        best_match_keyword = None
                        for keyword in emoji_map:
                            if keyword == "default": continue
                            # Kelime sınırları ile daha hassas kontrol
                            if re.search(r'\b' + re.escape(keyword) + r'\b', comment_lower, re.IGNORECASE):
                                # Daha uzun anahtar kelime daha spesifik kabul edilebilir
                                if best_match_keyword is None or len(keyword) > len(best_match_keyword):
                                     best_match_keyword = keyword

                        if best_match_keyword:
                            chosen_emoji = emoji_map[best_match_keyword]

                        # Yorumu escape et
                        escaped_comment = escape_markdown_v2(comment)
                        formatted_comments_list.append(f"{chosen_emoji} {escaped_comment}")

                    formatted_comments = "\n".join(formatted_comments_list)
                else:
                    formatted_comments = "_Yorum bulunamadı\\._" # Markdown italik

                # Mesajı oluştur
                response_lines.append(
                    f"📊 *BİST Detaylı Analiz*\n\n"
                    f"🏷️ *Sembol:* {symbol}\n"
                    f"📈 *Puan:* {score}\n"
                    f"🏅 *Sınıflandırma:* {classification}\n\n"
                    f"📝 *Öne Çıkanlar:*\n{formatted_comments}"
                )
            else:
                response_lines.append(f"❌ `{escape_markdown_v2(ticker)}` için detaylı BIST analizi bulunamadı\\.")

        return "\n\n---\n\n".join(response_lines) # Analizler arasına ayırıcı ekle

# --- Flask Endpointleri ---

@app.route("/signal", methods=["POST"])
def receive_signal():
    """TradingView veya başka bir kaynaktan gelen sinyalleri alır."""
    signal_text = request.data.decode("utf-8")
    print(f"--- Gelen Sinyal Raw: ---\n{signal_text}\n------------------------")

    if not signal_text:
        print("⚠️ Boş sinyal verisi alındı.")
        return "Boş veri", 400 # Bad Request

    # Her satırı ayrı bir sinyal olarak işle
    processed_count = 0
    new_signal_details = [] # Telegram'a gönderilecek yeni sinyallerin detayları

    for line in signal_text.strip().split('\n'):
        line = line.strip()
        if not line: continue # Boş satırları atla

        parsed_data = parse_signal_line(line)

        if parsed_data:
            borsa = parsed_data.get("borsa", "unknown").lower()
            symbol = parsed_data.get("symbol", "N/A")
            signal_type = parsed_data.get("type", "INFO")
            timestamp = parsed_data.get("time")
            source = parsed_data.get("source", "Belirtilmemiş")

            # Zorunlu alan kontrolü
            if borsa == "unknown" or symbol == "N/A":
                 print(f"❌ Geçersiz sinyal (borsa veya sembol eksik): {line}")
                 continue # Bu satırı atla

            # Bellekteki veriyi güncelle (kilitle)
            with signals_lock:
                if borsa not in signals_data:
                    signals_data[borsa] = []

                # Aynı sembol için eski sinyali bul ve üzerine yaz/güncelle (opsiyonel)
                # Şimdilik basitçe sona ekleyelim:
                signals_data[borsa].append(parsed_data)

                # Son sinyal zamanını güncelle
                last_signal_time[borsa] = timestamp

            # Yeni sinyal detayını listeye ekle
            new_signal_details.append(
                f"*{escape_markdown_v2(borsa.upper())}* \\- `{escape_markdown_v2(symbol)}` "
                f"{'🟢 AL' if signal_type == 'BUY' else ('🔴 SAT' if signal_type == 'SELL' else 'ℹ️ INFO')} "
                f"_(Kaynak: {escape_markdown_v2(source)})_ "
                f"\\({escape_markdown_v2(timestamp)}\\)"
            )
            processed_count += 1
            print(f"✅ Sinyal işlendi ve eklendi: {parsed_data}")

        else:
            print(f"⚠️ Sinyal ayrıştırılamadı: {line}")
            # Ayrıştırılamayan sinyaller için de bir bildirim gönderilebilir (opsiyonel)
            # send_telegram_message(f"⚠️ Ayrıştırılamayan sinyal alındı:\n```\n{line}\n```")

    if processed_count > 0:
        # Sinyalleri dosyaya kaydet
        save_signals()

        # Yeni sinyalleri Telegram'a gönder
        if new_signal_details:
             message_to_send = "🚨 *Yeni Sinyal(ler) Alındı:*\n\n" + "\n".join(new_signal_details)
             send_telegram_message(message_to_send)

        return f"{processed_count} sinyal işlendi.", 200
    else:
        return "Gelen veride işlenecek geçerli sinyal bulunamadı.", 400 # Bad Request


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Telegram'dan gelen mesajları (komutları) işler."""
    print(">>> /telegram endpoint tetiklendi")
    webhook_start_time = time.time()
    try:
        update = request.json
        if not update:
            print("Boş JSON verisi alındı.")
            return "ok", 200 # Telegram'a hızlı yanıt dönmek önemli

        # Mesaj veya düzenlenmiş mesajı al
        message = update.get("message") or update.get("edited_message")
        if not message:
            update_type = next((key for key in update if key != 'update_id'), 'bilinmiyor')
            print(f"Desteklenmeyen güncelleme türü '{update_type}' alındı, işlenmiyor.")
            return "ok", 200

        text = message.get("text", "").strip()
        chat_info = message.get("chat")
        user_info = message.get("from")

        if not chat_info or not user_info:
             print("❌ Sohbet veya kullanıcı bilgisi eksik, mesaj işlenemiyor.")
             return "ok", 200

        chat_id = chat_info.get("id")
        user_id = user_info.get("id")
        first_name = user_info.get("first_name", "")
        username = user_info.get("username", "N/A")

        # Sadece belirlenen CHAT_ID'den gelen mesajları işle
        if str(chat_id) != CHAT_ID:
            print(f"⚠️ Uyarı: Mesaj beklenen sohbetten ({CHAT_ID}) gelmedi. Gelen: {chat_id}. İşlenmeyecek.")
            return "ok", 200

        if not text:
            print("Boş mesaj içeriği alındı.")
            return "ok", 200

        print(f">>> Mesaj alındı (Chat: {chat_id}, User: {first_name} [{username}/{user_id}]): {text}")

        response_message = "" # Gönderilecek yanıt mesajı
        command_processed = False # Komut işlendi mi?

        # Komutları işle
        if text.startswith("/ozet"):
            command_processed = True
            print(">>> /ozet komutu işleniyor...")
            parts = text.split(maxsplit=1)
            keyword = parts[1].lower() if len(parts) > 1 else None
            allowed_keywords = ["bats", "nasdaq", "bist", "binance"] # İzin verilen borsa anahtar kelimeleri
            print(f"Anahtar kelime: {keyword}")

            if keyword and keyword not in allowed_keywords:
                 allowed_str = ", ".join([f"`{k}`" for k in allowed_keywords])
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{escape_markdown_v2(keyword)}`\\. İzin verilenler: {allowed_str}\\."
                 print(f"Geçersiz özet anahtar kelimesi: {keyword}")
            else:
                 summary = generate_summary(keyword) # Belirli bir borsa veya tümü için özet
                 response_message = summary

        elif text.startswith("/analiz"):
            command_processed = True
            print(">>> /analiz komutu işleniyor...")
            tickers_input = text[len("/analiz"):].strip()
            if not tickers_input:
                 response_message = "Lütfen bir veya daha fazla hisse kodu belirtin\\. Örnek: `/analiz GOOGL,AAPL`"
            else:
                # Virgül, boşluk veya her ikisiyle ayrılmış kodları işle
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers:
                     response_message = "Geçerli bir hisse kodu bulunamadı\\. Örnek: `/analiz GOOGL,AAPL`"
                else:
                    print(f"Analiz istenen hisseler (/analiz): {tickers}")
                    response_message = generate_analiz_response(tickers)

        elif text.startswith("/bist_analiz"):
            command_processed = True
            print(">>> /bist_analiz komutu işleniyor...")
            tickers_input = text[len("/bist_analiz"):].strip()
            if not tickers_input:
                response_message = "Lütfen bir veya daha fazla BIST hisse kodu belirtin\\. Örnek: `/bist_analiz EREGL,TUPRS`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers:
                     response_message = "Geçerli bir hisse kodu bulunamadı\\. Örnek: `/bist_analiz EREGL,TUPRS`"
                else:
                    print(f"Detaylı analiz istenen hisseler (/bist_analiz): {tickers}")
                    response_message = generate_bist_analiz_response(tickers)

        elif text.startswith("/clear_signals"):
            command_processed = True
            print(">>> /clear_signals komutu işleniyor...")
            # Bu komutu sadece belirli kullanıcılar çalıştırabilmeli (opsiyonel güvenlik)
            # if str(user_id) == "ADMIN_USER_ID":
            if clear_signals():
                response_message = "✅ Tüm sinyal ve analiz verileri başarıyla temizlendi\\."
            else:
                response_message = "❌ Veriler temizlenirken bir hata oluştu\\."
            # else:
            #    response_message = "⛔ Bu komutu kullanma yetkiniz yok."

        elif text.startswith("/start") or text.startswith("/help"):
            command_processed = True
            print(">>> /start veya /help komutu işleniyor...")
            response_message = "👋 *Merhaba\\! Kullanabileceğiniz komutlar:*\n\n" \
                               "• `/ozet` : Tüm borsalardan gelen sinyallerin özetini gösterir\\.\n" \
                               "• `/ozet [borsa]` : Belirli bir borsa için özet gösterir \\(Örn: `/ozet bist`, `/ozet nasdaq`\\)\\.\n" \
                               "• `/analiz [HİSSE1,HİSSE2,\\.\\.\\.]` : Belirtilen hisseler için temel analiz puanını ve yorumunu gösterir \\(Örn: `/analiz GOOGL,AAPL`\\)\\.\n" \
                               "• `/bist_analiz [HİSSE1,HİSSE2,\\.\\.\\.]` : Belirtilen BIST hisseleri için daha detaylı analizi gösterir \\(Örn: `/bist_analiz EREGL,TUPRS`\\)\\.\n" \
                               "• `/clear_signals` : Kayıtlı tüm sinyal ve analiz verilerini temizler \\(Dikkatli kullanın\\!\\)\\.\n" \
                               "• `/help` : Bu yardım mesajını gösterir\\."

        # Yanıt gönderilecekse gönder
        if response_message:
             send_telegram_message(response_message)
        elif not command_processed:
             print(f"Bilinmeyen komut veya metin alındı: {text}")
             # Bilinmeyen komutlara yanıt vermemek genellikle daha iyidir
             # response_message = f"❓ `{escape_markdown_v2(text)}` komutunu anlayamadım\\. Yardım için `/help` yazabilirsiniz\\."
             # send_telegram_message(response_message)

        processing_time = time.time() - webhook_start_time
        print(f"<<< /telegram endpoint tamamlandı ({processing_time:.3f} saniye)")
        return "ok", 200 # Telegram'a başarılı yanıt

    except Exception as e:
        print(f"❌ /telegram endpoint genel hatası: {e}")
        print(traceback.format_exc()) # Hatayı detaylı logla
        # Hata durumunda kullanıcıya genel bir mesaj göndermeyi dene
        try:
             # 'chat_id' değişkeninin tanımlı olup olmadığını kontrol et
             if 'chat_id' in locals() and str(chat_id) == CHAT_ID:
                 error_message = "🤖 Üzgünüm, isteğinizi işlerken beklenmedik bir hata oluştu\\. Lütfen daha sonra tekrar deneyin veya yönetici ile iletişime geçin\\."
                 send_telegram_message(error_message)
             else:
                 print("Hata oluştu ancak hedef sohbet ID'si belirlenemedi veya yetkisiz.")
        except Exception as telegram_err:
             print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        # Sunucu hatası olarak yanıt ver
        return "Internal Server Error", 500


@app.route("/clear_signals_endpoint", methods=["POST"]) # POST ile daha güvenli
def clear_signals_endpoint():
    """Manuel olarak sinyalleri temizlemek için bir endpoint (güvenlik eklenmeli)."""
    # İsteğe bağlı: IP kontrolü veya basit bir şifre/token kontrolü eklenebilir
    # Örneğin:
    # secret_key = request.headers.get("X-Clear-Secret")
    # if secret_key != os.getenv("CLEAR_SECRET_KEY"):
    #     print("❌ Yetkisiz temizleme isteği.")
    #     return "Unauthorized", 401

    print(">>> /clear_signals_endpoint tetiklendi (manuel temizlik)")
    if clear_signals():
        send_telegram_message("🧹 Manuel olarak tüm sinyal ve analiz verileri temizlendi\\.")
        return "Sinyaller temizlendi.", 200
    else:
        send_telegram_message("❌ Manuel temizlik sırasında bir hata oluştu\\!")
        return "Temizleme hatası.", 500

@app.route("/")
def home():
    """Ana sayfa, botun çalıştığını gösterir."""
    return "Telegram Sinyal ve Analiz Botu Aktif!", 200

# --- Uygulama Başlangıcı ---
if __name__ == "__main__":
    print("🚀 Flask uygulaması başlatılıyor...")

    # Ortam değişkenlerini kontrol et
    if not BOT_TOKEN: print("❌ UYARI: BOT_TOKEN .env dosyasında ayarlanmamış!")
    if not CHAT_ID: print("❌ UYARI: CHAT_ID .env dosyasında ayarlanmamış!")
    if not SIGNALS_FILE: print("⚠️ Uyarı: SIGNALS_FILE_PATH ayarlanmamış, 'signals.json' kullanılacak.")
    if not ANALIZ_FILE: print("⚠️ Uyarı: ANALIZ_FILE_PATH ayarlanmamış, 'analiz.json' kullanılacak.")
    if not ANALIZ_SONUCLARI_FILE: print("⚠️ Uyarı: ANALIZ_SONUCLARI_FILE_PATH ayarlanmamış, 'analiz_sonuclari.json' kullanılacak.")

    # JSON dosyalarının varlığını kontrol et veya oluştur
    for filepath in [SIGNALS_FILE, ANALIZ_FILE, ANALIZ_SONUCLARI_FILE]:
        if filepath and not os.path.exists(filepath):
            print(f"ℹ️ {filepath} dosyası bulunamadı, boş olarak oluşturuluyor...")
            if not save_json_file(filepath, {}):
                 print(f"❌ {filepath} dosyası oluşturulamadı!")

    # Başlangıçta verileri tekrar yükle (dosya oluşturma sonrası için)
    load_signals()
    load_analiz_data()
    load_bist_analiz_data()

    # Arka plan günlük temizlik görevini başlat
    # Daemon=True, ana program bittiğinde thread'in de bitmesini sağlar
    cleanup_thread = threading.Thread(target=clear_signals_daily, daemon=True)
    cleanup_thread.start()
    print("✅ Günlük sinyal temizleme görevi arka planda başlatıldı.")

    # Flask uygulamasını çalıştır
    port = int(os.getenv("PORT", 5000))
    # DEBUG modunu ortam değişkeninden al, varsayılan False
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t")
    print(f"🔧 Ayarlar: Port={port}, Debug={debug_mode}, Timezone={TIMEZONE}")
    print(f"📂 Veri Dosyaları: Sinyal='{SIGNALS_FILE}', Analiz='{ANALIZ_FILE}', BIST Analiz='{ANALIZ_SONUCLARI_FILE}'")

    # Gunicorn gibi bir WSGI sunucusu ile production'da çalıştırırken debug=False olmalı
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
