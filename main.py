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
import locale # Sayı formatlama için eklendi

# .env dosyasını yükle
load_dotenv()

app = Flask(__name__)

# .env dosyasından değerleri al
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
# SIGNALS_FILE = "C:\\Users\\Administrator\\Desktop\\tradingview-telegram-bot\\signals.json" # Orijinal yol
SIGNALS_FILE = os.getenv("SIGNALS_FILE_PATH", "signals.json") # .env'den al veya varsayılan kullan
ANALIZ_FILE = "analiz.json"
ANALIZ_SONUCLARI_FILE = "analiz_sonuclari.json"

# --- Sayı Formatlama ve Emoji Ayarları ---

# Sayıları Türkçe formatında göstermek için (isteğe bağlı, binlik ayıracı için)
# Sisteminizde Türkçe locale kurulu olmalı (örn. Linux'ta sudo locale-gen tr_TR.UTF-8)
# Windows'ta genellikle hazırdır. Hata verirse bu satırları kaldırabilirsiniz.
try:
    # Windows için 'tr_TR' veya 'turkish'
    # Linux için 'tr_TR.utf8'
    locale.setlocale(locale.LC_ALL, 'tr_TR.utf8' if os.name != 'nt' else 'turkish')
    print("✅ Türkçe locale başarıyla ayarlandı.")
except locale.Error as e:
    print(f"⚠️ Uyarı: Türkçe locale ayarlanamadı ({e}). Sayı formatlaması varsayılan sistem ayarlarına göre yapılacak.")

def format_currency(value):
    """
    Sayısal bir değeri alır, gereksiz '.0'ları kaldırır,
    milyonları ' Milyon TL', diğerlerini ' TL' olarak formatlar (veya sadece sayı).
    Negatif ve küçük değerleri de yönetir. Yüzde gibi değerler için 'TL' eklemez.
    """
    try:
        # Gelen değeri float'a çevirmeye çalış
        num_str = str(value).strip()
        # Yüzde işareti varsa özel işlem
        is_percent = num_str.endswith('%')
        if is_percent:
            num_str = num_str[:-1].strip()

        num = float(num_str)

        # Neredeyse tamsayı ise (örn. 727651.0), tamsayı yap
        if abs(num - round(num)) < 0.00001:
            num = round(num)

        # Milyon veya daha büyük mü kontrol et (pozitif ve negatif)
        if abs(num) >= 1_000_000:
            # Milyona böl ve 2 ondalık basamakla formatla
            formatted_num = locale.format_string("%.2f", num / 1_000_000, grouping=True)
            return f"{formatted_num} Milyon TL"
        # Bin veya daha büyük mü kontrol et
        elif abs(num) >= 1000:
             # Tamsayı ise ondalıksız, değilse 2 ondalıklı formatla
            format_spec = "%.0f" if isinstance(num, int) or num == round(num) else "%.2f"
            formatted_num = locale.format_string(format_spec, num, grouping=True)
            unit = " TL" if not is_percent else "%"
            return f"{formatted_num}{unit}"
        # Küçük sayılar
        else:
             # Tamsayı ise ondalıksız, değilse 2 ondalıklı formatla (oranlar için 2 ondalık önemli)
            format_spec = "%.0f" if isinstance(num, int) or num == round(num) else "%.2f"
            formatted_num = locale.format_string(format_spec, num, grouping=True)
            unit = " TL" if not is_percent else "%" # Eğer yüzde değilse TL ekle
            # Çok küçükse TL eklemeyebiliriz, oranı basitçe gösterelim
            if abs(num) < 10 and not is_percent: # Oran gibi değerlerde TL anlamsız olabilir
                 unit = ""
            elif is_percent:
                 unit = "%"

            return f"{formatted_num}{unit}"

    except (ValueError, TypeError):
        # Eğer sayıya çevrilemiyorsa, orijinal değeri (string olarak) döndür
        return str(value)

EMOJI_MAP = {
    # Anahtar Kelimeler (Yorum başlangıcı ile eşleşecek)
    "PEG": "🧠",
    "F/K": "📈",
    "PD/DD": "⚖️",
    "Net Borç/FAVÖK": "🏦",
    "Net Kar Marjı": "💰",
    "Esas Faaliyet Kar Marjı": "🏭",
    "FAVÖK Marjı": "📊",
    "Net Dönem Karı Artışı": "💲",
    "Esas Faaliyet Karı Artışı": "💹", # Farklı emoji
    "FAVÖK Artışı": "🚀", # Farklı emoji
    "Satışlar Artışı": "🛒",
    "Dönen Varlıklar Artışı": "🔄",
    "Duran Varlıklar Artışı": "🏗️",
    "Toplam Varlıklar Artışı": "🏛️",
    "Finansal Borç Azalışı": "📉", # VEYA "✅"
    "Net Borç Azalışı": "✅",
    "Özkaynak Artışı": "💪",
    "Cari Oran": "💧",
    "Likidite Oranı": "🩸",
    "Nakit Oran": "💵",
    "Brüt Kar Marjı": "🏷️", # Yeni eklendi
    # Diğer olası anahtar kelimeler eklenebilir...
    "default": "🔹" # Anahtar kelime bulunamazsa kullanılacak varsayılan emoji
}

# --- Yardımcı Fonksiyonlar ---

def escape_markdown_v2(text):
    """
    Telegram API'sine MarkdownV2 formatında metin gönderirken özel karakterleri
    kaçırmak (escape etmek) için kullanılır.
    """
    # DİKKAT: Bu liste '*', '_', '`' gibi formatlama karakterlerini de içerir.
    # Eğer mesaj içinde manuel formatlama (örn. *kalın*) kullanılıyorsa,
    # bu karakterler de kaçırılacak ve formatlama görünmeyecektir.
    # Manuel formatlama isteniyorsa, bu listeden ilgili karakterler çıkarılmalıdır.
    # escape_chars = r'\[]()~>#+-=|{}.!' # Örnek: *, _, ` kaçırılmaz
    escape_chars = r'\_*[]()~`>#+-=|{}.!' # Mevcut hali: Hepsini kaçırır
    return re.sub(r'([{}])'.format(re.escape(escape_chars)), r'\\\1', str(text))

def send_telegram_message(message):
    """
    Verilen mesajı Telegram Bot API kullanarak belirtilen CHAT_ID'ye gönderir.
    Mesajı göndermeden önce MarkdownV2 için özel karakterleri kaçırır.
    Çok uzun mesajları (4096 karakterden fazla) otomatik olarak böler.
    """
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
            # API'ye POST isteği gönder. timeout=10 saniye sonra zaman aşımına uğrar.
            r = requests.post(url, json=data, timeout=15) # Timeout biraz daha artırıldı
            r.raise_for_status() # HTTP Hata Kodlarını Kontrol Et (4xx, 5xx gibi)
            print(f"✅ Telegram yanıtı (Mesaj parçası {i//4096 + 1}): {r.status_code}")
        except requests.exceptions.Timeout:
            print(f"❌ Telegram'a mesaj gönderilemedi (Zaman Aşımı): {url}")
        except requests.exceptions.RequestException as e:
            print(f"❌ Telegram'a mesaj gönderilemedi: {e}")
            if hasattr(e, 'response') and e.response is not None:
                 print(f"❌ Telegram Hata Detayı: {e.response.status_code} - {e.response.text}")
            print(f"❌ Gönderilemeyen mesaj parçası (orijinal): {message[i:i+4096]}")
        except Exception as e:
            print(f"❌ Beklenmedik hata (Telegram gönderimi): {e}")


@app.route("/signal", methods=["POST"])
def receive_signal():
    """
    TradingView veya başka bir kaynaktan gelen sinyalleri (webhook) kabul eden endpoint.
    """
    try:
        print(f">>> /signal endpoint tetiklendi ({request.method})")
        data = {}

        # 1. Gelen Veriyi İşle
        if request.is_json:
            print(">>> Gelen veri formatı: JSON")
            data = request.get_json()
            if not isinstance(data, dict):
                 print(f"⚠️ JSON verisi alındı ama dictionary değil: {data}. 'signal' anahtarına atanıyor.")
                 data = {"signal": str(data)}
        elif request.data:
            print(">>> Gelen veri formatı: Raw/Text")
            raw = request.data.decode("utf-8")
            print(f">>> Ham veri: {raw}")
            match = re.match(r"^(.*?)\s+\((.*?)\)\s*-\s*(.*)$", raw.strip())
            if match:
                symbol, exchange, signal_text = match.groups()
                data = {
                    "symbol": symbol.strip().upper(),
                    "exchange": exchange.strip(),
                    "signal": signal_text.strip()
                }
                print(f">>> Ham veri ayrıştırıldı: {data}")
            else:
                 print(f"⚠️ Signal formatı ayrıştırılamadı. Ham veri 'signal' olarak atanıyor.")
                 data = {
                    "symbol": "Bilinmiyor",
                    "exchange": "Bilinmiyor",
                    "signal": raw.strip()
                 }
        else:
             print("⚠️ Boş veya anlaşılamayan istek verisi alındı.")
             return "error: bad request - no data", 400

        # 2. Dinamik Yerleştirme (İsteğe Bağlı - Örnek)
        # signal_text = data.get("signal", "")
        # signal_text = re.sub(r"\{\{plot\(\"matisay trend direction\"\)\}\}", "-25", signal_text)
        # data["signal"] = signal_text

        # 3. Zaman Damgası Ekle
        data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # 4. Dosyaya Kaydet
        try:
            with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(data, ensure_ascii=False) + "\n")
            print(f"✅ Sinyal dosyaya kaydedildi: {SIGNALS_FILE}")
        except IOError as e:
             print(f"❌ Sinyal dosyasına yazılamadı ({SIGNALS_FILE}): {e}")
             send_telegram_message(f"⚠️ Uyarı: Sinyal dosyasına yazılamadı ({escape_markdown_v2(SIGNALS_FILE)}) \- G/Ç Hatası: {escape_markdown_v2(str(e))}")
        except Exception as e:
              print(f"❌ Sinyal dosyasına yazılırken beklenmedik hata ({SIGNALS_FILE}): {e}")
              send_telegram_message(f"⚠️ Uyarı (Genel): Sinyal dosyasına yazılamadı ({escape_markdown_v2(SIGNALS_FILE)}) \- {escape_markdown_v2(str(e))}")


        # 5. Telegram'a Bildirim Gönder
        symbol = data.get("symbol", "Bilinmiyor")
        exchange = data.get("exchange", "Bilinmiyor")
        signal_msg = data.get("signal", "İçerik Yok")

        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")

        # Mesajı hazırla (MarkdownV2 formatında)
        # DİKKAT: Aşağıdaki *, _ formatlamaları escape_markdown_v2 nedeniyle çalışmayabilir.
        message = f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({exchange_display})\n📍 _{signal_msg}_"
        print(f">>> Telegram'a gönderilecek mesaj (Önce): {message}")
        send_telegram_message(message)

        return "ok", 200

    except Exception as e:
        print(f"❌ /signal endpoint hatası: {e}")
        try:
            send_telegram_message(f"❌ `/signal` endpointinde hata oluştu: {escape_markdown_v2(str(e))}")
        except Exception as telegram_err:
            print(f"❌ Hata mesajı Telegram'a gönderilemedi: {telegram_err}")
        return str(e), 500


# --- Dosya Okuma ve Analiz Fonksiyonları ---

def parse_signal_line(line):
    """JSON formatındaki tek bir sinyal satırını Python dict nesnesine çevirir."""
    try:
        return json.loads(line.strip())
    except json.JSONDecodeError:
        print(f"⚠️ JSON parse hatası (satır atlanıyor): {line.strip()}")
        return None

def load_json_file(filename):
    """Belirtilen JSON dosyasını okur ve içeriğini Python dict olarak döndürür."""
    try:
        with open(filename, "r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError:
        print(f"⚠️ Uyarı: JSON dosyası bulunamadı: {filename}")
        return {}
    except json.JSONDecodeError:
        print(f"❌ Hata: JSON dosyası geçerli bir formatta değil: {filename}")
        return {}
    except Exception as e:
        print(f"❌ Beklenmedik Hata ({filename} okuma): {e}")
        return {}

def load_analiz_json():
    """analiz.json dosyasını yükler."""
    return load_json_file(ANALIZ_FILE)

def load_bist_analiz_json():
    """analiz_sonuclari.json dosyasını yükler."""
    return load_json_file(ANALIZ_SONUCLARI_FILE)

def generate_analiz_response(tickers):
    """
    Verilen hisse (ticker) listesi için 'analiz.json' dosyasından verileri alır,
    formatlar ve Telegram'da gösterilecek düz metin oluşturur.
    """
    analiz_verileri = load_analiz_json()
    analiz_listesi = []

    if not analiz_verileri:
         escaped_filename = escape_markdown_v2(ANALIZ_FILE)
         # Mesajı `code` formatında göndermeyi deneyelim
         return f"⚠️ Analiz verileri (`{escaped_filename}`) yüklenemedi veya boş\."

    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        analiz = analiz_verileri.get(ticker_upper)
        if analiz:
            puan = analiz.get("puan", 0)
            detaylar_list = analiz.get("detaylar")
            # Detaylar listesini birleştirirken her satır başına emoji ekleyelim (isteğe bağlı)
            detaylar = "\n".join([f"▪️ {line}" for line in detaylar_list]) if isinstance(detaylar_list, list) else "Detay bulunamadı."
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
                "puan": None,
                "detaylar": None,
                "yorum": f"❌ {ticker_upper} için analiz bulunamadı." # Formatsız
            })

    # Puana göre sırala (Puanı olmayanlar sona)
    analiz_listesi.sort(key=lambda x: (x["puan"] is not None, x["puan"]), reverse=True)

    response_lines = []
    for analiz in analiz_listesi:
        if analiz["puan"] is not None:
            # Tamamen düz metin, formatlama yok
            response_lines.append(
                f"📊 {analiz['ticker']} Analiz Sonuçları (Puan: {analiz['puan']}):\n{analiz['detaylar']}\n\n💬 Yorum: {analiz['yorum']}"
            )
        else:
            response_lines.append(analiz["yorum"])

    return "\n\n".join(response_lines)


def generate_bist_analiz_response(tickers):
    """
    Verilen hisse listesi için analiz_sonuclari.json'dan veri çeker,
    sayıları formatlar, emojiler ekler ve Telegram mesajı oluşturur.
    """
    all_analiz_data = load_bist_analiz_json()
    response_lines = []

    if not all_analiz_data:
         escaped_filename = escape_markdown_v2(ANALIZ_SONUCLARI_FILE)
         return f"⚠️ Detaylı analiz verileri (`{escaped_filename}`) yüklenemedi veya boş\."

    # Yorumlardaki sayıları (potansiyel olarak binlik/ondalık ayraçlı) bulmak için Regex
    # Daha esnek: '=' veya ':' sonrası, 'Değer:' sonrası veya tek başına sayıları yakalar
    # Örnek: "Değer: 1.234,56", "Değer: -50.0", "oranı çok iyi (0.04)"
    # Bu regex, formatlama fonksiyonu tarafından işlenecek sayısal kısmı yakalamaya çalışır.
    number_pattern = re.compile(r"([-+]?\s?\d[\d.,]*%?)")

    def replace_number_with_formatted(match):
        """re.sub için callback fonksiyonu. Yakalanan sayıyı formatlar."""
        number_str = match.group(1).strip()
        # Binlik ayıracını kaldır, ondalık ayracını '.' yap (varsa)
        cleaned_str = number_str.replace('.', '', number_str.count('.') - number_str.count('%') ).replace(',', '.')
        # Yüzde işaretini koru
        if '%' in number_str:
             cleaned_str = cleaned_str.replace('%', '') + '%' # Format fonksiyonu yüzdeyi anlar

        formatted = format_currency(cleaned_str)
        # Eğer orijinal sayı formatlanmış sayı ile aynıysa (örn. zaten "10 TL" ise),
        # tekrar formatlamayı önlemek için orijinali döndür.
        # Bu, "10%" gibi zaten formatlı değerlerin bozulmasını engeller.
        # VEYA format_currency zaten string döndürdüğü için bu kontrole gerek kalmayabilir.
        # print(f"Formatlama: '{number_str}' -> '{formatted}'") # Debug
        return formatted

    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        analiz_data = all_analiz_data.get(ticker_upper)

        if analiz_data:
            symbol = analiz_data.get("symbol", ticker_upper)
            score = analiz_data.get("score", "N/A")
            classification = analiz_data.get("classification", "Belirtilmemiş")
            comments = analiz_data.get("comments", [])

            formatted_comments_list = []
            if comments:
                for comment in comments:
                    # 1. Sayıları formatla (Regex ile bul ve değiştir)
                    # Önce yorumun sadece sayı içeren kısımlarını formatlayalım
                    # Örnek: "- PEG oranı mükemmel (< 0.5). Değer: 0.04"
                    # Callback fonksiyonu '0.5' ve '0.04'ü formatlayacak.
                    processed_comment = number_pattern.sub(replace_number_with_formatted, comment)

                    # 2. Uygun emojiyi bul ve ekle
                    found_emoji = EMOJI_MAP["default"]
                    # Yorumun başındaki anahtar kelimeye göre emoji bul
                    stripped_comment_start = comment.strip().lstrip('- ') # Başındaki '-' ve boşlukları at
                    for keyword, emoji in EMOJI_MAP.items():
                        if keyword != "default" and stripped_comment_start.startswith(keyword):
                            found_emoji = emoji
                            break
                    formatted_comments_list.append(f"{found_emoji} {processed_comment.lstrip('- ')}") # Başındaki '-' tekrar eklenmesin
                formatted_comments = "\n".join(formatted_comments_list)
            else:
                formatted_comments = "📝 Yorum bulunamadı." # Emoji eklendi

            # Puan ve Sınıflandırma için emojiler
            score_emoji = "📈"
            class_emoji = {"Excellent": "🏆", "Good": "👍", "Average": "😐", "Poor": "👎"}.get(classification, "🏅")

            # Mesajı Markdown ile oluştur
            # DİKKAT: escape_markdown_v2 fonksiyonu * karakterini kaçırırsa,
            # aşağıdaki kalın formatlama çalışmaz.
            message_body = (
                f"📊 *{escape_markdown_v2(symbol)}* Detaylı Analiz:\n\n"
                f"{score_emoji} *Puan:* {escape_markdown_v2(str(score))}\n"
                f"{class_emoji} *Sınıflandırma:* {escape_markdown_v2(classification)}\n\n"
                f"📝 *Öne Çıkanlar:*\n{escape_markdown_v2(formatted_comments)}" # Yorumları da escape et
            )
            response_lines.append(message_body)

        else:
            # Analiz bulunamadı mesajı (Formatsız, emoji eklendi)
            response_lines.append(f"❌ {ticker_upper} için detaylı analiz bulunamadı.")

    # Tüm hisselerin mesajlarını aralarına iki boş satır koyarak birleştir
    # Dikkat: Birleştirilmiş mesajı send_telegram_message'a gönderdiğimizde
    # escape_markdown_v2 tekrar çalışacak. Bu yüzden yukarıda her parçayı
    # manuel olarak escape ettik.
    final_message = "\n\n".join(response_lines)

    # return final_message # Direkt bu şekilde gönderebiliriz, send_telegram_message escape edecek.
    # VEYA Manuel escape ettiğimiz için parse_mode olmadan gönderebiliriz?
    # Hayır, parse_mode=MarkdownV2 gerekli, yukarıdaki manuel escape doğru yol.
    # Ama send_telegram_message'a göndermeden ÖNCE escape etmeliyiz.
    # Bu yüzden generate fonksiyonları escape edilmiş metin DÖNDÜRMEMELİ.
    # send_telegram_message zaten escape ediyor. Yukarıdaki manuel escape'leri geri alalım.

    # --- Düzeltme: Manuel escape'leri kaldıralım ---
    response_lines = [] # Listeyi temizle ve tekrar oluştur
    for ticker in tickers:
        ticker_upper = ticker.strip().upper()
        analiz_data = all_analiz_data.get(ticker_upper)

        if analiz_data:
            symbol = analiz_data.get("symbol", ticker_upper)
            score = analiz_data.get("score", "N/A")
            classification = analiz_data.get("classification", "Belirtilmemiş")
            comments = analiz_data.get("comments", [])

            formatted_comments_list = []
            if comments:
                for comment in comments:
                    processed_comment = number_pattern.sub(replace_number_with_formatted, comment)
                    found_emoji = EMOJI_MAP["default"]
                    stripped_comment_start = comment.strip().lstrip('- ')
                    for keyword, emoji in EMOJI_MAP.items():
                        if keyword != "default" and stripped_comment_start.startswith(keyword):
                            found_emoji = emoji
                            break
                    formatted_comments_list.append(f"{found_emoji} {processed_comment.lstrip('- ')}")
                formatted_comments = "\n".join(formatted_comments_list)
            else:
                formatted_comments = "📝 Yorum bulunamadı."

            score_emoji = "📈"
            class_emoji = {"Excellent": "🏆", "Good": "👍", "Average": "😐", "Poor": "👎"}.get(classification, "🏅")

            # Markdown formatlamasını koru, send_telegram_message escape edecek
            message_body = (
                f"📊 *{symbol}* Detaylı Analiz:\n\n"
                f"{score_emoji} *Puan:* {score}\n"
                f"{class_emoji} *Sınıflandırma:* {classification}\n\n"
                f"📝 *Öne Çıkanlar:*\n{formatted_comments}" # Yorumlar artık formatlı
            )
            response_lines.append(message_body)

        else:
            response_lines.append(f"❌ {ticker_upper} için detaylı analiz bulunamadı.")

    return "\n\n".join(response_lines) # Escape edilmemiş metni döndür


# --- Telegram Webhook ---
@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """
    Telegram Bot API'den gelen güncellemeleri (mesajlar, komutlar vb.) alan webhook endpoint'i.
    """
    print(">>> /telegram endpoint tetiklendi")
    update = request.json
    if not update:
        print("⚠️ Boş JSON verisi alındı.")
        return "ok", 200

    message = update.get("message")
    edited_message = update.get("edited_message")
    channel_post = update.get("channel_post")

    # Mesaj, düzenlenmiş mesaj veya kanal postasını işle (öncelik sırasına göre)
    target_message = message or edited_message or channel_post

    if not target_message:
        print("ℹ️ Tanınmayan veya mesaj içermeyen güncelleme tipi, atlanıyor.")
        return "ok", 200

    text = target_message.get("text", "").strip()
    chat_id = target_message.get("chat", {}).get("id")
    message_id = target_message.get("message_id") # Yanıtlamak için (isteğe bağlı)

    # Güvenlik: Sadece belirli bir sohbetten gelen mesajları işle (isteğe bağlı)
    # if str(chat_id) != CHAT_ID:
    #     print(f"⚠️ Uyarı: Mesaj beklenen sohbetten gelmedi (Gelen: {chat_id}, Beklenen: {CHAT_ID}). İşlenmeyecek.")
    #     return "ok", 200

    if not text:
        print("ℹ️ Boş mesaj içeriği alındı.")
        return "ok", 200

    print(f">>> Mesaj alındı (Chat ID: {chat_id}, Msg ID: {message_id}) -> Komut: '{text}'")

    # --- Komut İşleme ---
    response_message = None # Gönderilecek yanıt mesajı

    if text.startswith("/ozet"):
        print(">>> /ozet komutu işleniyor...")
        keyword = text[6:].strip().lower() if len(text) > 5 else None
        # İzin verilen anahtar kelimeler + map'teki anahtarlar
        keyword_map = {"bist": "bist_dly", "nasdaq": "bats", "binance": "binance"}
        allowed_keywords = list(keyword_map.keys()) + list(keyword_map.values())

        if keyword:
            if keyword in allowed_keywords:
                print(f">>> /ozet için anahtar kelime: {keyword}")
                response_message = generate_summary(keyword)
            else:
                 allowed_display = ", ".join(sorted(list(set(allowed_keywords)))) # Tekrarları kaldır, sırala
                 # Mesajı escape et
                 response_message = f"⚠️ Geçersiz anahtar kelime: `{escape_markdown_v2(keyword)}`\. İzin verilenler: {escape_markdown_v2(allowed_display)}"
                 print(f"Geçersiz özet anahtar kelimesi: {keyword}")
        else:
            print(">>> /ozet için anahtar kelime yok, tüm sinyaller kullanılıyor.")
            response_message = generate_summary()

    elif text.startswith("/analiz"):
        print(">>> /analiz komutu işleniyor...")
        tickers_input = text[7:].strip()
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
        if not tickers:
            # Mesajı escape et
            response_message = "Lütfen bir veya daha fazla hisse kodu belirtin\. Örnek: `/analiz GOOGL,AAPL,TSLA`"
        else:
            print(f"Analiz istenen hisseler: {tickers}")
            response_message = generate_analiz_response(tickers) # Düz metin döner

    elif text.startswith("/bist_analiz"):
        print(">>> /bist_analiz komutu işleniyor...")
        tickers_input = text[12:].strip()
        tickers = [ticker.strip().upper() for ticker in tickers_input.split(",") if ticker.strip()]
        if not tickers:
             # Mesajı escape et
             response_message = "Lütfen bir veya daha fazla BIST hisse kodu belirtin\. Örnek: `/bist_analiz EREGL,THYAO`"
        else:
            print(f"Detaylı BIST analizi istenen hisseler: {tickers}")
            response_message = generate_bist_analiz_response(tickers) # Formatlı metin döner

    elif text.startswith("/yardim") or text.startswith("/help"):
         print(">>> /yardim komutu işleniyor...")
         # Yardım mesajını escape etmeye gerek yok, zaten escape edilmiş karakterler içeriyor
         response_message = (
             "🤖 *Kullanılabilir Komutlar:*\n\n"
             "*/ozet* \[`borsa`] \- Kayıtlı sinyallerin özetini gösterir\. Opsiyonel olarak borsa adı \(`bist`, `nasdaq`, `binance`\) ile filtreleyebilirsiniz\.\n\n"
             "*/analiz* `HISSE1`,`HISSE2` \- Belirtilen hisse kodları için temel analiz \(puan, yorum\) gösterir \(analiz\.json\)\. Düz metin çıktıdır\.\n\n"
             "*/bist_analiz* `HISSE1`,`HISSE2` \- Belirtilen BIST hisseleri için detaylı analiz \(puan, sınıflandırma, öne çıkanlar\) gösterir \(analiz_sonuclari\.json\)\. Formatlı çıktıdır\.\n\n"
             "*/temizle* \- `signals\.json` dosyasını manuel olarak temizler \(Dikkatli kullanın\!\)\.\n\n"
             "*/yardim* \- Bu yardım mesajını gösterir\."
         )

    elif text.startswith("/temizle") or text.startswith("/clear"):
        print(">>> /temizle komutu işleniyor (Manuel)")
        try:
            clear_signals()
            # Dosya adını escape et
            escaped_filename = escape_markdown_v2(SIGNALS_FILE)
            response_message = f"✅ `{escaped_filename}` dosyası manuel olarak temizlendi\."
        except Exception as e:
            print(f"❌ Manuel sinyal temizleme hatası: {e}")
            response_message = f"❌ `{escape_markdown_v2(SIGNALS_FILE)}` temizlenirken hata oluştu: {escape_markdown_v2(str(e))}"

    # Eğer bir yanıt mesajı oluşturulduysa gönder
    if response_message:
        send_telegram_message(response_message)
    else:
        # Bilinmeyen komut veya işlenmeyen mesaj durumu
        print(f"ℹ️ Komut işlenmedi veya yanıt oluşturulmadı: {text}")
        # İsteğe bağlı: Bilinmeyen komutlara yanıt verilebilir
        # send_telegram_message(f"❓ Anlamadım: {escape_markdown_v2(text)}\nKullanılabilir komutlar için `/yardim` yazabilirsiniz\.")

    return "ok", 200


# --- Özet Fonksiyonu ---
def generate_summary(keyword=None):
    """
    'signals.json' dosyasındaki sinyalleri okur, kategorize eder ve bir özet metni oluşturur.
    İsteğe bağlı olarak belirli bir 'keyword' (örn: 'bist', 'nasdaq') içeren sinyalleri filtreler.
    """
    if not os.path.exists(SIGNALS_FILE):
        return "📊 Henüz hiç sinyal kaydedilmedi."

    lines = []
    try:
        with open(SIGNALS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except IOError as e:
        print(f"❌ Sinyal dosyası okunamadı ({SIGNALS_FILE}): {e}")
        return f"⚠️ Sinyal dosyası (`{escape_markdown_v2(SIGNALS_FILE)}`) okunurken bir hata oluştu\."
    except Exception as e:
         print(f"❌ Sinyal dosyası okunurken beklenmedik hata ({SIGNALS_FILE}): {e}")
         return f"⚠️ Sinyal dosyası (`{escape_markdown_v2(SIGNALS_FILE)}`) okunurken genel bir hata oluştu\."

    if not lines:
        return "📊 Sinyal dosyasında kayıtlı veri bulunamadı."

    # Sinyalleri kategorilere ayır
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

    parsed_lines = [parse_signal_line(line) for line in lines if line.strip()]
    parsed_lines = [s for s in parsed_lines if s]

    # Filtreleme
    keyword_map = {"bist": "bist_dly", "nasdaq": "bats", "binance": "binance"}
    if keyword:
        keyword_lower = keyword.strip().lower()
        keyword_mapped = keyword_map.get(keyword_lower, keyword_lower)
        print(f"Özet filtreleniyor: Exchange adı '{keyword_mapped}' içerenler")
        filtered_lines = [s for s in parsed_lines if keyword_mapped in s.get("exchange", "").lower()]
        if not filtered_lines:
             return f"📊 '{escape_markdown_v2(keyword)}' anahtar kelimesi için uygun sinyal bulunamadı\."
        parsed_lines = filtered_lines

    print(f"Özet için işlenecek sinyal sayısı (filtre sonrası): {len(parsed_lines)}")

    # Kategorizasyon
    for signal_data in parsed_lines:
        symbol = signal_data.get("symbol", "Bilinmiyor")
        exchange = signal_data.get("exchange", "Bilinmiyor")
        signal_text = signal_data.get("signal", "")
        exchange_display = exchange.replace("BIST_DLY", "BIST").replace("BATS", "NASDAQ")
        display_key = f"{symbol} ({exchange_display})" # Escape etmeyeceğiz, send_telegram_message yapacak
        signal_lower = signal_text.lower()

        # KAIRI
        if "kairi" in signal_lower:
            try:
                kairi_match = re.search(r"kairi\s*([-+]?\d*\.?\d+)", signal_lower)
                if kairi_match:
                    kairi_value = round(float(kairi_match.group(1)), 2)
                    kairi_entry = f"{display_key}: KAIRI {kairi_value}" # Escape yok
                    if kairi_value <= -30: summary["kairi_-30"].add(kairi_entry)
                    elif kairi_value <= -20: summary["kairi_-20"].add(kairi_entry)
                    # Güçlü sinyal
                    for other in parsed_lines:
                        if (other.get("symbol") == symbol and other.get("exchange") == exchange and
                            re.search(r"(mükemmel alış|alış sayımı)", other.get("signal", "").lower())):
                            summary["güçlü"].add(f"✅ {display_key} \- KAIRI: {kairi_value} & Alış Sinyali") # Escape '-'
                            break
            except Exception as e: print(f"KAIRI işlenirken hata: {e} - Sinyal: {signal_text}")
        # Matisay
        elif "matisay" in signal_lower:
             try:
                 matisay_match = re.search(r"matisay\s*([-+]?\d*\.?\d+)", signal_lower)
                 if matisay_match:
                     matisay_value = round(float(matisay_match.group(1)), 2)
                     if matisay_value < -25:
                         summary["matisay_-25"].add(f"{display_key}: Matisay {matisay_value}") # Escape yok
             except Exception as e: print(f"Matisay işlenirken hata: {e} - Sinyal: {signal_text}")
        # Diğerleri
        elif re.search(r"mükemmel alış", signal_lower): summary["mükemmel_alış"].add(display_key)
        elif re.search(r"alış sayımı", signal_lower): summary["alış_sayımı"].add(display_key)
        elif re.search(r"mükemmel satış", signal_lower): summary["mükemmel_satış"].add(display_key)
        elif re.search(r"satış sayımı", signal_lower): summary["satış_sayımı"].add(display_key)

    # Özeti Oluşturma (Markdown Formatlı)
    # DİKKAT: Bu formatlamalar escape_markdown_v2 fonksiyonu tarafından escape edilirse GÖRÜNMEZ.
    msg_parts = []
    if summary["güçlü"]: msg_parts.append("*📊 GÜÇLÜ EŞLEŞEN SİNYALLER:*\n" + "\n".join(sorted(list(summary["güçlü"]))))
    if summary["kairi_-30"]: msg_parts.append("*🔴 KAIRI ≤ \-30:*\n" + "\n".join(sorted(list(summary["kairi_-30"])))) # Escape '-'
    if summary["kairi_-20"]: msg_parts.append("*🟠 KAIRI ≤ \-20 (ama > \-30):*\n" + "\n".join(sorted(list(summary["kairi_-20"])))) # Escape '-'
    if summary["matisay_-25"]: msg_parts.append("*🟣 Matisay < \-25:*\n" + "\n".join(sorted(list(summary["matisay_-25"])))) # Escape '-'
    if summary["mükemmel_alış"]: msg_parts.append("*🟢 Mükemmel Alış:*\n" + "\n".join(sorted(list(summary["mükemmel_alış"]))))
    if summary["alış_sayımı"]: msg_parts.append("*📈 Alış Sayımı Tamamlananlar:*\n" + "\n".join(sorted(list(summary["alış_sayımı"]))))
    if summary["mükemmel_satış"]: msg_parts.append("*🔵 Mükemmel Satış:*\n" + "\n".join(sorted(list(summary["mükemmel_satış"]))))
    if summary["satış_sayımı"]: msg_parts.append("*📉 Satış Sayımı Tamamlananlar:*\n" + "\n".join(sorted(list(summary["satış_sayımı"]))))

    if not msg_parts:
        filter_text = f" '{escape_markdown_v2(keyword)}' filtresi ile" if keyword else ""
        return f"📊 Gösterilecek uygun sinyal bulunamadı{filter_text}\."

    final_summary = "\n\n".join(msg_parts)
    print("Oluşturulan Özet (ilk 200 karakter):", final_summary[:200] + "...")
    # Escape edilmemiş metni döndür, send_telegram_message halledecek.
    return final_summary


# --- Sinyal Temizleme ---

@app.route("/clear_signals", methods=["POST"])
def clear_signals_endpoint():
    """
    'signals.json' dosyasını temizlemek için manuel HTTP endpoint'i.
    !!! GÜVENLİK UYARISI: Bu endpoint'e erişimi kısıtlayın!
    """
    print(">>> /clear_signals endpoint tetiklendi (Manuel HTTP POST)")
    # Örnek Token Kontrolü (Aktif değil)
    # expected_token = os.getenv("CLEAR_TOKEN")
    # provided_token = request.headers.get("Authorization")
    # if not expected_token or provided_token != f"Bearer {expected_token}":
    #     print("❌ Yetkisiz manuel temizleme isteği reddedildi.")
    #     return "Unauthorized", 401

    try:
        clear_signals()
        escaped_filename = escape_markdown_v2(SIGNALS_FILE)
        send_telegram_message(f"📁 `{escaped_filename}` dosyası HTTP endpoint üzerinden manuel olarak temizlendi\.")
        return f"📁 {SIGNALS_FILE} dosyası temizlendi!", 200
    except Exception as e:
        print(f"❌ Manuel sinyal temizleme hatası (HTTP): {e}")
        escaped_filename = escape_markdown_v2(SIGNALS_FILE)
        send_telegram_message(f"❌ `{escaped_filename}` temizlenirken hata oluştu (HTTP): {escape_markdown_v2(str(e))}")
        return str(e), 500

def clear_signals():
    """signals.json dosyasının içeriğini temizler."""
    try:
        if os.path.exists(SIGNALS_FILE):
            with open(SIGNALS_FILE, "w", encoding="utf-8") as f:
                f.write("")
            print(f"📁 {SIGNALS_FILE} dosyası başarıyla temizlendi.")
        else:
            print(f"ℹ️ {SIGNALS_FILE} dosyası bulunamadı, temizleme işlemi atlandı.")
    except IOError as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken G/Ç hatası: {e}")
        escaped_filename = escape_markdown_v2(SIGNALS_FILE)
        send_telegram_message(f"⚠️ Otomatik temizlik hatası: `{escaped_filename}` temizlenemedi \- G/Ç Hatası: {escape_markdown_v2(str(e))}")
        raise # Hatayı tekrar fırlat ki clear_signals_daily bilsin
    except Exception as e:
        print(f"❌ {SIGNALS_FILE} dosyası temizlenirken beklenmedik hata: {e}")
        escaped_filename = escape_markdown_v2(SIGNALS_FILE)
        send_telegram_message(f"⚠️ Otomatik temizlik hatası (Genel): `{escaped_filename}` temizlenemedi \- {escape_markdown_v2(str(e))}")
        raise # Hatayı tekrar fırlat

def clear_signals_daily():
    """Her gün TR saatiyle 23:59'da signals.json dosyasını temizler."""
    already_cleared_today = False
    print("🕒 Günlük sinyal temizleme görevi başlatıldı (Kontrol periyodu: 30sn).")
    while True:
        try:
            tz = pytz.timezone("Europe/Istanbul")
            now = datetime.now(tz)

            if now.hour == 23 and now.minute == 59:
                if not already_cleared_today:
                    print(f"⏰ Zamanı geldi ({now.strftime('%Y-%m-%d %H:%M:%S %Z')}), {SIGNALS_FILE} temizleniyor...")
                    try:
                        clear_signals() # Temizlemeyi dene
                        # Başarılı olursa Telegram'a bildirim gönder
                        escaped_filename = escape_markdown_v2(SIGNALS_FILE)
                        send_telegram_message(f"🧹 Günlük otomatik temizlik yapıldı (`{escaped_filename}`)\.")
                        already_cleared_today = True
                        print("✅ Temizlik yapıldı ve bugün için işaretlendi.")
                        time.sleep(65) # 00:00'ı geçmek için bekle
                        continue
                    except Exception as clear_err:
                         # clear_signals içinde hata olduysa zaten loglandı ve Telegram'a gitti.
                         # Burada sadece döngünün devam etmesi için loglama yapabiliriz.
                         print(f"❌ Günlük temizlik yapılamadı: {clear_err}. Bir sonraki deneme bekleniyor.")
                         # Hata durumunda da bir süre bekle (örn. 5 dakika)
                         time.sleep(300)
            else:
                if already_cleared_today:
                     print("🕰️ Yeni güne geçildi veya saat 23:59 dışı, temizlendi bayrağı sıfırlandı.")
                     already_cleared_today = False

            time.sleep(30) # Normal kontrol aralığı

        except Exception as e:
            print(f"❌ clear_signals_daily döngüsünde kritik hata: {e}")
            time.sleep(60) # Kritik hata durumunda daha uzun bekle


# --- Ana Uygulama Başlangıcı ---
if __name__ == "__main__":
    # Arka Plan Temizlik Görevini Başlat
    cleanup_thread = threading.Thread(target=clear_signals_daily, daemon=True)
    cleanup_thread.start()

    print("🚀 Flask uygulaması başlatılıyor...")
    # Token'ın sadece son 4 hanesini göster
    bot_token_display = f"{'*' * (len(BOT_TOKEN) - 4)}{BOT_TOKEN[-4:]}" if BOT_TOKEN and len(BOT_TOKEN) > 4 else "YOK veya Geçersiz"
    print(f"🔑 Bot Token: {bot_token_display}")
    print(f"👤 Chat ID: {CHAT_ID if CHAT_ID else 'YOK'}")
    print(f"💾 Sinyal Dosyası: {SIGNALS_FILE}")
    print(f"📊 Analiz Dosyası (Temel): {ANALIZ_FILE}")
    print(f"📈 Analiz Dosyası (Detaylı BIST): {ANALIZ_SONUCLARI_FILE}")
    print(f"🌍 Dinlenen Adres: http://0.0.0.0:5000")
    print(" Mavi Webhook Endpoint'i /telegram olarak ayarlayın.")
    print("🎯 Sinyal Endpoint: /signal (POST)")
    print("🧹 Temizlik Endpoint: /clear_signals (POST) - DİKKAT: Güvenlik!")
    print("🤖 Bot çalışıyor... Komutları bekliyor.")

    # Flask uygulamasını başlat (Canlı ortam için debug=False)
    # Geliştirme için: app.run(host="0.0.0.0", port=5000, debug=True)
    app.run(host="0.0.0.0", port=5000)
