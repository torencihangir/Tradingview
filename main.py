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

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# .env dosyasından değerleri al
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SIGNALS_FILE = "C:\\Users\\Administrator\\Desktop\\tradingview-telegram-bot\\signals.json" # Bu yolu kontrol et, belki daha göreceli bir yol daha iyi olur
ANALIZ_FILE = "analiz.json"
ANALIZ_SONUCLARI_FILE = "analiz_sonuclari.json" # YENİ EKLENDİ: Yeni JSON dosyasının adı

def escape_markdown_v2(text):
    # Telegram MarkdownV2'de özel karakterleri kaçırmak gerekiyor
    escape_chars = r"\_*[]()~`>#+-=|{}.!<>"
    # Özel not: Başlık gibi kalın veya italik yapmak istediğimiz yerlerdeki * ve _ karakterlerini
    # formatlama fonksiyonlarında ekleyip, burada sadece metin içindeki özel karakterleri kaçıracağız.
    # Ancak basitlik adına şimdilik hepsini kaçırabiliriz, send_telegram_message zaten yapıyor.
    # Bu fonksiyonun kendisi aslında send_telegram_message içinde çağrıldığı için burada tekrar yapmaya gerek yok gibi.
    # send_telegram_message içindeki kaçırma işlemi yeterli olacaktır.
    # Şimdilik bu fonksiyonu kullanmayalım, send_telegram_message hallediyor.
    # --> DÜZELTME: send_telegram_message içindeki kullanım doğru, burada tekrar yapmaya gerek yok.
    # escape_chars = r"\_[]()~`>#+-=|{}.!" # * ve < > ! karakterleri formatlama için kullanılabilir, onları kaçırmayalım? Deneme yanılma gerekebilir.
    return re.sub(r"([{}])".format(re.escape(escape_chars)), r"\\\1", text)


def send_telegram_message(message):
    # Mesajı Telegram'a göndermeden ÖNCE MarkdownV2 karakterlerini kaçır
    escaped_message = escape_markdown_v2(message)

    # Çok uzun mesajları parçalayarak gönder
    for i in range(0, len(escaped_message), 4096):
        chunk = escaped_message[i:i+4096]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "MarkdownV2"  # MarkdownV2 kullanıyoruz
        }
        try:
            r = requests.post(url, json=data, timeout=10) # Timeout artırıldı
            r.raise_for_status() # HTTP hatalarını kontrol et
            print("✅ Telegram yanıtı:", r.status_code)
            # print("Giden Mesaj Chunk:", chunk) # Hata ayıklama için
            # print("Telegram Yanıt Detayı:", r.text) # Hata ayıklama için
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi: {e}")
            # Hata durumunda orijinal (kaçırılmamış) mesajı da loglayabiliriz
            print(f"❌ Gönderilemeyen mesaj (orijinal): {message[i:i+4096]}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")


@app.route("/signal", methods=["POST"])
def receive_signal():
    try:
        print(">>> /signal endpoint tetiklendi")
        if request.is_json:
            data = request.get_json()
        else:
            # Ham metin verisini işle
            raw = request.data.decode("utf-8")
            # Daha esnek bir regex veya string işleme
            symbol, exchange, signal = "Bilinmiyor", "Bilinmiyor", raw.strip() # Varsayılan değerler
            match = re.match(r"^(.*?)\s+\((.*?)\)\s*-\s*(.*)$", raw)
            if match:
                symbol, exchange, signal = match.groups()
                symbol = symbol.strip()
                exchange = exchange.strip()
                signal = signal.strip()
            else:
                 # Eğer format eşleşmezse, ham veriyi sinyal olarak ata
                 print(f"Signal formatı ayrıştırılamadı: {raw}")


            data = {
                "symbol": symbol,
                "exchange": exchange,
                "signal": signal
            }

        # Dinamik yerleştirme (örneğin, {{plot(...)}} gibi ifadeleri işleme)
        signal_text = data.get("signal", "")
        # Örnek: Matisay değeri -25 ile değiştiriliyor (Bu kısım isteğe bağlı)
        signal_text = re.sub(r"{{plot\(\"matisay trend direction\"\)}}", "-25", signal_text)
        data["signal"] = signal_text

        # Zaman damgası ekle
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
        except IOError as e:
             print(f"❌ Sinyal dosyasına yazılamadı ({SIGNALS_FILE}): {e}")
             # Belki burada bir alternatif loglama veya bildirim yapılabilir
             send_telegram_message(f"⚠️ Uyarı: Sinyal dosyasına yazılamadı: {e}")


        symbol = data.get("symbol", "Bilinmiyor")
        exchange = data.get("exchange", "Bilinmiyor")
        signal_msg = data.get("signal", "İçerik Yok")

        # Borsa isimlerini daha okunabilir hale getir
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ") # Diğer borsalar için de eklenebilir

        # Mesajı hazırla (MarkdownV2 formatında)
        # Özel karakterleri burada manuel eklemiyoruz, send_telegram_message halledecek.
        message = f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({exchange_display})\n📍 _{signal_msg}_"
        send_telegram_message(message)

        return "ok", 200
    except Exception as e:
        print(f"❌ /signal endpoint hatası: {e}")
        # Hata durumunda Telegram'a bilgi gönderilebilir
        try:
            send_telegram_message(f"❌ `/signal` endpointinde hata oluştu: {str(e)}")
        except Exception as telegram_err:
            print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        return str(e), 500


# --- Mevcut Fonksiyonlar (Değişiklik Yok) ---
def parse_signal_line(line):
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        print(f"JSON parse hatası: {line.strip()}")
        return None # Hatalı satırı atla

def load_analiz_json():
    try:
        with open(ANALIZ_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Uyarı: {ANALIZ_FILE} dosyası bulunamadı.")
        return {}
    except json.JSONDecodeError:
        print(f"Hata: {ANALIZ_FILE} dosyası geçerli bir JSON formatında değil.")
        return {}

def generate_analiz_response(tickers):
    analiz_verileri = load_analiz_json()
    analiz_listesi = []

    for ticker in tickers:
        analiz = analiz_verileri.get(ticker.upper())
        if analiz:
            puan = analiz.get("puan", 0)
            # Detayların None olup olmadığını kontrol et
            detaylar_list = analiz.get("detaylar")
            detaylar = "\n".join(detaylar_list) if detaylar_list else "Detay bulunamadı."
            yorum = analiz.get("yorum", "Yorum bulunamadı.")
            analiz_listesi.append({
                "ticker": ticker.upper(),
                "puan": puan,
                "detaylar": detaylar,
                "yorum": yorum
            })
        else:
            analiz_listesi.append({
                "ticker": ticker.upper(),
                "puan": None,
                "detaylar": None,
                "yorum": f"❌ _{ticker.upper()}_ için analiz bulunamadı." # Markdown için _ eklendi
            })

    analiz_listesi.sort(key=lambda x: (x["puan"] is not None, x["puan"]), reverse=True)

    response_lines = []
    for analiz in analiz_listesi:
        if analiz["puan"] is not None:
            # MarkdownV2 formatı
            response_lines.append(
                f"📊 *{analiz['ticker']} Analiz Sonuçları (Puan: {analiz['puan']})*:\n`{analiz['detaylar']}`\n\n_{analiz['yorum']}_"
            )
        else:
            response_lines.append(analiz["yorum"])

    return "\n\n".join(response_lines)

# --- /bist_analiz için Yeni Fonksiyonlar ---

# YENİ EKLENDİ: analiz_sonuclari.json dosyasını yüklemek için fonksiyon
def load_bist_analiz_json():
    """analiz_sonuclari.json dosyasını yükler."""
    try:
        with open(ANALIZ_SONUCLARI_FILE, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"Uyarı: {ANALIZ_SONUCLARI_FILE} dosyası bulunamadı.")
        return {}
    except json.JSONDecodeError:
        print(f"Hata: {ANALIZ_SONUCLARI_FILE} dosyası geçerli bir JSON formatında değil.")
        return {}
    except Exception as e:
        print(f"Beklenmedik Hata ({ANALIZ_SONUCLARI_FILE} okuma): {e}")
        return {}

# YENİ EKLENDİ: /bist_analiz komutu için yanıt oluşturan fonksiyon
def generate_bist_analiz_response(tickers):
    """
    Verilen hisse listesi için analiz_sonuclari.json'dan veri çeker ve formatlar.
    """
    all_analiz_data = load_bist_analiz_json()
    response_lines = []

    if not all_analiz_data:
         return f"⚠️ Detaylı analiz verileri (`{ANALIZ_SONUCLARI_FILE}`) yüklenemedi veya boş."

    for ticker in tickers:
        analiz_data = all_analiz_data.get(ticker.upper()) # JSON anahtarlarının büyük harf olduğunu varsayıyoruz

        if analiz_data:
            symbol = analiz_data.get("symbol", ticker.upper()) # JSON'da yoksa ticker'ı kullan
            score = analiz_data.get("score", "N/A")
            classification = analiz_data.get("classification", "Belirtilmemiş")
            comments = analiz_data.get("comments", [])

            # Yorumları formatla (başına - ekleyerek)
            formatted_comments = "\n".join([f"- {comment}" for comment in comments])
            if not formatted_comments:
                formatted_comments = "_Yorum bulunamadı_" # Yorum yoksa belirt

            # MarkdownV2 formatında mesaj oluştur
            # Dikkat: * ve _ gibi karakterler send_telegram_message tarafından escape edilecek.
            # Bu yüzden burada düz metin olarak ekliyoruz.
            response_lines.append(
                f"📊 *{symbol}* Detaylı Analiz:\n\n"
                f"📈 *Puan:* {score}\n"
                f"🏅 *Sınıflandırma:* {classification}\n\n"
                f"📝 *Öne Çıkanlar:*\n{formatted_comments}"
            )
        else:
            # MarkdownV2 için _ eklendi
            response_lines.append(f"❌ _{ticker.upper()}_ için detaylı analiz bulunamadı.")

    return "\n\n".join(response_lines)


# --- Telegram Webhook (GÜNCELLENDİ) ---
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    update = request.json
    if not update:
        print("Boş JSON verisi alındı.")
        return "ok", 200

    message = update.get("message")
    if not message:
        # Mesaj olmayan güncellemeleri (kanal postları, düzenlemeler vb.) şimdilik atla
        print("Gelen güncelleme bir mesaj değil, atlanıyor.")
        return "ok", 200

    text = message.get("text", "").strip()
    chat_id = message.get("chat", {}).get("id")

    # Gelen chat_id'yi global CHAT_ID ile karşılaştırabiliriz (isteğe bağlı güvenlik)
    # if str(chat_id) != CHAT_ID:
    #     print(f"Uyarı: Mesaj beklenen sohbetten gelmedi ({chat_id}). İşlenmeyecek.")
    #     return "ok", 200 # Yetkisiz sohbetten gelen komutları engelle

    if not text:
        print("Boş mesaj içeriği alındı.")
        return "ok", 200

    print(f">>> Mesaj alındı (Chat ID: {chat_id}): {text}")

    # Komutları işle
    if text.startswith("/ozet"):
        print(">>> /ozet komutu işleniyor...")
        keyword = text[6:].strip().lower() if len(text) > 6 else None
        allowed_keywords = ["bats", "nasdaq", "bist_dly", "binance", "bist"] # İzin verilen anahtar kelimeler
        summary = "📊 Varsayılan özet oluşturuluyor..."
        if keyword:
            if keyword in allowed_keywords:
                print(f">>> /ozet için anahtar kelime: {keyword}")
                summary = generate_summary(keyword)
            else:
                 summary = f"⚠️ Geçersiz anahtar kelime: `{keyword}`. İzin verilenler: {', '.join(allowed_keywords)}"
                 print(f"Geçersiz özet anahtar kelimesi: {keyword}")
        else:
            summary = generate_summary() # Varsayılan tüm sinyaller için özet

        send_telegram_message(summary)

    elif text.startswith("/analiz"): # Mevcut /analiz komutu
        print(">>> /analiz komutu işleniyor...")
        tickers_input = text[8:].strip()
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
        if not tickers:
            send_telegram_message("Lütfen bir veya daha fazla hisse kodu belirtin. Örnek: `/analiz AAPL,MSFT,AMD`")
        else:
            print(f"Analiz istenen hisseler: {tickers}")
            response = generate_analiz_response(tickers)
            send_telegram_message(response)

    # YENİ EKLENDİ: /bist_analiz komutu işleyici
    elif text.startswith("/bist_analiz"):
        print(">>> /bist_analiz komutu işleniyor...")
        tickers_input = text[13:].strip() # "/bist_analiz " kısmını atla (13 karakter)
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]

        if not tickers:
            send_telegram_message("Lütfen bir veya daha fazla hisse kodu belirtin. Örnek: `/bist_analiz MIATK,THYAO`")
        else:
            print(f"Detaylı analiz istenen hisseler: {tickers}")
            # Yeni fonksiyonu çağır
            response = generate_bist_analiz_response(tickers)
            send_telegram_message(response)

    # Başka komutlar buraya eklenebilir (elif ...)
    # else:
        # Bilinmeyen komutlara yanıt vermek isterseniz:
        # print(f"Bilinmeyen komut veya metin: {text}")
        # send_telegram_message("❓ Anlamadım. Kullanılabilir komutlar: `/ozet [bist/nasdaq/...]`, `/analiz HISSE1,HISSE2`, `/bist_analiz HISSE1,HISSE2`")

    return "ok", 200


# --- Mevcut Diğer Fonksiyonlar (generate_summary, clear_signals, clear_signals_daily) ---
# (generate_summary fonksiyonunda küçük iyileştirmeler/düzeltmeler yapıldı)
def generate_summary(keyword=None):
    if not os.path.exists(SIGNALS_FILE):
        return "📊 Henüz hiç sinyal kaydedilmedi."

    lines = []
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except IOError as e:
        print(f"❌ Sinyal dosyası okunamadı ({SIGNALS_FILE}): {e}")
        return f"⚠️ Sinyal dosyası (`{SIGNALS_FILE}`) okunurken bir hata oluştu."

    if not lines:
        return "📊 Sinyal dosyasında kayıtlı veri bulunamadı."

    summary = {
        "güçlü": set(),
        "kairi_-30": set(),
        "kairi_-20": set(),
        "mükemmel_alış": set(),
        "alış_sayımı": set(),
        "mükemmel_satış": set(),
        "satış_sayımı": set(),
        "matisay_-25": set()
    }

    parsed_lines = [parse_signal_line(line) for line in lines if line.strip()] # Boş satırları atla
    parsed_lines = [s for s in parsed_lines if s] # parse_signal_line'dan None dönenleri filtrele

    # Anahtar kelimelere göre filtreleme yap
    keyword_map = {
        "bist": "bist_dly",
        "nasdaq": "bats",
        "binance": "binance" # Binance için exchange adı 'binance' ise
    }
    if keyword:
        keyword_lower = keyword.lower()
        # Hem doğrudan eşleşme hem de map üzerinden eşleşme kontrolü
        keyword_mapped = keyword_map.get(keyword_lower, keyword_lower)
        print(f"Özet filtreleniyor: '{keyword_mapped}' içerenler")
        filtered_lines = []
        for s in parsed_lines:
            exchange_lower = s.get("exchange", "").lower()
            if keyword_mapped in exchange_lower:
                 filtered_lines.append(s)
        parsed_lines = filtered_lines # Filtrelenmiş liste ile devam et
        if not parsed_lines:
             return f"📊 '{keyword}' anahtar kelimesi için sinyal bulunamadı."


    print(f"Özet için işlenecek sinyal sayısı: {len(parsed_lines)}")

    # Sinyalleri kategorize et
    for signal_data in parsed_lines:
        symbol = signal_data.get("symbol", "Bilinmiyor")
        exchange = signal_data.get("exchange", "Bilinmiyor")
        signal = signal_data.get("signal", "")
        # Borsa adını güzelleştir
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        key = f"{symbol} ({exchange_display})" # Gösterilecek anahtar

        signal_lower = signal.lower() # Küçük harfe çevirerek kontrol yap

        # KAIRI Sinyalleri
        if "kairi" in signal_lower:
            try:
                # Sayıyı bul (pozitif, negatif, ondalıklı)
                kairi_match = re.search(r"kairi\s*([-+]?\d*\.?\d+)", signal_lower)
                if kairi_match:
                    kairi_value = round(float(kairi_match.group(1)), 2)
                    kairi_entry = f"{key}: KAIRI {kairi_value}"
                    if kairi_value <= -30:
                        summary["kairi_-30"].add(kairi_entry)
                    elif kairi_value <= -20:
                        summary["kairi_-20"].add(kairi_entry)

                    # Güçlü eşleşme kontrolü (KAIRI ve Alış Sinyali)
                    for other in parsed_lines:
                        if (other.get("symbol") == symbol and
                            other.get("exchange") == exchange and # Aynı borsa olduğundan emin ol
                            re.search(r"(mükemmel alış|alış sayımı)", other.get("signal", "").lower())):
                            summary["güçlü"].add(f"✅ {key} - KAIRI: {kairi_value} & Alış Sinyali")
                            break # Bir eşleşme yeterli
            except ValueError:
                print(f"KAIRI değeri ayrıştırılamadı: {signal}")
                continue # Hatalı sinyalde sonraki adıma geç
            except Exception as e:
                 print(f"KAIRI işlenirken hata: {e} - Sinyal: {signal}")
                 continue

        # Diğer Sinyal Türleri
        elif re.search(r"mükemmel alış", signal_lower):
            summary["mükemmel_alış"].add(key)
        elif re.search(r"alış sayımı", signal_lower):
            summary["alış_sayımı"].add(key)
        elif re.search(r"mükemmel satış", signal_lower):
            summary["mükemmel_satış"].add(key)
        elif re.search(r"satış sayımı", signal_lower):
            summary["satış_sayımı"].add(key)

        # Matisay Sinyalleri
        elif "matisay" in signal_lower:
            try:
                matisay_match = re.search(r"matisay\s*([-+]?\d*\.?\d+)", signal_lower)
                if matisay_match:
                    matisay_value = round(float(matisay_match.group(1)), 2)
                    if matisay_value < -25: # -25'ten KÜÇÜK olanlar
                        summary["matisay_-25"].add(f"{key}: Matisay {matisay_value}")
            except ValueError:
                print(f"Matisay değeri ayrıştırılamadı: {signal}")
                continue
            except Exception as e:
                 print(f"Matisay işlenirken hata: {e} - Sinyal: {signal}")
                 continue

    # Özeti oluştur
    msg_parts = []
    # Her kategori için başlık ve listeyi ekle (eğer boş değilse)
    # Başlıkları kalın (bold) yapalım
    if summary["güçlü"]:
        msg_parts.append("*📊 GÜÇLÜ EŞLEŞEN SİNYALLER:*\n" + "\n".join(sorted(list(summary["güçlü"]))))
    if summary["kairi_-30"]:
        msg_parts.append("*🔴 KAIRI ≤ -30:*\n" + "\n".join(sorted(list(summary["kairi_-30"]))))
    if summary["kairi_-20"]:
        msg_parts.append("*🟠 KAIRI ≤ -20 (ama > -30):*\n" + "\n".join(sorted(list(summary["kairi_-20"]))))
    if summary["matisay_-25"]:
        msg_parts.append("*🟣 Matisay < -25:*\n" + "\n".join(sorted(list(summary["matisay_-25"])))) # Matisay eklendi
    if summary["mükemmel_alış"]:
        msg_parts.append("*🟢 Mükemmel Alış:*\n" + "\n".join(sorted(list(summary["mükemmel_alış"]))))
    if summary["alış_sayımı"]:
        msg_parts.append("*📈 Alış Sayımı Tamamlananlar:*\n" + "\n".join(sorted(list(summary["alış_sayımı"]))))
    if summary["mükemmel_satış"]:
        msg_parts.append("*🔵 Mükemmel Satış:*\n" + "\n".join(sorted(list(summary["mükemmel_satış"]))))
    if summary["satış_sayımı"]:
        msg_parts.append("*📉 Satış Sayımı Tamamlananlar:*\n" + "\n".join(sorted(list(summary["satış_sayımı"]))))


    # Eğer hiçbir kategori dolu değilse, uygun bir mesaj döndür
    if not msg_parts:
        filter_text = f" '{keyword}' filtresi ile" if keyword else ""
        return f"📊 Gösterilecek uygun sinyal bulunamadı{filter_text}."

    # Bölümleri birleştir
    final_summary = "\n\n".join(msg_parts)
    print("Oluşturulan Özet:", final_summary[:200] + "...") # Özetin başını logla
    return final_summary


@app.route("/clear_signals", methods=["POST"]) # Bu endpoint'e dışarıdan erişim kısıtlanmalı
def clear_signals_endpoint():
    # İsteğe bağlı: Sadece belirli IP'lerden veya bir token ile erişime izin verilebilir
    print(">>> /clear_signals endpoint tetiklendi (Manuel)")
    try:
        clear_signals()
        send_telegram_message("📁 `signals.json` dosyası manuel olarak temizlendi.")
        return "📁 signals.json dosyası temizlendi!", 200
    except Exception as e:
        print(f"❌ Manuel sinyal temizleme hatası: {e}")
        send_telegram_message(f"❌ `signals.json` temizlenirken hata oluştu: {str(e)}")
        return str(e), 500


def clear_signals():
    """signals.json dosyasının içeriğini temizler."""
    try:
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                f.write("") # Dosyayı boşalt
            print(f"📁 {SIGNALS_FILE} dosyası başarıyla temizlendi!")
        else:
            print(f"ℹ️ {SIGNALS_FILE} dosyası bulunamadı, temizleme işlemi atlandı.")
    except IOError as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken G/Ç hatası: {e}")
        # Hata durumunda Telegram'a bildirim gönderilebilir
        send_telegram_message(f"⚠️ Otomatik temizlik hatası: `{SIGNALS_FILE}` temizlenemedi - {e}")
    except Exception as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken beklenmedik hata: {e}")
        send_telegram_message(f"⚠️ Otomatik temizlik hatası (Genel): `{SIGNALS_FILE}` temizlenemedi - {e}")


def clear_signals_daily():
    """Her gün 23:59'da signals.json dosyasını temizler."""
    already_cleared_today = False
    while True:
        try:
            # Saat dilimini doğru ayarladığınızdan emin olun
            tz = pytz.timezone("Europe/Istanbul")
            now = datetime.now(tz)

            # Her gün 23:59'da temizle
            if now.hour == 23 and now.minute == 59:
                if not already_cleared_today:
                    print(f"⏰ Zamanı geldi ({now.strftime('%H:%M')}), {SIGNALS_FILE} temizleniyor...")
                    clear_signals()
                    # Telegram'a bildirim gönder (isteğe bağlı)
                    try:
                         send_telegram_message(f"🧹 Günlük otomatik temizlik yapıldı (`{SIGNALS_FILE}`).")
                    except Exception as tel_err:
                         print(f"Temizlik bildirimi gönderilemedi: {tel_err}")

                    already_cleared_today = True # Bugün için temizlendi olarak işaretle
                    # Bir sonraki kontrol için 65 saniye bekle (00:00'ı geçmek için)
                    time.sleep(65)
                    continue # Döngünün başına dön
            else:
                # Eğer saat 23:59 değilse, temizlendi bayrağını sıfırla
                if already_cleared_today:
                     print("Yeni güne geçildi, temizlendi bayrağı sıfırlandı.")
                     already_cleared_today = False

            # Bir sonraki kontrol için bekleme süresi (örneğin 30 saniye)
            time.sleep(30)

        except Exception as e:
            print(f"❌ clear_signals_daily döngüsünde hata: {e}")
            # Hata durumunda biraz daha uzun bekle
            time.sleep(60)


# Arka plan temizlik görevini başlat
# daemon=True ana program bittiğinde thread'in de bitmesini sağlar
threading.Thread(target=clear_signals_daily, daemon=True).start()
print("🕒 Günlük sinyal temizleme görevi başlatıldı.")

if __name__ == "__main__":
    print("🚀 Flask uygulaması başlatılıyor...")
    # Geliştirme için debug=True kullanılabilir, ancak canlı ortamda False olmalı.
    # Debug modunda kod değiştiğinde sunucu otomatik yeniden başlar.
    # app.run(host="0.0.0.0", port=5000, debug=True)
    app.run(host="0.0.0.0", port=5000) # Canlı ortam için debug=False (varsayılan)
