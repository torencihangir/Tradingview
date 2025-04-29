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
    TIMEZONE = pytz.timezone(os.getenv("TIMEZONE", "Europe/Istanbul")) # Zaman dilimini .env'den al veya varsayılan kullan
except pytz.exceptions.UnknownTimeZoneError:
    print(f"❌ Uyarı: .env dosyasındaki TIMEZONE '{os.getenv('TIMEZONE')}' geçersiz. 'Europe/Istanbul' kullanılacak.")
    TIMEZONE = pytz.timezone("Europe/Istanbul")

# Bellekte verileri tutmak için (Uygulama yeniden başladığında sıfırlanır)
# Daha kalıcı depolama için dosya okuma/yazma veya veritabanı kullanılır.
signals_data = {}
analiz_data = {}
bist_analiz_data = {}
last_signal_time = {} # Her borsa için son sinyal zamanını tutar

# Eşzamanlılık için Kilitler (Thread safety)
signals_lock = threading.Lock()
analiz_lock = threading.Lock()
bist_analiz_lock = threading.Lock()

# --- Yardımcı Fonksiyonlar ---

def escape_markdown_v2(text):
    """
    Telegram MarkdownV2 için özel karakterleri kaçırır.
    """
    if not isinstance(text, str):
        text = str(text) # Gelen verinin string olduğundan emin ol
    # Özel karakterler listesi: _ * [ ] ( ) ~ ` > # + - = | { } . !
    # Önce ters eğik çizgiyi kaçır, sonra diğerlerini
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    text = text.replace('\\', '\\\\') # Ters eğik çizgiyi kendisiyle kaçır
    # Diğer özel karakterleri kaçır
    for char in escape_chars:
        text = text.replace(char, f'\\{char}')
    return text

def send_telegram_message(message):
    """Telegram'a mesaj gönderir, MarkdownV2 kaçırma işlemi yapar ve uzun mesajları böler."""
    if not BOT_TOKEN or not CHAT_ID:
        print("❌ Hata: BOT_TOKEN veya CHAT_ID ayarlanmamış. Mesaj gönderilemiyor.")
        return

    # Tüm mesajı escape etmek yerine, dinamik kısımları escape etmek daha güvenli olabilir,
    # ancak komut yanıtları genellikle yapılandırılmış olduğundan tümünü escape edebiliriz.
    # Dikkat: Eğer mesaj içinde zaten Markdown formatlaması varsa (örn. *kalın*),
    # escape_markdown_v2 bunu bozacaktır. Bu durumda formatlamayı escape etmeden önce yapmalısınız.
    # Şimdilik tüm mesajı escape ediyoruz. Komut yanıtlarını oluştururken buna dikkat edin.
    escaped_message = message # escape_markdown_v2(message) # -> Markdown'ı kendimiz eklediğimiz için burada escape ETMEYELİM

    max_length = 4096 # Telegram API limiti

    # Mesajı 4096 karakterlik parçalara böl
    for i in range(0, len(escaped_message), max_length):
        chunk = escaped_message[i:i+max_length]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "MarkdownV2" # Formatlamayı kullanacağımızı belirtiyoruz
        }
        try:
            r = requests.post(url, json=data, timeout=30) # Timeout süresi artırıldı
            r.raise_for_status() # HTTP 4xx veya 5xx hatalarında exception fırlatır
            print(f"✅ Telegram yanıtı: {r.status_code}")
            time.sleep(0.5) # Rate limiting'i önlemek için kısa bekleme
        except requests.exceptions.Timeout:
            print(f"❌ Telegram API zaman aşımına uğradı.")
        except requests.exceptions.HTTPError as http_err:
            # Telegram'dan gelen hata mesajını logla
            error_response = r.text
            print(f"❌ Telegram HTTP Hatası: {http_err} - Yanıt: {error_response}")
            print(f"❌ Gönderilemeyen mesaj parçası (ilk 100kr): {chunk[:100]}...")
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi (RequestException): {e}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")
            print(traceback.format_exc())

def load_json_file(filepath):
    """Genel JSON dosyası yükleme fonksiyonu."""
    try:
        if not filepath:
            print("❌ Hata: Geçersiz dosya yolu (None veya boş).")
            return None # Hata durumunu belirtmek için None dön
        if not os.path.exists(filepath):
             print(f"⚠️ Uyarı: {filepath} dosyası bulunamadı. Boş veri döndürülüyor.")
             return {} # Dosya yoksa boş dict dönmek genellikle daha güvenli
        if os.path.getsize(filepath) == 0:
            print(f"⚠️ Uyarı: {filepath} dosyası boş.")
            return {} # Boş dosya ise boş dict dön
        with open(filepath, "r", encoding="utf-8") as file:
            data = json.load(file)
            print(f"✅ {filepath} başarıyla yüklendi.")
            return data
    except FileNotFoundError:
        print(f"⚠️ Uyarı: {filepath} dosyası bulunamadı (tekrar kontrol).")
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ Hata: {filepath} dosyası geçerli bir JSON formatında değil. Hata: {e}")
        try:
             with open(filepath, "r", encoding="utf-8") as f_err:
                 print(f"Dosyanın başı (ilk 200kr): {f_err.read(200)}...")
        except Exception as read_err:
             print(f"❌ Hata dosyasını okuma hatası: {read_err}")
        return {} # Hatalı formatta da boş dict dön
    except IOError as e:
        print(f"❌ G/Ç Hatası ({filepath} okuma): {e}")
        return {}
    except Exception as e:
        print(f"❌ Beklenmedik Hata ({filepath} okuma): {e}")
        print(traceback.format_exc())
        return {}

def save_json_file(filepath, data):
    """Genel JSON dosyası kaydetme fonksiyonu."""
    try:
        if not filepath:
            print("❌ Hata: Geçersiz dosya yolu (None veya boş).")
            return False
        directory = os.path.dirname(filepath)
        if directory and not os.path.exists(directory):
            os.makedirs(directory) # Gerekirse dizini oluştur
            print(f"ℹ️ Dizin oluşturuldu: {directory}")
        with open(filepath, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=4)
        print(f"✅ Veri başarıyla şuraya kaydedildi: {filepath}")
        return True
    except IOError as e:
        print(f"❌ G/Ç Hatası ({filepath} yazma): {e}")
        return False
    except TypeError as e:
        # JSON'a çevrilemeyen veri tipi varsa (örn. datetime objesi)
        print(f"❌ Tip Hatası (JSON serileştirme): {e}. Veri (ilk 200kr): {str(data)[:200]}...")
        return False
    except Exception as e:
        print(f"❌ Beklenmedik Hata ({filepath} yazma): {e}")
        print(traceback.format_exc())
        return False

def load_signals():
    """signals.json dosyasını yükler ve global signals_data'yı günceller."""
    global signals_data, last_signal_time
    print(f"🔄 Sinyal verileri yükleniyor: {SIGNALS_FILE}")
    with signals_lock:
        loaded_data = load_json_file(SIGNALS_FILE)
        if loaded_data is not None: # Yükleme başarılıysa veya dosya yoksa/boşsa {} döner
            signals_data = loaded_data
            # Yüklenen veriden last_signal_time'ı yeniden oluştur (opsiyonel ama iyi fikir)
            last_signal_time = {}
            for borsa, signal_list in signals_data.items():
                if signal_list:
                    # Sinyalleri zamana göre sıralayıp en sonuncuyu al
                    try:
                        # Zaman formatını varsayalım: "YYYY-MM-DD HH:MM:SS ZONE+/-HHMM"
                        latest_signal = max(signal_list, key=lambda s: datetime.strptime(s.get('time', '1970-01-01 00:00:00 +0000')[:19], "%Y-%m-%d %H:%M:%S"))
                        last_signal_time[borsa] = latest_signal.get('time')
                    except (ValueError, TypeError) as dt_err:
                         print(f"⚠️ {borsa} için son sinyal zamanı belirlenirken hata: {dt_err}. Sinyal: {signal_list[-1] if signal_list else 'Yok'}")
                         # Hata durumunda en son eklenenin zamanını almayı dene
                         if signal_list and 'time' in signal_list[-1]:
                             last_signal_time[borsa] = signal_list[-1]['time']

            print(f"✅ Sinyal verileri yüklendi. Borsalar: {list(signals_data.keys())}")
            print(f"⏳ Son sinyal zamanları: {last_signal_time}")
        else:
            # load_json_file None döndürdüyse (ciddi okuma hatası), mevcut veriyi koru
            print("❌ Sinyal dosyası okuma hatası. Bellekteki veri korunuyor (varsa).")
            signals_data = signals_data or {} # Eğer hiç yüklenmemişse boş dict olsun

def save_signals():
    """Bellekteki signals_data'yı dosyaya kaydeder."""
    print(f"💾 Sinyal verileri kaydediliyor: {SIGNALS_FILE}")
    with signals_lock:
        if not save_json_file(SIGNALS_FILE, signals_data):
            print(f"❌ Sinyal verileri şuraya kaydedilemedi: {SIGNALS_FILE}")

def load_analiz_data():
    """analiz.json dosyasını yükler."""
    global analiz_data
    print(f"🔄 Analiz verileri yükleniyor: {ANALIZ_FILE}")
    with analiz_lock:
        loaded_data = load_json_file(ANALIZ_FILE)
        if loaded_data is not None:
            analiz_data = loaded_data
            print(f"✅ Analiz verileri yüklendi. {len(analiz_data)} kayıt.")
        else:
            print("❌ Analiz dosyası okuma hatası. Bellekteki veri korunuyor (varsa).")
            analiz_data = analiz_data or {}

def load_bist_analiz_data():
    """analiz_sonuclari.json dosyasını yükler."""
    global bist_analiz_data
    print(f"🔄 BIST Analiz verileri yükleniyor: {ANALIZ_SONUCLARI_FILE}")
    with bist_analiz_lock:
        loaded_data = load_json_file(ANALIZ_SONUCLARI_FILE)
        if loaded_data is not None:
            bist_analiz_data = loaded_data
            print(f"✅ BIST Analiz verileri yüklendi. {len(bist_analiz_data)} kayıt.")
        else:
            print("❌ BIST Analiz dosyası okuma hatası. Bellekteki veri korunuyor (varsa).")
            bist_analiz_data = bist_analiz_data or {}

def parse_signal_line(line):
    """TradingView alert mesajını veya benzer formatı ayrıştırır."""
    line = line.strip()
    if not line:
        return None

    data = {"raw": line, "borsa": "unknown", "symbol": "N/A", "type": "INFO", "source": "Belirtilmemiş"}

    # 1. Borsa Adı (Genellikle başta ve ':' ile biter)
    borsa_match = re.match(r"^(\w+)[:\s]+", line, re.IGNORECASE)
    if borsa_match:
        borsa_raw = borsa_match.group(1).lower()
        borsa_map = {"bist": "bist", "xu100": "bist", "nasdaq": "nasdaq", "ndx": "nasdaq",
                     "binance": "binance", "crypto": "binance", "bats": "bats", "us": "bats"}
        data["borsa"] = borsa_map.get(borsa_raw, borsa_raw) # Bilinenlerle eşle, yoksa olduğu gibi al
        line = line[len(borsa_match.group(0)):].strip() # Borsa kısmını kaldır
    else:
        print(f"⚠️ Sinyalde borsa adı bulunamadı: {data['raw']}")
        # İçeriğe göre tahmin denenebilir ama şimdilik unknown kalsın

    # 2. Sembol (Genellikle büyük harf/rakam grubu)
    # Örnekler: AAPL, GOOG, BTCUSDT, ETH/BTC, EURUSD, TUPRS.IS, XU100
    # Daha esnek regex: \b([A-Z0-9\./-]{2,})\b - en az 2 karakterli harf/rakam/./- içeren
    symbol_match = re.search(r"\b([A-Z0-9\./-]{2,})\b", line)
    if symbol_match:
        data["symbol"] = symbol_match.group(1).upper()
        # Sembolü satırdan çıkarıp kalan metni işlemeyi kolaylaştırabiliriz (opsiyonel)
        # line = line.replace(symbol_match.group(1), "", 1).strip()
    else:
        print(f"⚠️ Sinyalde sembol bulunamadı: {data['raw']}")

    # 3. Sinyal Tipi (AL/SAT, LONG/SHORT, vb.)
    if re.search(r"\b(AL|ALIM|LONG|BUY)\b", line, re.IGNORECASE):
        data["type"] = "BUY"
    elif re.search(r"\b(SAT|SATIM|SHORT|SELL)\b", line, re.IGNORECASE):
        data["type"] = "SELL"
    # else: INFO olarak kalır

    # 4. Zaman (Opsiyonel - ISO veya Unix timestamp)
    time_str = None
    time_match_iso = re.search(r"time:?\s*(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", line, re.IGNORECASE)
    time_match_unix = re.search(r"time:?\s*(\d{10,})", line, re.IGNORECASE)
    if time_match_iso:
        try:
            utc_time = datetime.strptime(time_match_iso.group(1), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=pytz.utc)
            time_str = utc_time.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z")
        except ValueError: pass # Hatalı formatı yoksay
    elif time_match_unix:
         try:
            utc_time = datetime.fromtimestamp(int(time_match_unix.group(1)), tz=pytz.utc)
            time_str = utc_time.astimezone(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z")
         except ValueError: pass # Hatalı formatı yoksay

    data["time"] = time_str if time_str else datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S %Z%z")

    # 5. Kaynak/Strateji (Opsiyonel)
    source_match = re.search(r"(?:strategy|kaynak|nedeni|indicator)[:\s]+(.+)", line, re.IGNORECASE)
    if source_match:
        # Kaynaktan sonra başka anahtar kelime (örn. 'price:') geliyorsa onu alma
        source_text = source_match.group(1).strip()
        stop_keywords = ["price:", "time:", "signal:"]
        for keyword in stop_keywords:
            if keyword in source_text.lower():
                 source_text = source_text[:source_text.lower().find(keyword)].strip()
        if source_text:
             data["source"] = source_text

    # Zorunlu alanlar (borsa ve symbol) olmadan sinyali geçersiz say
    if data["borsa"] == "unknown" or data["symbol"] == "N/A":
        print(f"❌ Ayrıştırma başarısız (borsa/sembol eksik): {data}")
        return None

    return data

def clear_signals():
    """Bellekteki ve dosyalardaki tüm sinyal ve analiz verilerini temizler."""
    global signals_data, analiz_data, bist_analiz_data, last_signal_time
    print("🧹 Tüm veriler temizleniyor...")
    success = True
    with signals_lock:
        signals_data = {}
        last_signal_time = {}
        if not save_json_file(SIGNALS_FILE, {}):
            print(f"❌ {SIGNALS_FILE} dosyası temizlenirken hata.")
            success = False
        else:
            print(f"✅ {SIGNALS_FILE} temizlendi.")
    with analiz_lock:
        analiz_data = {}
        # Dosya varsa temizle
        if os.path.exists(ANALIZ_FILE):
            if not save_json_file(ANALIZ_FILE, {}):
                print(f"❌ {ANALIZ_FILE} dosyası temizlenirken hata.")
                success = False
            else:
                print(f"✅ {ANALIZ_FILE} temizlendi.")
    with bist_analiz_lock:
        bist_analiz_data = {}
         # Dosya varsa temizle
        if os.path.exists(ANALIZ_SONUCLARI_FILE):
            if not save_json_file(ANALIZ_SONUCLARI_FILE, {}):
                print(f"❌ {ANALIZ_SONUCLARI_FILE} dosyası temizlenirken hata.")
                success = False
            else:
                print(f"✅ {ANALIZ_SONUCLARI_FILE} temizlendi.")

    if success:
        print("✅ Tüm veriler başarıyla temizlendi.")
    else:
        print("⚠️ Temizleme işlemi sırasında bazı hatalar oluştu.")
    return success

def clear_signals_daily():
    """Her gün belirli bir saatte (örn. gece yarısı) verileri temizler."""
    CLEANUP_HOUR = int(os.getenv("CLEANUP_HOUR", 0)) # Temizlik saati (0-23), varsayılan gece 00
    CLEANUP_MINUTE = int(os.getenv("CLEANUP_MINUTE", 5)) # Temizlik dakikası, varsayılan 00:05
    print(f"📅 Günlük temizlik görevi ayarlandı: Her gün {CLEANUP_HOUR:02d}:{CLEANUP_MINUTE:02d}")

    while True:
        try:
            now = datetime.now(TIMEZONE)
            # Bir sonraki temizlik zamanını hesapla
            next_run_time = now.replace(hour=CLEANUP_HOUR, minute=CLEANUP_MINUTE, second=0, microsecond=0)
            if now >= next_run_time:
                # Eğer şu anki zaman hedeften sonraysa, sonraki güne ayarla
                next_run_time += timedelta(days=1)

            wait_seconds = (next_run_time - now).total_seconds()
            print(f"🌙 Sonraki günlük temizlik: {next_run_time.strftime('%Y-%m-%d %H:%M:%S %Z')} ({wait_seconds:.0f} saniye sonra)")

            # Negatif bekleme süresi olmaması için kontrol (nadiren olabilir)
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            else:
                 time.sleep(60) # 1 dakika bekle ve tekrar hesapla
                 continue

            print(f"⏰ {datetime.now(TIMEZONE).strftime('%Y-%m-%d %H:%M:%S')} - Günlük temizlik başlıyor...")
            if clear_signals():
                send_telegram_message("🧹 Günlük sinyal ve analiz verileri otomatik olarak temizlendi\\.")
            else:
                send_telegram_message("❌ Günlük otomatik temizlik sırasında bir hata oluştu\\!")
            print("✅ Günlük temizlik tamamlandı.")
            time.sleep(60) # Bir sonraki döngüye geçmeden önce kısa bekleme

        except Exception as e:
            print(f"❌ Günlük temizlik döngüsünde hata: {e}")
            print(traceback.format_exc())
            send_telegram_message("🚨 Günlük temizlik görevinde kritik hata oluştu\\! Kontrol gerekli\\.")
            time.sleep(3600) # Hata durumunda 1 saat bekle

# --- Çekirdek Fonksiyonlar (Komut Yanıtları) ---

def generate_summary(target_borsa=None):
    """Bellekteki sinyalleri kullanarak özet oluşturur."""
    with signals_lock:
        if not signals_data:
            return "ℹ️ Henüz kayıtlı sinyal bulunmamaktadır\\."

        summary_lines = []
        borsa_list = sorted(signals_data.keys()) # Alfabetik sırala
        active_borsa_list = [] # Sinyali olanları tut

        for borsa in borsa_list:
            # Belirli bir borsa istenmişse ve bu o değilse atla
            if target_borsa and borsa.lower() != target_borsa.lower():
                continue

            signals = signals_data[borsa]
            if not signals: continue # Bu borsa için sinyal yoksa atla

            active_borsa_list.append(borsa)
            buy_signals = sorted([s['symbol'] for s in signals if s.get('type') == 'BUY']) # Alfabetik sırala
            sell_signals = sorted([s['symbol'] for s in signals if s.get('type') == 'SELL'])
            info_signals = sorted([s['symbol'] for s in signals if s.get('type') == 'INFO'])

            # Markdown için sembolleri escape et
            safe_buy_str = ", ".join([f"`{escape_markdown_v2(s)}`" for s in buy_signals]) if buy_signals else "_Yok_"
            safe_sell_str = ", ".join([f"`{escape_markdown_v2(s)}`" for s in sell_signals]) if sell_signals else "_Yok_"
            safe_info_str = ", ".join([f"`{escape_markdown_v2(s)}`" for s in info_signals]) if info_signals else ""

            summary_lines.append(f"*{escape_markdown_v2(borsa.upper())}*") # Borsa adını kalın yap
            summary_lines.append(f"🟢 AL: {safe_buy_str}")
            summary_lines.append(f"🔴 SAT: {safe_sell_str}")
            if safe_info_str:
                summary_lines.append(f"ℹ️ INFO: {safe_info_str}")
            summary_lines.append("") # Borsalar arasına boşluk

        if not active_borsa_list:
            if target_borsa:
                return f"ℹ️ `{escape_markdown_v2(target_borsa.upper())}` için kayıtlı sinyal bulunmamaktadır\\."
            else: # Bu durum normalde yukarıda yakalanmalı
                 return "ℹ️ Henüz kayıtlı sinyal bulunmamaktadır\\."

        # Başlık
        title = "📊 *Sinyal Özeti*"
        if target_borsa:
            title += f" \\({escape_markdown_v2(target_borsa.upper())}\\)"

        # Son sinyal zamanı bilgisi
        time_info = ""
        last_time_str = None
        if target_borsa:
             last_time_str = last_signal_time.get(target_borsa.lower())
             if last_time_str:
                  time_info = f"⏳ _Son Sinyal ({escape_markdown_v2(target_borsa.upper())}): {escape_markdown_v2(last_time_str)}_\\n"
        else:
             # Genel özet için en son sinyali bul
             latest_time = None
             latest_borsa_name = None
             for b, t_str in last_signal_time.items():
                  if not t_str: continue
                  try:
                      # Zaman string'ini datetime'a çevir karşılaştırma için
                      # Format: 2023-10-27 15:30:00 Europe/Istanbul+0300
                      current_t = datetime.strptime(t_str[:19], "%Y-%m-%d %H:%M:%S")
                      # Timezone bilgisi varsa ekle (pytz ile)
                      tz_match = re.search(r'([+\-]\d{4})$', t_str)
                      if tz_match:
                          offset_seconds = int(tz_match.group(1)[:3]) * 3600 + int(tz_match.group(1)[0] + tz_match.group(1)[3:]) * 60
                          current_t = current_t.replace(tzinfo=pytz.FixedOffset(offset_seconds // 60))
                      else:
                           # Zaman dilimi yoksa varsayılanı kullan
                           current_t = TIMEZONE.localize(current_t)

                      if latest_time is None or current_t > latest_time:
                           latest_time = current_t
                           last_time_str = t_str # Orijinal string'i sakla
                           latest_borsa_name = b
                  except (ValueError, TypeError) as dt_err:
                      print(f"⚠️ Son sinyal zamanı karşılaştırma hatası: {dt_err}. Zaman: {t_str}")
                      continue
             if last_time_str and latest_borsa_name:
                  time_info = f"⏳ _En Son Sinyal ({escape_markdown_v2(latest_borsa_name.upper())}): {escape_markdown_v2(last_time_str)}_\\n"

        # Mesajı birleştir
        full_summary = f"{title}\n\n{time_info}\n" + "\n".join(summary_lines).strip()
        return full_summary

def generate_analiz_response(tickers):
    """analiz.json'dan (bellekten) veri çeker ve formatlar."""
    with analiz_lock:
        if not analiz_data:
             return f"⚠️ Genel Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_FILE))}`) yüklenemedi veya boş\\."

        response_lines = []
        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper()
            data = analiz_data.get(ticker)

            if data:
                symbol = escape_markdown_v2(data.get("symbol", ticker))
                score = escape_markdown_v2(data.get("score", "N/A"))
                # Yorumu escape etmeden önce içinde Markdown var mı kontrol et (zor)
                # Şimdilik yorumu da escape edelim.
                yorum = escape_markdown_v2(data.get("yorum", "_Yorum bulunamadı_"))

                response_lines.append(
                    f"📊 *Temel Analiz*\n\n"
                    f"🏷️ *Sembol:* `{symbol}`\n" # Sembolü kod formatında göster
                    f"📈 *Puan:* {score}\n"
                    f"💬 *Yorum:* {yorum}"
                )
            else:
                response_lines.append(f"❌ `{escape_markdown_v2(ticker)}` için temel analiz bulunamadı\\.")

        return "\n\n---\n\n".join(response_lines) # Ayırıcı ekle

def generate_bist_analiz_response(tickers):
    """analiz_sonuclari.json'dan (bellekten) veri çeker, emojilerle formatlar."""
    with bist_analiz_lock:
        if not bist_analiz_data:
             return f"⚠️ Detaylı BIST Analiz verileri (`{escape_markdown_v2(os.path.basename(ANALIZ_SONUCLARI_FILE))}`) yüklenemedi veya boş\\."

        response_lines = []
        emoji_map = {
            "peg oranı": "🎯", "f/k oranı": "💰", "pd/dd": "⚖️", "net borç/favök": "🏦",
            "cari oran": "💧", "likidite oranı": "🩸", "net dönem karı": "📈", "net kar marjı": "💸",
            "favök marjı": "🛠️", "brüt kar marjı": "🛒", "finansal borç": "📉", "net borç": "💳",
            "dönen varlıklar": "🔄", "duran varlıklar": "🏢", "toplam varlıklar": "🏛️", "özkaynak": "🧱",
            "aktif karlılık": "💡", "özkaynak karlılığı": "🔥", "büyüme": "🚀", "temettü": " dividend ",
            "default": "➡️"
        }

        for ticker_raw in tickers:
            ticker = ticker_raw.strip().upper()
            data = bist_analiz_data.get(ticker)

            if data:
                symbol = escape_markdown_v2(data.get("symbol", ticker))
                score = escape_markdown_v2(data.get("score", "N/A"))
                classification = escape_markdown_v2(data.get("classification", "_Belirtilmemiş_"))
                comments = data.get("comments", [])

                formatted_comments_list = []
                if comments and isinstance(comments, list):
                    for comment in comments:
                        if not isinstance(comment, str): continue
                        comment_lower = comment.lower()
                        chosen_emoji = emoji_map["default"]
                        best_match_keyword = None
                        for keyword in emoji_map:
                            if keyword == "default": continue
                            if re.search(r'\b' + re.escape(keyword) + r'\b', comment_lower, re.IGNORECASE):
                                if best_match_keyword is None or len(keyword) > len(best_match_keyword):
                                     best_match_keyword = keyword
                        if best_match_keyword:
                            chosen_emoji = emoji_map[best_match_keyword]

                        escaped_comment = escape_markdown_v2(comment)
                        formatted_comments_list.append(f"{chosen_emoji} {escaped_comment}")
                    formatted_comments = "\n".join(formatted_comments_list)
                else:
                    formatted_comments = "_Yorum bulunamadı\\._"

                response_lines.append(
                    f"📊 *BİST Detaylı Analiz*\n\n"
                    f"🏷️ *Sembol:* `{symbol}`\n" # Sembolü kod formatında
                    f"📈 *Puan:* {score}\n"
                    f"🏅 *Sınıflandırma:* {classification}\n\n"
                    f"📝 *Öne Çıkanlar:*\n{formatted_comments}"
                )
            else:
                response_lines.append(f"❌ `{escape_markdown_v2(ticker)}` için detaylı BIST analizi bulunamadı\\.")

        return "\n\n---\n\n".join(response_lines)

# --- Flask Endpointleri ---

@app.route("/", methods=["GET"])
def home():
    """Basit bir sağlık kontrolü veya hoşgeldin sayfası."""
    return f"Telegram Sinyal/Analiz Bot v1.0 Aktif! Son sinyaller: {len(signals_data.get('bist',[]))} BIST, {len(signals_data.get('nasdaq',[]))} NASDAQ.", 200

@app.route("/signal", methods=["POST"])
def receive_signal():
    """TradingView veya başka kaynaklardan sinyal alır."""
    signal_text = request.data.decode("utf-8")
    print(f"--- Gelen Sinyal Raw ---\n{signal_text}\n------------------------")

    if not signal_text.strip():
        print("⚠️ Boş sinyal verisi alındı.")
        return "Boş veri", 400

    processed_count = 0
    new_signal_details = [] # Telegram'a gönderilecekler

    for line in signal_text.strip().split('\n'):
        if not line.strip(): continue
        parsed_data = parse_signal_line(line)

        if parsed_data:
            borsa = parsed_data["borsa"].lower()
            symbol = parsed_data["symbol"]
            signal_type = parsed_data["type"]
            timestamp = parsed_data["time"]
            source = parsed_data["source"]

            # Belleği ve dosyayı güncelle (kilitle)
            with signals_lock:
                if borsa not in signals_data:
                    signals_data[borsa] = []
                # Aynı sembol için eski sinyal varsa üzerine yazmak yerine yenisini ekle?
                # Veya son N sinyali tut? Şimdilik ekliyoruz.
                signals_data[borsa].append(parsed_data)
                last_signal_time[borsa] = timestamp # Son zamanı güncelle

            # Bildirim için formatla
            icon = "🟢" if signal_type == "BUY" else ("🔴" if signal_type == "SELL" else "ℹ️")
            new_signal_details.append(
                f"{icon} *{escape_markdown_v2(borsa.upper())}* \\- `{escape_markdown_v2(symbol)}` "
                f"*{escape_markdown_v2(signal_type)}* "
                f"_(Kaynak: {escape_markdown_v2(source)})_ "
                f"\\({escape_markdown_v2(timestamp)}\\)"
            )
            processed_count += 1
            print(f"✅ Sinyal işlendi: {parsed_data}")
        else:
            print(f"⚠️ Sinyal ayrıştırılamadı: {line}")

    if processed_count > 0:
        save_signals() # İşlenen sinyaller varsa dosyayı kaydet
        if new_signal_details:
             message_to_send = "🚨 *Yeni Sinyal(ler) Alındı:*\n\n" + "\n".join(new_signal_details)
             send_telegram_message(message_to_send)
        return f"{processed_count} sinyal işlendi.", 200
    else:
        # Hiç geçerli sinyal bulunamadıysa
        send_telegram_message(f"⚠️ Geçersiz formatta sinyal alındı:\n```\n{escape_markdown_v2(signal_text)}\n```")
        return "Gelen veride geçerli sinyal bulunamadı.", 400

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Telegram'dan gelen komutları işler."""
    print(">>> /telegram endpoint tetiklendi")
    webhook_start_time = time.time()
    try:
        update = request.json
        if not update:
            print("Boş JSON verisi alındı.")
            return "ok", 200

        message = update.get("message") or update.get("edited_message")
        if not message:
            update_type = next((key for key in update if key != 'update_id'), 'bilinmiyor')
            print(f"Desteklenmeyen güncelleme türü '{update_type}', işlenmiyor.")
            return "ok", 200

        text = message.get("text", "").strip()
        chat_info = message.get("chat")
        user_info = message.get("from")

        if not chat_info or not user_info:
             print("❌ Sohbet veya kullanıcı bilgisi eksik.")
             return "ok", 200

        chat_id = chat_info.get("id")
        user_id = user_info.get("id")
        first_name = user_info.get("first_name", "")
        username = user_info.get("username", "N/A")

        # Sadece yetkili sohbetten gelenleri işle
        if str(chat_id) != CHAT_ID:
            print(f"⚠️ Yetkisiz sohbet ID: {chat_id} (Beklenen: {CHAT_ID}). İşlem yapılmayacak.")
            # İsteğe bağlı olarak yetkisiz kullanıcıya mesaj gönderilebilir
            # requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json={"chat_id": chat_id, "text": "Bu botu kullanma yetkiniz yok."})
            return "ok", 200

        if not text:
            print("Boş mesaj içeriği.")
            return "ok", 200

        print(f">>> Mesaj (Chat:{chat_id}, User:{first_name}[{username}/{user_id}]): {text}")

        response_message = None # Başlangıçta yanıt yok
        command_processed = False

        # Komut İşleme
        if text.lower().startswith("/ozet"):
            command_processed = True
            print(">>> /ozet komutu işleniyor...")
            parts = text.split(maxsplit=1)
            keyword = parts[1].lower() if len(parts) > 1 else None
            # İzin verilen borsa isimlerini global veriden alabiliriz
            # allowed_keywords = list(signals_data.keys()) # Veya sabit liste: ["bist", "nasdaq", ...]
            allowed_keywords = ["bist", "nasdaq", "bats", "binance"] # Sabit liste daha güvenli olabilir
            print(f"Anahtar kelime: {keyword}")

            if keyword and keyword not in allowed_keywords:
                 allowed_str = ", ".join([f"`{k}`" for k in allowed_keywords])
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{escape_markdown_v2(keyword)}`\\. İzin verilenler: {allowed_str} veya boş bırakın\\."
            else:
                 response_message = generate_summary(keyword)

        elif text.lower().startswith("/analiz"):
            command_processed = True
            print(">>> /analiz komutu işleniyor...")
            tickers_input = text[len("/analiz"):].strip()
            if not tickers_input:
                 response_message = "Lütfen bir veya daha fazla hisse kodu belirtin\\. Örnek: `/analiz GOOGL,AAPL`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers:
                     response_message = "Geçerli hisse kodu bulunamadı\\. Örnek: `/analiz GOOGL,AAPL`"
                else:
                    print(f"Analiz istenen hisseler (/analiz): {tickers}")
                    response_message = generate_analiz_response(tickers)

        elif text.lower().startswith("/bist_analiz"):
            command_processed = True
            print(">>> /bist_analiz komutu işleniyor...")
            tickers_input = text[len("/bist_analiz"):].strip()
            if not tickers_input:
                response_message = "Lütfen bir veya daha fazla BIST hisse kodu belirtin\\. Örnek: `/bist_analiz EREGL,TUPRS`"
            else:
                tickers = [t.strip().upper() for t in re.split(r'[,\s]+', tickers_input) if t.strip()]
                if not tickers:
                     response_message = "Geçerli hisse kodu bulunamadı\\. Örnek: `/bist_analiz EREGL,TUPRS`"
                else:
                    print(f"Detaylı analiz istenen hisseler (/bist_analiz): {tickers}")
                    response_message = generate_bist_analiz_response(tickers)

        elif text.lower().startswith("/clear_signals"):
             command_processed = True
             print(">>> /clear_signals komutu işleniyor...")
             # Güvenlik: Belki sadece belirli admin kullanıcılar?
             # ADMIN_USER_IDS = os.getenv("ADMIN_IDS", "").split(',')
             # if str(user_id) in ADMIN_USER_IDS:
             if clear_signals():
                 response_message = "✅ Tüm sinyal ve analiz verileri başarıyla temizlendi\\."
             else:
                 response_message = "❌ Veriler temizlenirken bir hata oluştu\\."
             # else:
             #     response_message = "⛔ Bu komutu kullanma yetkiniz yok."


        elif text.lower().startswith("/start") or text.lower().startswith("/help"):
            command_processed = True
            print(">>> /start veya /help komutu işleniyor...")
            response_message = (
                "👋 *Merhaba\\! Kullanabileceğiniz komutlar:*\n\n"
                "• `/ozet`: Tüm borsaların sinyal özeti\\.\n"
                "• `/ozet [borsa]`: Belirli borsa özeti \\(`bist`, `nasdaq`, `bats`, `binance`\\)\\.\n"
                "• `/analiz [HİSSE,\\.\\.]`: Temel analiz \\(Örn: `/analiz GOOGL,AAPL`\\)\\.\n"
                "• `/bist_analiz [HİSSE,\\.\\.]`: Detaylı BIST analizi \\(Örn: `/bist_analiz EREGL,TUPRS`\\)\\.\n"
                "• `/clear_signals`: Tüm kayıtlı verileri siler \\(Dikkat\\!\\)\\.\n"
                "• `/help`: Bu yardım mesajı\\."
            )

        # Yanıt varsa gönder
        if response_message:
            send_telegram_message(response_message)
        elif not command_processed:
            # Bilinmeyen komutlara yanıt verme (spam önleme)
            print(f"Bilinmeyen komut/metin: {text}")
            # send_telegram_message(f"❓ `{escape_markdown_v2(text)}` anlaşılamadı\\. Yardım için `/help` yazın\\.")

        processing_time = time.time() - webhook_start_time
        print(f"<<< /telegram endpoint tamamlandı ({processing_time:.3f} saniye)")
        return "ok", 200 # Her durumda Telegram'a OK dönmek önemli

    except Exception as e:
        print(f"❌ /telegram endpoint genel hatası: {e}")
        print(traceback.format_exc())
        try:
             if 'chat_id' in locals() and str(chat_id) == CHAT_ID:
                 error_message = "🤖 Üzgünüm, isteğinizi işlerken kritik bir hata oluştu\\. Lütfen logları kontrol edin veya tekrar deneyin\\."
                 send_telegram_message(error_message)
        except Exception as inner_e:
             print(f"❌ Hata mesajı Telegram'a gönderilemedi: {inner_e}")
        return "Internal Server Error", 500

@app.route("/clear_signals_endpoint", methods=["POST"]) # Manuel temizlik için (POST ile daha güvenli)
def clear_signals_endpoint():
    """Endpoint for manually clearing signals (e.g., via curl or another script). Add security!"""
    # --- GÜVENLİK EKLE ---
    # Örneğin basit bir secret key kontrolü:
    # expected_secret = os.getenv("CLEAR_SECRET_KEY")
    # provided_secret = request.headers.get("X-Clear-Secret")
    # if not expected_secret or provided_secret != expected_secret:
    #     print("❌ Yetkisiz manuel temizleme isteği reddedildi.")
    #     return "Unauthorized", 401
    # --- /GÜVENLİK EKLE ---

    print(">>> /clear_signals_endpoint tetiklendi (manuel temizlik)")
    if clear_signals():
        send_telegram_message("🧹 Manuel olarak tüm sinyal ve analiz verileri temizlendi\\.")
        return "Veriler temizlendi.", 200
    else:
        send_telegram_message("❌ Manuel temizlik sırasında hata oluştu\\!")
        return "Temizleme hatası.", 500

# --- Uygulama Başlangıcı ---
if __name__ == "__main__":
    print("*"*50)
    print("🚀 Flask Sinyal/Analiz Botu Başlatılıyor...")
    print("*"*50)

    # Ortam değişkenlerini kontrol et
    if not BOT_TOKEN: print("❌ UYARI: BOT_TOKEN .env dosyasında bulunamadı!")
    if not CHAT_ID: print("❌ UYARI: CHAT_ID .env dosyasında bulunamadı!")
    if not all([BOT_TOKEN, CHAT_ID]):
        print(">>> Lütfen .env dosyasını kontrol edip tekrar başlatın. <<<")
        exit() # Gerekli değişkenler yoksa çık

    print(f"🔧 Ayarlar: Timezone='{TIMEZONE}', Cleanup Time='{os.getenv('CLEANUP_HOUR', 0)}:{os.getenv('CLEANUP_MINUTE', 5)}'")
    print(f"📂 Veri Dosyaları: Sinyal='{SIGNALS_FILE}', Analiz='{ANALIZ_FILE}', BIST Analiz='{ANALIZ_SONUCLARI_FILE}'")

    # Gerekli JSON dosyalarını kontrol et/oluştur
    for filepath in [SIGNALS_FILE, ANALIZ_FILE, ANALIZ_SONUCLARI_FILE]:
        if filepath and not os.path.exists(filepath):
            print(f"ℹ️ {filepath} bulunamadı, boş olarak oluşturuluyor...")
            # save_json_file dizini de oluşturur
            if not save_json_file(filepath, {}):
                 print(f"❌ {filepath} oluşturulamadı! Manuel kontrol gerekli.")
                 # Kritikse burada çıkış yapılabilir: exit()
        elif filepath and os.path.exists(filepath) and os.path.getsize(filepath) == 0:
            # Dosya varsa ama boşsa, geçerli JSON formatı için {} yazalım
            print(f"ℹ️ Boş dosya bulundu: {filepath}. İçerik '{}' olarak ayarlanıyor.")
            save_json_file(filepath, {})


    # Başlangıçta verileri yükle
    print("\n--- Başlangıç Veri Yükleme ---")
    load_signals()
    load_analiz_data()
    load_bist_analiz_data()
    print("--- Veri Yükleme Tamamlandı ---\n")


    # Arka plan temizlik görevini başlat
    try:
        cleanup_thread = threading.Thread(target=clear_signals_daily, name="DailyCleanupThread", daemon=True)
        cleanup_thread.start()
        print("✅ Günlük otomatik temizlik görevi arka planda başlatıldı.")
    except Exception as thread_err:
        print(f"❌ Günlük temizlik thread'i başlatılamadı: {thread_err}")


    # Flask uygulamasını çalıştır
    port = int(os.getenv("PORT", 5000))
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() in ("true", "1", "t")
    host = "0.0.0.0" # Tüm ağ arayüzlerinden erişilebilir yap

    print(f"\n🌍 Sunucu başlatılıyor: http://{host}:{port} (Debug: {debug_mode})")
    print("🔑 Telegram Bot Token: Var, Chat ID: Var")
    print("🚦 Bot komut almaya hazır...")
    if debug_mode:
        print("⚠️ DİKKAT: Debug modu aktif. Production ortamında kullanmayın!")

    # Production için Gunicorn gibi bir WSGI sunucusu önerilir.
    # Örnek: gunicorn --bind 0.0.0.0:5000 main:app
    app.run(host=host, port=port, debug=debug_mode)
