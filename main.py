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

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# .env dosyasından değerleri al
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# DİKKAT: Bu yolu kendi sisteminize göre ayarlayın veya daha göreceli bir yol kullanın.
# Örnek: SIGNALS_FILE = os.path.join(os.path.dirname(__file__), "signals.json")
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json") # .env'den veya varsayılan
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
ANALIZ_SONUCLARI_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")

def escape_markdown_v2(text):
    """
    Telegram MarkdownV2 için özel karakterleri kaçırır.
    Not: Bu fonksiyon *, _, ~, ` gibi formatlama karakterlerini de kaçıracaktır.
    Eğer mesaj içinde manuel formatlama (örn. *kalın*) yapmak istiyorsanız,
    bu fonksiyonu çağırmadan önce bu formatlamayı yapmanız ve kaçırılmamasını
    sağlamanız gerekir, ya da bu fonksiyonu daha seçici hale getirmeniz gerekir.
    Şu anki haliyle, send_telegram_message içinde çağrıldığı için tüm özel karakterler kaçırılır.
    """
    # Kaçırılacak karakterler listesi (formatlama dahil)
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def send_telegram_message(message):
    """Telegram'a mesaj gönderir, MarkdownV2 kaçırma işlemi yapar ve uzun mesajları böler."""
    # Mesajı Telegram'a göndermeden ÖNCE MarkdownV2 karakterlerini kaçır
    # DİKKAT: Bu işlem, mesaj içinde kasıtlı olarak kullanılan *bold* gibi formatlamaları da bozacaktır.
    # Eğer manuel formatlama lazımsa, escape_markdown_v2 fonksiyonu düzenlenmeli
    # veya mesaj parçaları ayrı ayrı ele alınmalıdır.
    # Şimdilik, tüm metin kaçırılıyor. Emojiler etkilenmez.
    escaped_message = escape_markdown_v2(message)

    max_length = 4096
    for i in range(0, len(escaped_message), max_length):
        chunk = escaped_message[i:i+max_length]
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        data = {
            "chat_id": CHAT_ID,
            "text": chunk,
            "parse_mode": "MarkdownV2"
        }
        try:
            r = requests.post(url, json=data, timeout=20) # Timeout artırıldı
            r.raise_for_status() # HTTP hatalarını kontrol et
            print(f"✅ Telegram yanıtı: {r.status_code}")
            # print("Giden Mesaj Chunk (Escaped):", chunk) # Hata ayıklama için
            # print("Telegram Yanıt Detayı:", r.text) # Hata ayıklama için
        except requests.exceptions.Timeout:
            print(f"❌ Telegram API zaman aşımına uğradı.")
        except requests.exceptions.HTTPError as http_err:
            print(f"❌ Telegram HTTP Hatası: {http_err} - Yanıt: {r.text}")
            print(f"❌ Gönderilemeyen mesaj (orijinal): {message[i:i+max_length]}") # Orijinali logla
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi (RequestException): {e}")
            print(f"❌ Gönderilemeyen mesaj (orijinal): {message[i:i+max_length]}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")
            print(f"❌ Gönderilemeyen mesaj (orijinal): {message[i:i+max_length]}")


@app.route("/signal", methods=["POST"])
def receive_signal():
    try:
        print(">>> /signal endpoint tetiklendi")
        content_type = request.headers.get('Content-Type')

        if content_type == 'application/json':
            data = request.get_json()
            if not isinstance(data, dict):
                 print(f"❌ Hatalı JSON formatı: {data}")
                 return "Invalid JSON format", 400
        elif content_type == 'text/plain':
             raw = request.data.decode("utf-8").strip()
             print(f"Gelen ham text sinyali: {raw}")
             # Esnek regex: Sembol (Opsiyonel Borsa) - Sinyal Metni
             # Örnekler: "AAPL (NASDAQ) - Mükemmel Alış", "BTCUSDT - KAIRI -25", "Sadece sinyal metni"
             match = re.match(r"^(.*?)(?:\s+\((.*?)\))?\s*-\s*(.*)$", raw)
             symbol, exchange, signal = "Bilinmiyor", "Bilinmiyor", raw # Varsayılanlar

             if match:
                 symbol = match.group(1).strip() if match.group(1) else "Bilinmiyor"
                 exchange = match.group(2).strip() if match.group(2) else "Bilinmiyor"
                 signal = match.group(3).strip() if match.group(3) else "İçerik Yok"
                 print(f"Ayrıştırılan: Sembol='{symbol}', Borsa='{exchange}', Sinyal='{signal}'")
             else:
                 # Eğer format tam eşleşmezse, ham veriyi sinyal olarak ata
                 print(f"Format ayrıştırılamadı, ham veri sinyal olarak kullanılıyor: {raw}")
                 signal = raw # Tüm metni sinyal olarak al

             data = {
                 "symbol": symbol,
                 "exchange": exchange,
                 "signal": signal
             }
        else:
            print(f"❌ Desteklenmeyen Content-Type: {content_type}")
            # Belki ham veriyi yine de işlemeye çalışabiliriz? Şimdilik hata verelim.
            raw_data = request.data.decode("utf-8", errors='ignore') # Hataları görmezden gelerek decode etmeyi dene
            print(f"Alınan ham veri: {raw_data[:500]}...") # Verinin başını logla
            send_telegram_message(f"⚠️ Desteklenmeyen formatta sinyal alındı ({content_type}). Ham veri loglandı.")
            return f"Unsupported Content-Type: {content_type}", 415


        # Yer tutucuları işle (örnek: {{plot...}})
        signal_text = data.get("signal", "")
        # Bu kısım dinamik olarak yer tutucuları değiştirmek için kullanılabilir
        # Örnek: signal_text = re.sub(r"{{plot\(\"matisay trend direction\"\)}}", "-25", signal_text)
        data["signal"] = signal_text # Güncellenmiş sinyali veriye geri yaz

        # Zaman damgası ekle (UTC veya belirli bir timezone)
        # tz = pytz.timezone("Europe/Istanbul")
        # data["timestamp"] = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z%z")
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S") # Sunucu zamanı

        # Sinyali dosyaya ekle
        try:
            # Dosya yolunun var olduğundan emin ol
            os.makedirs(os.path.dirname(SIGNALS_FILE), exist_ok=True)
            with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
                # ensure_ascii=False Türkçe karakterlerin doğru yazılmasını sağlar
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
            print(f"✅ Sinyal dosyaya yazıldı: {SIGNALS_FILE}")
        except IOError as e:
             print(f"❌ Sinyal dosyasına yazılamadı ({SIGNALS_FILE}): {e}")
             send_telegram_message(f"⚠️ Uyarı: Sinyal dosyasına yazılamadı: {e}")
        except Exception as e:
             print(f"❌ Sinyal dosyasına yazarken beklenmedik hata: {e}")
             send_telegram_message(f"⚠️ Uyarı: Sinyal dosyasına yazarken hata: {e}")


        # Telegram mesajı için verileri al
        symbol = data.get("symbol", "Bilinmiyor")
        exchange = data.get("exchange", "Bilinmiyor")
        signal_msg = data.get("signal", "İçerik Yok")

        # Borsa isimlerini daha okunabilir hale getir
        exchange_display_map = {
            "BIST_DLY": "BIST",
            "BATS": "NASDAQ",
            "BINANCE": "Binance",
            # Diğer borsalar eklenebilir
        }
        exchange_display = exchange_display_map.get(exchange.upper(), exchange) # Büyük/küçük harf duyarsız eşleşme

        # Mesajı hazırla (MarkdownV2 formatı için karakterler send_telegram_message'da kaçırılacak)
        # Bu yüzden burada * veya _ kullanmıyoruz. Emojilerle görsel ayrım sağlıyoruz.
        message = f"📡 Yeni Sinyal Geldi:\n\n" \
                  f"🏷️ Sembol: {symbol}\n" \
                  f"🏦 Borsa: {exchange_display}\n" \
                  f"💬 Sinyal: {signal_msg}"

        send_telegram_message(message)

        return "ok", 200
    except json.JSONDecodeError as json_err:
        print(f"❌ /signal JSON parse hatası: {json_err}")
        print(f"Gelen Ham Veri: {request.data.decode('utf-8', errors='ignore')}")
        return f"Invalid JSON received: {json_err}", 400
    except Exception as e:
        print(f"❌ /signal endpoint genel hatası: {e}")
        # Hata detayını loglamak önemli
        import traceback
        print(traceback.format_exc())
        try:
            # Hata mesajını Telegram'a gönderirken escape etmeyi unutma
            error_message = f"❌ `/signal` endpointinde hata oluştu:\n{str(e)}"
            send_telegram_message(error_message)
        except Exception as telegram_err:
            print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        return f"Internal Server Error: {str(e)}", 500


# --- Mevcut Fonksiyonlar (Değişiklik Yok veya Küçük İyileştirmeler) ---
def parse_signal_line(line):
    """Bir satır JSON metnini ayrıştırır, hata durumunda None döner."""
    try:
        # Satır başı/sonundaki boşlukları temizle
        stripped_line = line.strip()
        if not stripped_line: # Boş satırsa None dön
            return None
        return json.loads(stripped_line)
    except json.JSONDecodeError:
        print(f"⚠️ JSON parse hatası (satır atlanıyor): {line.strip()}")
        return None # Hatalı satırı atla

def load_json_file(filepath):
    """Genel JSON dosyası yükleme fonksiyonu."""
    try:
        # Dosya yolunun var olduğundan emin ol
        if not os.path.exists(filepath):
             print(f"Uyarı: {filepath} dosyası bulunamadı.")
             return None # veya {} dönebiliriz
        # Dosya boş mu kontrol et
        if os.path.getsize(filepath) == 0:
            print(f"Uyarı: {filepath} dosyası boş.")
            return {}

        with open(filepath, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError: # Bu aslında üstteki exists kontrolü ile gereksizleşti ama kalsın
        print(f"Uyarı: {filepath} dosyası bulunamadı.")
        return {}
    except json.JSONDecodeError as e:
        print(f"❌ Hata: {filepath} dosyası geçerli bir JSON formatında değil. Hata: {e}")
        # Hatanın olduğu satırı/konumu yazdırmak faydalı olabilir ama json modülü bunu doğrudan vermez
        # Belki dosyanın başını loglayabiliriz
        try:
             with open(filepath, "r", encoding="utf-8") as f_err:
                 print(f"Dosyanın başı: {f_err.read(100)}...")
        except Exception:
             pass # Okuma hatası olursa görmezden gel
        return {}
    except IOError as e:
        print(f"❌ G/Ç Hatası ({filepath} okuma): {e}")
        return {}
    except Exception as e:
        print(f"❌ Beklenmedik Hata ({filepath} okuma): {e}")
        return {}

# Analiz JSON yükleme (genel fonksiyonu kullanır)
def load_analiz_json():
    data = load_json_file(ANALIZ_FILE)
    return data if data is not None else {} # None yerine boş dict dön

# Bist Analiz JSON yükleme (genel fonksiyonu kullanır)
def load_bist_analiz_json():
    data = load_json_file(ANALIZ_SONUCLARI_FILE)
    return data if data is not None else {} # None yerine boş dict dön

# /analiz komutu yanıtı (Markdown kaçırma nedeniyle * kaldırıldı)
def generate_analiz_response(tickers):
    analiz_verileri = load_analiz_json()
    analiz_listesi = []

    if not analiz_verileri:
         # Dosya adı escape edilmeli mi? Şimdilik etmeyelim.
         return f"⚠️ Analiz verileri (`{os.path.basename(ANALIZ_FILE)}`) yüklenemedi veya boş."

    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        # JSON anahtarlarının da büyük harf olduğunu varsayıyoruz
        analiz = analiz_verileri.get(ticker_upper)
        if analiz:
            puan = analiz.get("puan", "N/A") # Puan yoksa N/A
            detaylar_list = analiz.get("detaylar")
            # Detayları madde imleriyle formatla
            detaylar = "\n".join([f"- {d}" for d in detaylar_list]) if isinstance(detaylar_list, list) and detaylar_list else "Detay bulunamadı."
            yorum = analiz.get("yorum", "Yorum bulunamadı.")
            analiz_listesi.append({
                "ticker": ticker_upper,
                "puan": puan,
                "detaylar": detaylar,
                "yorum": yorum
            })
        else:
            analiz_listesi.append({
                "ticker": ticker_upper,
                "puan": None, # Bulunamadığını belirtmek için None
                "detaylar": None,
                "yorum": f"❌ {ticker_upper} için analiz bulunamadı." # Hata mesajı
            })

    # Puana göre sırala (puanı olmayanları sona at)
    analiz_listesi.sort(key=lambda x: (x["puan"] == "N/A" or x["puan"] is None, isinstance(x["puan"], (int, float)), -x["puan"] if isinstance(x["puan"], (int, float)) else 0), reverse=False) # Küçük puan->Büyük Puan

    response_lines = []
    for analiz in analiz_listesi:
        if analiz["puan"] is not None:
            # Mesajı Markdown kaçırmasına uygun hale getir (manuel * yok)
            response_lines.append(
                f"📊 {analiz['ticker']} Analiz:\n" # Başlık
                f"⭐ Puan: {analiz['puan']}\n"      # Puan
                f"📋 Detaylar:\n{analiz['detaylar']}\n" # Detaylar
                f"💡 Yorum: {analiz['yorum']}"      # Yorum
            )
        else:
            response_lines.append(analiz["yorum"]) # Sadece hata mesajı

    return "\n\n".join(response_lines)


# /bist_analiz komutu yanıtı (GÜNCELLENDİ - Emojiler eklendi, Markdown * kaldırıldı)
def generate_bist_analiz_response(tickers):
    """
    Verilen hisse listesi için analiz_sonuclari.json'dan veri çeker ve formatlar.
    """
    all_analiz_data = load_bist_analiz_json()
    response_lines = []

    if not all_analiz_data:
         # Dosya adı escape edilmeli mi? Şimdilik etmeyelim.
         return f"⚠️ Detaylı analiz verileri (`{os.path.basename(ANALIZ_SONUCLARI_FILE)}`) yüklenemedi veya boş."

    for ticker in tickers:
        # JSON anahtarlarının büyük harf olduğunu varsayalım
        analiz_data = all_analiz_data.get(ticker.strip().upper())

        if analiz_data:
            symbol = analiz_data.get("symbol", ticker.strip().upper()) # JSON'da yoksa ticker'ı kullan
            score = analiz_data.get("score", "N/A") # Skor yoksa N/A
            classification = analiz_data.get("classification", "Belirtilmemiş")
            comments = analiz_data.get("comments", [])

            # Yorumları madde imleriyle formatla (başına - veya emoji)
            if comments and isinstance(comments, list):
                 # formatted_comments = "\n".join([f"- {comment}" for comment in comments])
                 formatted_comments = "\n".join([f"▫️ {comment}" for comment in comments]) # Alternatif emoji
            else:
                formatted_comments = "Yorum bulunamadı." # Yorum yoksa veya format yanlışsa

            # MarkdownV2 kaçırması nedeniyle manuel '*' formatlaması KULLANILMIYOR.
            # Görsel ayrım için emojiler kullanılıyor.
            response_lines.append(
                f" BİST Detaylı Analiz\n\n" # Ana Başlık
                f"🏷️ Sembol: {symbol}\n"          # Emoji: Etiket
                f"📈 Puan: {score}\n"             # Emoji: Artan grafik
                f"🏅 Sınıflandırma: {classification}\n\n" # Emoji: Madalya
                f"📝 Öne Çıkanlar:\n{formatted_comments}" # Emoji: Not defteri
            )
        else:
            # Hata mesajı (Markdown kaçırmasına uygun, manuel * yok)
            response_lines.append(f"❌ {ticker.strip().upper()} için detaylı analiz bulunamadı.")

    return "\n\n".join(response_lines)


# --- Telegram Webhook (GÜNCELLENDİ) ---
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    print(">>> /telegram endpoint tetiklendi")
    try:
        update = request.json
        if not update:
            print("Boş JSON verisi alındı.")
            return "ok", 200

        # Mesaj veya düzenlenmiş mesajı kontrol et
        message = update.get("message") or update.get("edited_message")
        if not message:
            # Kanal postlarını veya diğer güncellemeleri şimdilik atla
            if update.get("channel_post"):
                 print("Kanal postu alındı, işlenmiyor.")
            elif update.get("callback_query"):
                 print("Callback query alındı, işlenmiyor.")
            else:
                 print("Gelen güncelleme bir mesaj değil veya desteklenmiyor, atlanıyor.")
                 # print(f"Gelen güncelleme detayı: {update}") # Hata ayıklama için
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


        # Gelen chat_id'yi .env'deki CHAT_ID ile karşılaştır (güvenlik)
        # Birden fazla sohbeti desteklemek için bu kontrol kaldırılabilir veya listeye dönüştürülebilir.
        if str(chat_id) != CHAT_ID:
            print(f"⚠️ Uyarı: Mesaj beklenen sohbetten ({CHAT_ID}) gelmedi. Gelen: {chat_id}. İşlenmeyecek.")
            # İsteğe bağlı: Tanımsız sohbetlere yanıt verilebilir.
            # send_telegram_message(f"Üzgünüm, bu sohbet ({chat_id}) için yetkim yok.", target_chat_id=chat_id) # Ayrı fonksiyon gerekebilir
            return "ok", 200 # Yetkisiz sohbetten gelen komutları engelle

        if not text:
            print("Boş mesaj içeriği alındı.")
            return "ok", 200

        print(f">>> Mesaj alındı (Chat: {chat_id}, User: {first_name} [{username}/{user_id}]): {text}")

        # Komutları işle
        response_message = ""
        if text.startswith("/ozet"):
            print(">>> /ozet komutu işleniyor...")
            parts = text.split(maxsplit=1) # Komutu ve argümanı ayır
            keyword = parts[1].lower() if len(parts) > 1 else None # Anahtar kelimeyi al (küçük harf)
            allowed_keywords = ["bats", "nasdaq", "bist_dly", "binance", "bist"] # İzin verilen anahtar kelimeler
            print(f"Anahtar kelime: {keyword}")

            if keyword and keyword not in allowed_keywords:
                 # Geçersiz anahtar kelime için Markdown kaçırma
                 allowed_str = ", ".join([f"`{k}`" for k in allowed_keywords]) # `code` formatı
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{keyword}`. İzin verilenler: {allowed_str}"
                 print(f"Geçersiz özet anahtar kelimesi: {keyword}")
            else:
                 summary = generate_summary(keyword)
                 response_message = summary

        elif text.startswith("/analiz"): # Mevcut /analiz komutu
            print(">>> /analiz komutu işleniyor...")
            tickers_input = text[len("/analiz"):].strip() # "/analiz " kısmını atla
            if not tickers_input:
                 response_message = "Lütfen bir veya daha fazla hisse kodu belirtin. Örnek: `/analiz AAPL, MSFT, AMD`"
            else:
                # Virgül veya boşlukla ayrılmış kodları işle
                tickers = [ticker.strip().upper() for ticker in re.split(r'[,\s]+', tickers_input) if ticker.strip()]
                if not tickers:
                     response_message = "Geçerli bir hisse kodu bulunamadı. Örnek: `/analiz AAPL, MSFT`"
                else:
                    print(f"Analiz istenen hisseler (/analiz): {tickers}")
                    response_message = generate_analiz_response(tickers)

        elif text.startswith("/bist_analiz"): # /bist_analiz komutu
            print(">>> /bist_analiz komutu işleniyor...")
            tickers_input = text[len("/bist_analiz"):].strip() # "/bist_analiz " kısmını atla
            if not tickers_input:
                response_message = "Lütfen bir veya daha fazla BIST hisse kodu belirtin. Örnek: `/bist_analiz MIATK, THYAO`"
            else:
                # Virgül veya boşlukla ayrılmış kodları işle
                tickers = [ticker.strip().upper() for ticker in re.split(r'[,\s]+', tickers_input) if ticker.strip()]
                if not tickers:
                     response_message = "Geçerli bir hisse kodu bulunamadı. Örnek: `/bist_analiz MIATK, THYAO`"
                else:
                    print(f"Detaylı analiz istenen hisseler (/bist_analiz): {tickers}")
                    response_message = generate_bist_analiz_response(tickers) # Yeni fonksiyonu çağır

        elif text.startswith("/start") or text.startswith("/help"):
             print(">>> /start veya /help komutu işleniyor...")
             # Kullanılabilir komutları listeleyin (Markdown kaçırmasına dikkat)
             response_message = "👋 Merhaba! Kullanabileceğiniz komutlar:\n\n" \
                                "• `/ozet` : Tüm borsalardan gelen sinyallerin özetini gösterir.\n" \
                                "• `/ozet [borsa]` : Belirli bir borsa için özet gösterir (Örn: `/ozet bist`, `/ozet nasdaq`).\n" \
                                "• `/analiz [HİSSE1,HİSSE2,...]` : Belirtilen hisseler için temel analiz puanını ve yorumunu gösterir (Örn: `/analiz GOOGL,AAPL`).\n" \
                                "• `/bist_analiz [HİSSE1,HİSSE2,...]` : Belirtilen BIST hisseleri için daha detaylı analizi gösterir (Örn: `/bist_analiz EREGL, TUPRS`).\n" \
                                "• `/help` : Bu yardım mesajını gösterir."


        # Başka komutlar buraya eklenebilir (elif ...)
        else:
            # Bilinmeyen komut veya metin ise (isteğe bağlı)
            # Belki hiçbir şey yapmamak daha iyidir? Veya yardım mesajı önerilebilir.
            print(f"Bilinmeyen komut veya metin alındı: {text}")
            # response_message = f"❓ `{text}` komutunu anlayamadım. Yardım için `/help` yazabilirsiniz."

        # Eğer bir yanıt mesajı oluşturulduysa gönder
        if response_message:
             send_telegram_message(response_message)
        else:
             # Yanıt oluşturulmadıysa (örn. bilinmeyen komut durumu) logla
             print("İşlenecek bilinen bir komut bulunamadı, yanıt gönderilmedi.")


        return "ok", 200

    except Exception as e:
        print(f"❌ /telegram endpoint genel hatası: {e}")
        import traceback
        print(traceback.format_exc())
        # Hata durumunda genel bir hata mesajı göndermeyi deneyebiliriz
        try:
             error_message = f"🤖 Üzgünüm, isteğinizi işlerken bir hata oluştu. Lütfen daha sonra tekrar deneyin."
             # Hatanın hangi sohbette olduğunu belirtmek için chat_id'yi kullanabiliriz ama
             # chat_id'nin bu scope'ta erişilebilir olduğundan emin olmalıyız.
             # Eğer chat_id yukarıda alındıysa:
             if 'chat_id' in locals() and str(chat_id) == CHAT_ID:
                 send_telegram_message(error_message)
             else:
                 # Hata mesajını admin'e gönderebiliriz (eğer admin chat id'si varsa)
                 # ya da sadece loglamakla yetinebiliriz.
                 print("Hata oluştu ancak hedef sohbet ID'si belirlenemedi veya yetkisiz.")
        except Exception as telegram_err:
             print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        return "Internal Server Error", 500

# --- Mevcut Diğer Fonksiyonlar ---

def generate_summary(keyword=None):
    """
    signals.json dosyasını okur, sinyalleri kategorize eder ve bir özet metni oluşturur.
    İsteğe bağlı olarak anahtar kelimeye göre filtreleme yapar.
    """
    # Dosya yolunun var olup olmadığını ve boş olup olmadığını kontrol et
    if not os.path.exists(SIGNALS_FILE) or os.path.getsize(SIGNALS_FILE) == 0:
        print(f"ℹ️ Sinyal dosyası bulunamadı veya boş: {SIGNALS_FILE}")
        return "📊 Henüz kaydedilmiş sinyal bulunmamaktadır."

    lines = []
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except IOError as e:
        print(f"❌ Sinyal dosyası okunamadı ({SIGNALS_FILE}): {e}")
        return f"⚠️ Sinyal dosyası (`{os.path.basename(SIGNALS_FILE)}`) okunurken bir hata oluştu."
    except Exception as e:
        print(f"❌ Sinyal dosyası okunurken beklenmedik hata: {e}")
        return f"⚠️ Sinyal dosyası okunurken beklenmedik bir hata oluştu."


    if not lines:
        return "📊 Sinyal dosyasında okunacak veri bulunamadı."

    # Sinyal kategorileri için set'ler (tekrarı önler)
    summary = {
        "güçlü": set(),             # KAIRI ve Alış/Satış eşleşmesi
        "kairi_negatif_30": set(),  # KAIRI <= -30
        "kairi_negatif_20": set(),  # -30 < KAIRI <= -20
        "matisay_negatif_25": set(),# Matisay < -25
        "mukemmel_alis": set(),
        "alis_sayimi": set(),
        "mukemmel_satis": set(),
        "satis_sayimi": set(),
        "diger": set()             # Kategorize edilemeyenler (opsiyonel)
    }

    parsed_signals = [parse_signal_line(line) for line in lines]
    # None dönen (parse edilemeyen) veya boş dict olanları filtrele
    valid_signals = [s for s in parsed_signals if isinstance(s, dict) and s]

    print(f"Toplam geçerli sinyal sayısı: {len(valid_signals)}")

    # Anahtar kelime filtreleme (daha sağlam)
    filtered_signals = valid_signals
    if keyword:
        keyword_lower = keyword.lower()
        # Borsa isimleri için eşleme (daha esnek)
        keyword_map = {
            "bist": ["bist", "bist_dly"],
            "nasdaq": ["nasdaq", "bats"],
            "binance": ["binance"]
        }
        # Anahtar kelime hangi listeye uyuyor?
        target_exchanges = []
        for key, values in keyword_map.items():
            if keyword_lower == key:
                target_exchanges.extend(values)
                break
        if not target_exchanges: # Eşleşme bulunamazsa, anahtar kelimeyi doğrudan kullan
            target_exchanges.append(keyword_lower)

        print(f"Özet filtreleniyor: Borsa '{keyword_lower}' (Eşleşenler: {target_exchanges})")

        temp_filtered = []
        for s in valid_signals:
            exchange_lower = s.get("exchange", "").lower()
            # Hedef borsa listesindeki herhangi biriyle eşleşiyor mu?
            if any(ex in exchange_lower for ex in target_exchanges):
                 temp_filtered.append(s)

        filtered_signals = temp_filtered
        if not filtered_signals:
             # Markdown kaçırmaya uygun mesaj
             return f"📊 `{keyword}` anahtar kelimesi için sinyal bulunamadı."

    print(f"Filtre sonrası işlenecek sinyal sayısı: {len(filtered_signals)}")

    # Sinyalleri işle ve kategorize et
    for signal_data in filtered_signals:
        symbol = signal_data.get("symbol", "?")
        exchange = signal_data.get("exchange", "?")
        signal_text = signal_data.get("signal", "").lower() # Küçük harf ile kontrol
        timestamp_str = signal_data.get("timestamp", "") # Zamanı da alalım (opsiyonel)

        # Borsa adını güzelleştir
        exchange_display_map = {"BIST_DLY": "BIST", "BATS": "NASDAQ", "BINANCE": "Binance"}
        exchange_display = exchange_display_map.get(exchange.upper(), exchange)

        # Gösterim formatı: Sembol (Borsa)
        display_key = f"{symbol} ({exchange_display})"

        # KAIRI Sinyalleri
        if "kairi" in signal_text:
            match = re.search(r"kairi\s*=?\s*([-+]?\d*\.?\d+)", signal_text)
            if match:
                try:
                    value = round(float(match.group(1)), 2)
                    kairi_entry = f"{display_key}: KAIRI {value}"
                    if value <= -30:
                        summary["kairi_negatif_30"].add(kairi_entry)
                    elif value <= -20: # -30 < value <= -20
                        summary["kairi_negatif_20"].add(kairi_entry)
                    # else: # Pozitif veya -20'den büyük negatifler (isterseniz ekleyebilirsiniz)
                    #     summary["diger"].add(kairi_entry + " (Diğer KAIRI)")

                    # Güçlü eşleşme kontrolü: Aynı sembol/borsa için başka alış/satış sinyali var mı?
                    # Bu kontrol biraz maliyetli olabilir, optimize edilebilir.
                    # Şimdilik basit kontrol:
                    for other_signal in filtered_signals:
                        if other_signal.get("symbol") == symbol and other_signal.get("exchange") == exchange:
                            other_text = other_signal.get("signal", "").lower()
                            if ("mükemmel alış" in other_text or "alış sayımı" in other_text):
                                summary["güçlü"].add(f"✅ {display_key} (KAIRI {value} & Alış)")
                                break # Bir eşleşme yeterli
                            # Satış için de benzer kontrol eklenebilir
                            # if ("mükemmel satış" in other_text or "satış sayımı" in other_text):
                            #    summary["güçlü"].add(f"❌ {display_key} (KAIRI {value} & Satış)")
                            #    break
                except ValueError:
                    print(f"⚠️ KAIRI değeri float'a çevrilemedi: {match.group(1)} (Sinyal: {signal_text})")
                    summary["diger"].add(f"{display_key}: KAIRI Parse Hatası")
            else:
                 summary["diger"].add(f"{display_key}: KAIRI (Değer Okunamadı)")

        # Matisay Sinyalleri
        elif "matisay" in signal_text:
            match = re.search(r"matisay\s*=?\s*([-+]?\d*\.?\d+)", signal_text)
            if match:
                try:
                    value = round(float(match.group(1)), 2)
                    if value < -25:
                        summary["matisay_negatif_25"].add(f"{display_key}: Matisay {value}")
                    # else: # -25 ve üzeri Matisay (isterseniz ekleyebilirsiniz)
                    #     summary["diger"].add(f"{display_key}: Matisay {value} (Diğer)")
                except ValueError:
                    print(f"⚠️ Matisay değeri float'a çevrilemedi: {match.group(1)} (Sinyal: {signal_text})")
                    summary["diger"].add(f"{display_key}: Matisay Parse Hatası")
            else:
                summary["diger"].add(f"{display_key}: Matisay (Değer Okunamadı)")


        # Diğer Standart Sinyaller
        elif "mükemmel alış" in signal_text:
            summary["mukemmel_alis"].add(display_key)
        elif "alış sayımı" in signal_text:
            summary["alis_sayimi"].add(display_key)
        elif "mükemmel satış" in signal_text:
            summary["mukemmel_satis"].add(display_key)
        elif "satış sayımı" in signal_text:
            summary["satis_sayimi"].add(display_key)

        # Bilinmeyen veya kategorize edilemeyenler
        else:
            # Eğer yukarıdaki hiçbir kategoriye girmediyse buraya düşer.
            # İsterseniz 'diger' kategorisine ekleyebilirsiniz.
            # summary["diger"].add(f"{display_key}: {signal_text[:30]}...") # Sinyalin başını ekle
            pass # Şimdilik görmezden gel


    # Özeti oluştur (Markdown kaçırmasına uygun, manuel * yok)
    msg_parts = []
    summary_title = f"📊 Sinyal Özeti"
    if keyword:
        summary_title += f" ({keyword.upper()})" # Filtre varsa belirt
    msg_parts.append(summary_title)

    # Her kategori için başlık ve listeyi ekle (eğer boş değilse)
    # Başlıkları emoji ile belirtelim
    if summary["güçlü"]:
        msg_parts.append("⭐ GÜÇLÜ EŞLEŞMELER:\n" + "\n".join(sorted(list(summary["güçlü"]))))
    if summary["kairi_negatif_30"]:
        msg_parts.append("🔴 KAIRI ≤ -30:\n" + "\n".join(sorted(list(summary["kairi_negatif_30"]))))
    if summary["kairi_negatif_20"]:
        msg_parts.append("🟠 KAIRI (-30 < X ≤ -20):\n" + "\n".join(sorted(list(summary["kairi_negatif_20"]))))
    if summary["matisay_negatif_25"]:
        msg_parts.append("🟣 MATISAY < -25:\n" + "\n".join(sorted(list(summary["matisay_negatif_25"]))))
    if summary["mukemmel_alis"]:
        msg_parts.append("🟢 MÜKEMMEL ALIŞ:\n" + "\n".join(sorted(list(summary["mukemmel_alis"]))))
    if summary["alis_sayimi"]:
        msg_parts.append("📈 ALIŞ SAYIMI TAMAMLANANLAR:\n" + "\n".join(sorted(list(summary["alis_sayimi"]))))
    if summary["mukemmel_satis"]:
        msg_parts.append("🔵 MÜKEMMEL SATIŞ:\n" + "\n".join(sorted(list(summary["mukemmel_satis"]))))
    if summary["satis_sayimi"]:
        msg_parts.append("📉 SATIŞ SAYIMI TAMAMLANANLAR:\n" + "\n".join(sorted(list(summary["satis_sayimi"]))))
    # if summary["diger"]: # İsterseniz diğerlerini de ekleyebilirsiniz
    #     msg_parts.append("⚙️ DİĞER / KATEGORİZE EDİLEMEYEN:\n" + "\n".join(sorted(list(summary["diger"]))))


    # Eğer başlık dışında hiçbir kategori dolu değilse, uygun bir mesaj döndür
    if len(msg_parts) <= 1: # Sadece başlık varsa
        filter_text = f" (`{keyword}` filtresi ile)" if keyword else ""
        return f"📊 Gösterilecek uygun sinyal bulunamadı{filter_text}."

    # Bölümleri birleştir
    final_summary = "\n\n".join(msg_parts)
    print("Oluşturulan Özetin Başı:", final_summary[:300].replace("\n", " ") + "...") # Özetin başını logla
    return final_summary


@app.route("/clear_signals", methods=["POST"]) # Güvenlik Notu: Bu endpoint'e erişimi kısıtlayın!
def clear_signals_endpoint():
    """Manuel olarak sinyal dosyasını temizlemek için HTTP endpoint'i."""
    # Güvenlik Önlemi Örneği (Basit Token Kontrolü):
    # expected_token = os.getenv("CLEAR_TOKEN")
    # provided_token = request.headers.get("Authorization") # veya ?token= query param
    # if not expected_token or provided_token != f"Bearer {expected_token}":
    #     print("❌ Yetkisiz sinyal temizleme denemesi!")
    #     return "Unauthorized", 401

    print(">>> /clear_signals endpoint tetiklendi (Manuel)")
    try:
        success = clear_signals() # clear_signals artık başarı durumu dönebilir
        if success:
            send_telegram_message(f"📁 `{os.path.basename(SIGNALS_FILE)}` dosyası manuel olarak temizlendi.")
            return f"📁 {os.path.basename(SIGNALS_FILE)} dosyası temizlendi!", 200
        else:
            # Temizleme başarısız olduysa (örn. dosya yok)
            send_telegram_message(f"ℹ️ `{os.path.basename(SIGNALS_FILE)}` dosyası zaten yok veya temizlenemedi (manuel istek).")
            return f"ℹ️ {os.path.basename(SIGNALS_FILE)} dosyası bulunamadı veya temizlenemedi.", 404
    except Exception as e:
        print(f"❌ Manuel sinyal temizleme hatası: {e}")
        import traceback
        print(traceback.format_exc())
        send_telegram_message(f"❌ `{os.path.basename(SIGNALS_FILE)}` temizlenirken hata oluştu: {str(e)}")
        return f"Internal Server Error: {str(e)}", 500


def clear_signals():
    """
    signals.json dosyasının içeriğini temizler.
    Başarılı olursa True, dosya yoksa veya hata olursa False döner.
    """
    try:
        if os.path.exists(SIGNALS_FILE):
            # Dosyayı boşaltmak yerine silip yeniden oluşturmak da bir yöntem olabilir
            # os.remove(SIGNALS_FILE)
            # open(SIGNALS_FILE, 'a').close() # Boş dosya oluştur
            # Veya içeriği boşalt:
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                f.write("") # Dosyayı boşalt
            print(f"📁 {SIGNALS_FILE} dosyası başarıyla temizlendi!")
            return True
        else:
            print(f"ℹ️ {SIGNALS_FILE} dosyası bulunamadı, temizleme işlemi atlandı.")
            return False # Dosya yok, teknik olarak "başarısız" sayılmaz ama temizlenmedi.
    except IOError as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken G/Ç hatası: {e}")
        # Hata durumunda Telegram'a bildirim gönderilebilir (opsiyonel, döngü içinde zaten var)
        # send_telegram_message(f"⚠️ Otomatik temizlik hatası: `{os.path.basename(SIGNALS_FILE)}` temizlenemedi - {e}")
        return False
    except Exception as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken beklenmedik hata: {e}")
        # send_telegram_message(f"⚠️ Otomatik temizlik hatası (Genel): `{os.path.basename(SIGNALS_FILE)}` temizlenemedi - {e}")
        return False


def clear_signals_daily():
    """Her gün belirli bir saatte signals.json dosyasını temizler."""
    already_cleared_today = False
    # Saat dilimini ayarla (Türkiye saati için)
    tz = pytz.timezone("Europe/Istanbul")
    clear_hour = 23 # Temizlik saati (24 saat formatında)
    clear_minute = 59 # Temizlik dakikası

    print(f"🕒 Günlük temizlik görevi ayarlandı: Her gün saat {clear_hour:02d}:{clear_minute:02d} ({tz})")

    while True:
        try:
            now = datetime.now(tz)

            # Hedeflenen temizlik zamanı geldi mi?
            if now.hour == clear_hour and now.minute == clear_minute:
                if not already_cleared_today:
                    print(f"⏰ Zamanı geldi ({now.strftime('%Y-%m-%d %H:%M:%S %Z')}), {os.path.basename(SIGNALS_FILE)} temizleniyor...")
                    success = clear_signals()

                    if success:
                        # Telegram'a bildirim gönder
                        try:
                             send_telegram_message(f"🧹 Günlük otomatik temizlik yapıldı (`{os.path.basename(SIGNALS_FILE)}`).")
                        except Exception as tel_err:
                             print(f"❌ Temizlik bildirimi gönderilemedi: {tel_err}")
                    else:
                         # Temizleme başarısız olduysa (örn. dosya yoktu) bildirim göndermeyebiliriz
                         # veya farklı bir bildirim gönderebiliriz.
                         print(f"ℹ️ Otomatik temizlik: {os.path.basename(SIGNALS_FILE)} zaten yoktu veya temizlenemedi.")


                    already_cleared_today = True # Bugün için temizlendi olarak işaretle
                    # Bir sonraki kontrol için temizlik zamanını geçecek kadar bekle (örn. 65 saniye)
                    print("Temizlik yapıldı, bir sonraki kontrol 65 saniye sonra.")
                    time.sleep(65)
                    continue # Döngünün başına dön
                # else: # Zaten temizlenmişse, bir şey yapma, sadece bekle
                     # print(f"Saat {now.strftime('%H:%M')}, bugün zaten temizlenmişti.") # Çok fazla log üretebilir
                     # time.sleep(30) # Yine de kısa bir süre bekle
                     # continue
            else:
                # Eğer temizlik saati geçtiyse ve bayrak hala True ise, yeni güne geçilmiştir, bayrağı sıfırla
                if already_cleared_today and (now.hour != clear_hour or now.minute != clear_minute):
                     print(f"Yeni güne/periyoda geçildi ({now.strftime('%H:%M')}), temizlendi bayrağı sıfırlandı.")
                     already_cleared_today = False

            # Bir sonraki kontrol için bekleme süresi (saniyede)
            # Daha az kaynak kullanmak için 60 saniye gibi daha uzun aralıklar seçilebilir
            check_interval = 30
            time.sleep(check_interval)

        except Exception as e:
            print(f"❌ clear_signals_daily döngüsünde beklenmedik hata: {e}")
            import traceback
            print(traceback.format_exc())
            # Hata durumunda daha uzun bekle (örn. 5 dakika)
            print("Hata nedeniyle 5 dakika bekleniyor...")
            time.sleep(300)


# --- Uygulama Başlangıcı ---
if __name__ == "__main__":
    print("🚀 Flask uygulaması başlatılıyor...")
    # Arka plan temizlik görevini daemon thread olarak başlat
    # Ana program kapanırsa bu thread de otomatik olarak durur.
    cleanup_thread = threading.Thread(target=clear_signals_daily, daemon=True)
    cleanup_thread.start()
    print("✅ Günlük sinyal temizleme görevi arka planda başlatıldı.")

    # Ortam değişkeninden portu al veya varsayılan kullan
    port = int(os.getenv("PORT", 5000))
    # Geliştirme için debug=True, canlı ortam için debug=False
    debug_mode = os.getenv("FLASK_DEBUG", "False").lower() == "true"

    print(f"🔧 Ayarlar: Port={port}, Debug={debug_mode}, Sinyal Dosyası='{SIGNALS_FILE}'")
    print(f"🔧 Analiz Dosyası='{ANALIZ_FILE}', Detaylı Analiz Dosyası='{ANALIZ_SONUCLARI_FILE}'")
    print(f"🔧 Telegram Bot Token: {'Var' if BOT_TOKEN else 'Yok!'}, Chat ID: {'Var' if CHAT_ID else 'Yok!'}")

    if not BOT_TOKEN or not CHAT_ID:
         print("❌ UYARI: BOT_TOKEN veya CHAT_ID .env dosyasında ayarlanmamış!")

    # Flask uygulamasını çalıştır
    # '0.0.0.0' tüm ağ arayüzlerinden erişime izin verir (Docker vb. için gerekli)
    app.run(host="0.0.0.0", port=port, debug=debug_mode)
