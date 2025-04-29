# -*- coding: utf-8 -*-
from flask import Flask, request, jsonify # jsonify debug için eklendi
import json
import requests
import os
import time
import re
# import threading # Şimdilik kullanılmıyor
from datetime import datetime, date # date eklendi
# import pytz # Şimdilik kullanılmıyor
from dotenv import load_dotenv
import traceback # Hata ayıklama için

# Ortam değişkenlerini yükle
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = os.getenv("CHAT_ID") # Yöneticiye bildirim/hata göndermek için
ANALIZ_FILE = os.getenv("ANALIZ_FILE_PATH", "analiz.json")
BIST_ANALIZ_FILE = os.getenv("ANALIZ_SONUCLARI_FILE_PATH", "analiz_sonuclari.json")
# YENİ: Sinyallerin kaydedileceği dosya
SIGNAL_LOG_FILE = os.getenv("SIGNAL_LOG_FILE_PATH", "signals_log.jsonl")

app = Flask(__name__)

# --- Yardımcı Fonksiyonlar ---

def load_json_file(path):
    """Verilen yoldaki JSON dosyasını okur ve içeriğini döndürür."""
    try:
        if not os.path.exists(path):
            print(f"❌ Uyarı: JSON dosyası bulunamadı: {path}")
            return {}
        # Boş dosyayı okumaya çalışma, geçerli JSON değil
        if os.path.getsize(path) == 0:
            print(f"❌ Uyarı: JSON dosyası boş: {path}")
            return {} # Boş dosya için boş sözlük döndür, hata verme

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                 print(f"❌ Uyarı: JSON dosyasının kökü bir sözlük değil: {path}")
                 raise ValueError("JSON root is not a dictionary")
            return data
    except json.JSONDecodeError as e:
        error_message = f"🚨 JSON Decode Hatası!\nDosya: {os.path.basename(path)}\nHata: {e}"
        print(f"❌ JSON okuma/decode hatası ({path}): {e}")
        if ADMIN_CHAT_ID:
            send_telegram_message(ADMIN_CHAT_ID, error_message, parse_mode=None, avoid_self_notify=True)
        return None
    except ValueError as e:
        error_message = f"🚨 JSON Format Hatası!\nDosya: {os.path.basename(path)}\nHata: {e}"
        print(f"❌ JSON format hatası ({path}): {e}")
        if ADMIN_CHAT_ID:
            send_telegram_message(ADMIN_CHAT_ID, error_message, parse_mode=None, avoid_self_notify=True)
        return None
    except Exception as e:
        error_message = f"🚨 Genel JSON Yükleme Hatası!\nDosya: {os.path.basename(path)}\nHata: {e}\n{traceback.format_exc()}"
        print(f"❌ Genel JSON yükleme hatası ({path}): {e}")
        if ADMIN_CHAT_ID:
            send_telegram_message(ADMIN_CHAT_ID, error_message, parse_mode=None, avoid_self_notify=True)
        return None

def append_to_jsonl(path, data_dict):
    """Verilen sözlüğü JSON Lines dosyasına ekler."""
    try:
        # Veriye her zaman sunucu zaman damgasını ekleyelim (ISO formatında)
        data_dict['server_timestamp'] = datetime.now().isoformat()
        json_string = json.dumps(data_dict, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json_string + "\n")
        return True
    except Exception as e:
        print(f"❌ JSONL dosyasına yazma hatası ({path}): {e}")
        if ADMIN_CHAT_ID:
             error_message = f"🚨 Dosyaya Yazma Hatası!\nDosya: {os.path.basename(path)}\nHata: {e}\nVeri: {data_dict}"
             send_telegram_message(ADMIN_CHAT_ID, error_message[:4000], parse_mode=None, avoid_self_notify=True)
        return False

def send_telegram_message(chat_id, msg, parse_mode="Markdown", avoid_self_notify=False):
    """Verilen chat_id'ye Telegram mesajı gönderir. Uzunsa böler."""
    if not BOT_TOKEN or not chat_id:
        print("🚨 Telegram gönderimi için BOT_TOKEN veya chat_id eksik!")
        return False

    msg = str(msg)
    max_length = 4096
    messages_to_send = []

    if len(msg) > max_length:
        # Mesajı bölme mantığı (önceki gibi)
        parts = msg.split('\n\n')
        current_message = ""
        for part in parts:
            part_len = len(part.encode('utf-8')) # Gerçek byte uzunluğunu kontrol et
            current_len = len(current_message.encode('utf-8'))

            if part_len >= max_length - 50: # Tek başına çok uzunsa
                if current_message: messages_to_send.append(current_message.strip())
                current_message = ""
                # Daha güvenli bölme (kelime ortasında kesmemeye çalış)
                start = 0
                while start < len(part):
                    # Max uzunluğa yakın bir yerden bölmeye çalış
                    # Son boşluk veya satır sonunu bul
                    split_point = -1
                    search_end = min(start + max_length - 50, len(part))
                    # Geriye doğru boşluk veya yeni satır ara
                    rfind_space = part.rfind(' ', start, search_end)
                    rfind_newline = part.rfind('\n', start, search_end)
                    split_point = max(rfind_space, rfind_newline)

                    # Uygun bölme noktası bulunamazsa veya çok kısaysa, karakter bazlı böl
                    if split_point <= start or split_point < start + 50: # Çok kısa kesme
                       split_point = search_end

                    messages_to_send.append(part[start:split_point])
                    start = split_point
                    # Bölünen yer boşluk veya yeni satırsa sonraki karakterden başla
                    if start < len(part) and part[start] in (' ', '\n'):
                        start += 1

            elif current_len + part_len + 2 <= max_length: # Mevcut mesaja sığıyorsa
                current_message += part + "\n\n"
            else: # Sığmıyorsa, mevcutu gönder, yeniye başla
                messages_to_send.append(current_message.strip())
                current_message = part + "\n\n"

        if current_message: messages_to_send.append(current_message.strip())
    else:
        messages_to_send.append(msg)

    all_sent_successfully = True
    for message_part in messages_to_send:
         if not message_part.strip(): continue
         try:
             url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
             data = {"chat_id": chat_id, "text": message_part}
             if parse_mode: data["parse_mode"] = parse_mode

             r = requests.post(url, json=data, timeout=20)
             r.raise_for_status()
             print(f"📤 Telegram'a gönderildi (Chat ID: {chat_id}): {r.status_code}")
             time.sleep(0.6) # Rate limiting
         except requests.exceptions.RequestException as e:
             all_sent_successfully = False
             print(f"🚨 Telegram gönderim hatası (Chat ID: {chat_id}): {e}")
             if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID) and not avoid_self_notify:
                 send_telegram_message(ADMIN_CHAT_ID, f"🚨 Kullanıcıya Mesaj Gönderilemedi!\nChat ID: {chat_id}\nHata: {e}", parse_mode=None, avoid_self_notify=True)
             break
         except Exception as e:
             all_sent_successfully = False
             print(f"🚨 Beklenmedik Telegram gönderim hatası (Chat ID: {chat_id}): {e}")
             if ADMIN_CHAT_ID and str(chat_id) != str(ADMIN_CHAT_ID) and not avoid_self_notify:
                  send_telegram_message(ADMIN_CHAT_ID, f"🚨 Beklenmedik Hata (TG Gönderim)!\nChat ID: {chat_id}\nHata: {e}\n{traceback.format_exc()}", parse_mode=None, avoid_self_notify=True)
             break
    return all_sent_successfully

def simplify_exchange(exchange_name):
    """ Borsa ismini basitleştirir."""
    name = str(exchange_name).upper()
    if name.startswith("BIST"): return "BIST"
    if name == "BATS": return "NASDAQ"
    mapping = {"NASDAQ": "NASDAQ", "NYSE": "NYSE", "BINANCE": "BINANCE", "OKX": "OKX", "BYBIT": "BYBIT", "KUCOIN": "KUCOIN", "GEMINI":"GEMINI", "KRAKEN":"KRAKEN", "COINBASE":"COINBASE"}
    return mapping.get(name, exchange_name)

# --- Analiz İşleme Fonksiyonları --- (Değişiklik Yok)
def format_analiz_output(ticker_data):
    t = ticker_data.get("symbol", "Bilinmiyor"); puan = ticker_data.get("puan", "N/A"); detaylar = ticker_data.get("detaylar", [])
    target_price_line, potential_line, analyst_count_line, sector_line, industry_line = "🎯 Hedef Fiyat: Bilgi Yok", "🚀 Potansiyel: Bilgi Yok", "👨‍💼 Analist Sayısı: Bilgi Yok", "🏢 Sektör: Bilgi Yok", "⚙️ Endüstri: Bilgi Yok"
    keys_to_extract = {"Hedef Fiyat:": ("🎯", target_price_line), "Potansiyel:": ("🚀", potential_line), "Analist Sayısı:": ("👨‍💼", analyst_count_line), "Sektör:": ("🏢", sector_line), "Endüstri:": ("⚙️", industry_line)}
    extracted_lines_set = set()
    for line in detaylar:
        for key, (emoji, default_value) in keys_to_extract.items():
            if key in line:
                formatted_line = f"{emoji} {line}" if not line.startswith(emoji) else line
                if key == "Hedef Fiyat:": target_price_line = formatted_line
                elif key == "Potansiyel:": potential_line = formatted_line
                elif key == "Analist Sayısı:": analyst_count_line = formatted_line
                elif key == "Sektör:": sector_line = formatted_line
                elif key == "Endüstri:": industry_line = formatted_line
                extracted_lines_set.add(line); break
    core_details = [line for line in detaylar if line not in extracted_lines_set]; detay_text = "\n".join(core_details)
    output = (f"📊 *{t} Analiz Sonuçları (Puan: {puan})*\n{detay_text}\n{target_price_line}\n{potential_line}\n{analyst_count_line}\n{sector_line}\n{industry_line}\n\n{t} için analiz tamamlandı. Toplam puan: {puan}.")
    return output

def format_bist_analiz_output(ticker_data):
    sembol = ticker_data.get("symbol", "Bilinmiyor"); puan = ticker_data.get("score", "N/A"); sinif = ticker_data.get("classification", "Belirtilmemiş"); yorumlar = ticker_data.get("comments", [])
    emoji_map = {"peg oranı": "🎯", "f/k oranı": "💰", "net borç/favök": "🏦","net dönem karı": "📈", "finansal borç": "📉", "net borç": "💸","dönen varlıklar": "🔄", "duran varlıklar": "🏢", "toplam varlıklar": "🏛️", "özkaynak": "🧱", "default": "➡️"}
    yorum_lines = []
    if yorumlar:
        for y in yorumlar:
            y_clean = str(y).strip();
            if not y_clean: continue
            eklenecek_emoji = emoji_map["default"]; lower_y = y_clean.lower(); found_emoji = False
            for k, v in emoji_map.items():
                if k != "default" and lower_y.startswith(k): eklenecek_emoji = v; found_emoji = True; break
            if not found_emoji:
                 for k, v in emoji_map.items():
                     if k != "default" and k in lower_y: eklenecek_emoji = v; break
            yorum_lines.append(f"{eklenecek_emoji} {y_clean}")
    else: yorum_lines.append("➡️ Yorum bulunamadı.")
    yorum_text = "\n".join(yorum_lines)
    output = (f"📊 BİST Detaylı Analiz\n\n🏷️ Sembol: *{sembol}*\n📈 Puan: *{puan}*\n🏅 Sınıflandırma: {sinif}\n\n📝 Öne Çıkanlar:\n{yorum_text}")
    return output

# --- Komut İşleyiciler --- (handle_ozet_command hariç değişiklik yok)
def handle_analiz_command(chat_id, args):
    if not args: send_telegram_message(chat_id, "Lütfen analiz için sembolleri belirtin.\nÖrnek: `/analiz AAPL, MSFT`"); return
    tickers = [t.strip().upper() for t in re.split(r'[ ,]+', args) if t.strip()]
    if not tickers: send_telegram_message(chat_id, "Geçerli sembol belirtilmedi.\nÖrnek: `/analiz AAPL,MSFT`"); return

    print(f"🔍 /analiz komutu alındı (Chat ID: {chat_id}): {tickers}")
    data = load_json_file(ANALIZ_FILE)
    if data is None: send_telegram_message(chat_id, f"❌ Analiz verisi ({os.path.basename(ANALIZ_FILE)}) yüklenemedi."); return
    if not data: send_telegram_message(chat_id, f"❌ Analiz verisi ({os.path.basename(ANALIZ_FILE)}) bulunamadı/boş."); return

    results_found, results_not_found = [], []
    for t in tickers:
        hisse_data = data.get(t)
        if hisse_data and isinstance(hisse_data, dict): hisse_data['symbol'] = t; results_found.append(hisse_data)
        else: results_not_found.append(f"❌ `{t}` için veri bulunamadı.")

    if not results_found:
        error_message = "\n".join(results_not_found) if results_not_found else f"❌ Sembol(ler) için ({', '.join(tickers)}) veri bulunamadı."
        send_telegram_message(chat_id, error_message); return

    def get_score(item):
        score = item.get('puan', -float('inf'))
        if isinstance(score, (int, float)): return score
        try: return float(score)
        except (ValueError, TypeError): return -float('inf')
    results_found.sort(key=get_score, reverse=True)

    formatted_results = [format_analiz_output(hisse) for hisse in results_found]
    final_output = "\n\n".join(formatted_results + results_not_found)
    send_telegram_message(chat_id, final_output)

def handle_bist_analiz_command(chat_id, args):
    if not args: send_telegram_message(chat_id, "Lütfen BİST sembolünü belirtin.\nÖrnek: `/bist_analiz MIATK`"); return
    ticker = args.split(None, 1)[0].strip().upper()
    if not ticker: send_telegram_message(chat_id, "Geçerli BİST sembolü belirtilmedi.\nÖrnek: `/bist_analiz MIATK`"); return

    print(f"🔍 /bist_analiz komutu alındı (Chat ID: {chat_id}): {ticker}")
    data = load_json_file(BIST_ANALIZ_FILE)
    if data is None: send_telegram_message(chat_id, f"❌ BİST Analiz verisi ({os.path.basename(BIST_ANALIZ_FILE)}) yüklenemedi."); return
    if not data: send_telegram_message(chat_id, f"❌ BİST Analiz verisi ({os.path.basename(BIST_ANALIZ_FILE)}) bulunamadı/boş."); return

    hisse_data = data.get(ticker)
    if not hisse_data or not isinstance(hisse_data, dict): send_telegram_message(chat_id, f"❌ `{ticker}` için BİST analiz verisi bulunamadı."); return

    output = format_bist_analiz_output(hisse_data)
    send_telegram_message(chat_id, output)

# YENİ: Dinamik Özet Fonksiyonu
def handle_ozet_command(chat_id, args):
    """ /ozet komutunu işler, güncel sinyallerden dinamik özet çıkarır """
    print(f"🔍 /ozet komutu alındı (Chat ID: {chat_id})")
    today_str = date.today().isoformat() # Bugünün tarihi (YYYY-AA-GG)

    signals_today = []
    try:
        if not os.path.exists(SIGNAL_LOG_FILE):
            send_telegram_message(chat_id, "ℹ️ Bugün için kaydedilmiş sinyal bulunamadı.")
            return

        with open(SIGNAL_LOG_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try:
                    signal_data = json.loads(line)
                    # Zaman damgasını kontrol et (ISO formatında olduğunu varsayıyoruz)
                    signal_ts = signal_data.get('server_timestamp', '')
                    if signal_ts.startswith(today_str):
                        signals_today.append(signal_data)
                except json.JSONDecodeError:
                    print(f"⚠️ Geçersiz JSON satırı atlandı: {line[:100]}")
                except Exception as e:
                     print(f"⚠️ Satır işlenirken hata: {e} - Satır: {line[:100]}")

    except Exception as e:
        print(f"❌ Sinyal log dosyası ({SIGNAL_LOG_FILE}) okunurken hata: {e}")
        send_telegram_message(chat_id, f"❌ Sinyal log dosyası okunurken bir hata oluştu.")
        if ADMIN_CHAT_ID:
            send_telegram_message(ADMIN_CHAT_ID, f"🚨 Sinyal Log Okuma Hatası!\nDosya: {SIGNAL_LOG_FILE}\nHata: {e}", parse_mode=None, avoid_self_notify=True)
        return

    if not signals_today:
        send_telegram_message(chat_id, f"📊 GÜNLÜK SİNYAL ÖZETİ ({today_str}):\n\nBugün için kaydedilmiş sinyal bulunamadı.")
        return

    # Sinyalleri kategorize et
    kategori_map = {
        "kairi_neg30": [], # 🔴
        "kairi_neg20": [], # 🟠
        "matisay_neg25": [], # 🟣
        "mukemmel_alis": [], # 🟢
        "alis_sayim": [], # 📈
        "mukemmel_satis": [], # 🔵
        "satis_sayim": [] # 📉
    }

    for s in signals_today:
        symbol = s.get("symbol", "?")
        exchange = simplify_exchange(s.get("exchange", "?"))
        signal_text = str(s.get("signal", "")).strip()
        lower_signal = signal_text.lower()

        processed = False # Sinyalin işlenip işlenmediğini takip et

        # KAIRI
        if "kairi" in lower_signal and "seviyesinde" in lower_signal:
            try:
                kairi_match = re.search(r'([-+]?\d*\.?\d+)', signal_text)
                if kairi_match:
                    kairi_val = float(kairi_match.group(1))
                    entry = f"{symbol} ({exchange}): KAIRI {kairi_val:.2f}" # Değeri formatla
                    if kairi_val <= -30: kategori_map["kairi_neg30"].append(entry); processed = True
                    elif kairi_val <= -20: kategori_map["kairi_neg20"].append(entry); processed = True
                    # Diğer KAIRI değerleri özette gösterilmiyor
            except Exception as e:
                print(f"⚠️ KAIRI değeri çıkarılırken hata: {e} - Sinyal: {signal_text}")

        # Matisay
        if not processed and "matisay" in lower_signal and ("değerinde" in lower_signal or "kesti" in lower_signal): # "kesti" de eklenebilir
             try:
                matisay_match = re.search(r'([-+]?\d*\.?\d+)', signal_text)
                if matisay_match:
                    matisay_val = float(matisay_match.group(1))
                    entry = f"{symbol} ({exchange}): Matisay {matisay_val:.2f}" # Değeri formatla
                    if matisay_val < -25: kategori_map["matisay_neg25"].append(entry); processed = True
             except Exception as e:
                print(f"⚠️ Matisay değeri çıkarılırken hata: {e} - Sinyal: {signal_text}")

        # Diğer Sinyaller (Tam eşleşme)
        if not processed:
            entry = f"{symbol} ({exchange}): {signal_text}" # Orijinal sinyal metnini kullan
            if "mükemmel alış" in lower_signal: kategori_map["mukemmel_alis"].append(entry)
            elif "alış sayımı" in lower_signal: kategori_map["alis_sayim"].append(entry)
            elif "mükemmel satış" in lower_signal: kategori_map["mukemmel_satis"].append(entry)
            elif "satış sayımı" in lower_signal: kategori_map["satis_sayim"].append(entry)

    # Özet mesajını oluştur
    ozet_mesaji = [f"📊 GÜNLÜK SİNYAL ÖZETİ ({today_str}):\n"] # Tarihi ekle

    # Kategorileri işle ve mesaja ekle
    kategori_basliklari = {
        "guclu": "📊 GÜÇLÜ EŞLEŞEN SİNYALLER:", # Bunun mantığı henüz yok
        "kairi_neg30": "🔴 KAIRI ≤ -30:",
        "kairi_neg20": "🟠 KAIRI ≤ -20 (ama > -30):",
        "mukemmel_alis": "🟢 Mükemmel Alış:",
        "alis_sayim": "📈 Alış Sayımı Tamamlananlar:",
        "mukemmel_satis": "🔵 Mükemmel Satış:",
        "satis_sayim": "📉 Satış Sayımı Tamamlananlar:",
        "matisay_neg25": "🟣 Matisay < -25:"
    }

    for key, baslik in kategori_basliklari.items():
        ozet_mesaji.append(baslik)
        signals_in_category = kategori_map.get(key, []) # Guclu için de çalışır
        if signals_in_category:
            # Her sinyali kendi satırına yaz
            ozet_mesaji.extend(signals_in_category)
        else:
            ozet_mesaji.append("Yok")
        ozet_mesaji.append("") # Kategoriler arası boşluk

    # Son mesajı birleştir ve gönder (Markdown olmadan gönderelim, liste formatı daha iyi görünebilir)
    final_ozet = "\n".join(ozet_mesaji).strip()
    send_telegram_message(chat_id, final_ozet, parse_mode=None)


# --- Flask Rotaları ---

@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    """Telegram'dan gelen webhook isteklerini işler."""
    start_time = time.time()
    try:
        update = request.get_json()
        if not update: print("⚠️ Boş veya geçersiz JSON alındı."); return "error: invalid json", 400

        if "message" in update and "text" in update["message"]:
            message = update["message"]; chat_id = message["chat"]["id"]; text = message["text"]
            user_info = message.get("from", {}); username = user_info.get("username", "N/A"); first_name = user_info.get("first_name", "")

            if text.startswith('/'):
                parts = text.split(' ', 1); command = parts[0].lower(); args = parts[1].strip() if len(parts) > 1 else ""
                print(f"➡️ Komut: {command} | Args: '{args}' | Chat: {chat_id} | User: @{username} ({first_name})")

                if command == "/analiz": handle_analiz_command(chat_id, args)
                elif command == "/bist_analiz": handle_bist_analiz_command(chat_id, args)
                elif command == "/ozet": handle_ozet_command(chat_id, args) # Dinamik özeti çağır
                elif command == "/start" or command == "/help":
                     help_text = (
                         f"Merhaba {first_name}! 👋\n\nKullanılabilir komutlar:\n\n"
                         "*ABD Analizi:*\n`/analiz <Sembol1>,<Sembol2>,...`\n_(Örn: `/analiz TSLA,AAPL`)_\n\n"
                         "*BİST Analizi:*\n`/bist_analiz <Sembol>`\n_(Örn: `/bist_analiz MIATK`)_\n\n"
                         "*Diğer:*\n`/ozet` - Günlük sinyal özeti.\n`/help` - Bu yardım mesajı."
                     )
                     send_telegram_message(chat_id, help_text)
                else: send_telegram_message(chat_id, f"❓ Bilinmeyen komut: `{command}`\n/help yazın.")

        return "ok", 200

    except Exception as e:
        error_details = traceback.format_exc()
        print(f"💥 Webhook HATA: {e}\n{error_details}")
        if ADMIN_CHAT_ID:
             try: request_data = request.get_data(as_text=True)
             except Exception: request_data = "Request data could not be read."
             error_message_to_admin = f"🚨 Webhook Hatası!\n\nError: {e}\n\nTraceback:\n{error_details}\n\nRequest Data:\n{request_data[:1000]}"
             send_telegram_message(ADMIN_CHAT_ID, error_message_to_admin, parse_mode=None, avoid_self_notify=True)
        try:
             if 'message' in update and 'chat' in update['message']:
                 user_chat_id = update['message']['chat']['id']
                 send_telegram_message(user_chat_id, "⚠️ Bir hata oluştu. Yönetici bilgilendirildi.")
        except Exception as inner_e: print(f"⚠️ Kullanıcıya hata mesajı gönderirken hata: {inner_e}")
        return "error", 500
    finally:
         end_time = time.time(); print(f"⏱️ İstek işleme süresi: {end_time - start_time:.4f} saniye")

@app.route("/", methods=["GET"])
def index():
    return """<!DOCTYPE html><html><head><title>SignalCihangir Bot</title></head><body><h1>SignalCihangir Bot Aktif!</h1><p>Webhook <code>/telegram</code>, Sinyal Alıcı <code>/signal</code></p><p>Test: <a href="/test">/test</a></p></body></html>""", 200

@app.route("/test", methods=["GET"])
def test():
    message_to_admin = "✅ Bot test endpoint'i başarıyla çalıştırıldı."
    if ADMIN_CHAT_ID:
        if send_telegram_message(ADMIN_CHAT_ID, message_to_admin): return f"Test başarılı! Yöneticiye (ID: {ADMIN_CHAT_ID}) mesaj gönderildi.", 200
        else: return f"Test endpoint'i çalıştı ancak yöneticiye mesaj gönderilemedi (ID: {ADMIN_CHAT_ID}).", 500
    else: return "Test başarılı! Yönetici CHAT_ID ayarlanmadı.", 200

# Güncellenmiş Sinyal Endpoint'i (Kayıt Eklenmiş)
@app.route("/signal", methods=["POST"])
def handle_signal():
    """TradingView'dan gelen sinyal webhook'larını işler ve dosyaya kaydeder."""
    start_time = time.time()
    signal_data_for_log = {} # Kaydedilecek veriyi tutmak için
    try:
        raw_data = request.data
        if not raw_data: print("⚠️ Sinyal endpoint'ine boş veri geldi."); return "error: empty body", 400

        try:
            signal_json_str = raw_data.decode('utf-8')
            print(f"📄 Gelen sinyal (raw): {signal_json_str}")
            data = json.loads(signal_json_str)
            signal_data_for_log = data.copy() # Orijinal veriyi kopyala
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            print(f"❌ Sinyal endpoint'ine geçersiz JSON veya decode edilemeyen veri geldi: {e} - Veri: {raw_data[:200]}")
            return "error: invalid data", 400
        except Exception as e:
             print(f"❌ Sinyal parse edilirken hata: {e} - Veri: {raw_data[:200]}")
             return "error: cannot parse data", 400

        symbol = data.get("symbol")
        exchange = data.get("exchange")
        signal_text = data.get("signal")

        if not all([symbol, exchange, signal_text]): print(f"❌ Sinyal endpoint'ine eksik anahtar geldi: {data}"); return "error: missing keys", 400

        print(f"✅ Sinyal alındı: {symbol} ({exchange}) - {signal_text}")

        # --- Sinyali Dosyaya Kaydet ---
        append_to_jsonl(SIGNAL_LOG_FILE, signal_data_for_log)
        # -----------------------------

        simplified_exchange = simplify_exchange(exchange)
        signal_text_clean = str(signal_text).strip()

        tg_message = (f"📡 Yeni Sinyal Geldi:\n\n*{symbol}* ({simplified_exchange})\n📍 _{signal_text_clean}_")

        if ADMIN_CHAT_ID:
            send_telegram_message(ADMIN_CHAT_ID, tg_message, parse_mode="Markdown")
        else: print("⚠️ ADMIN_CHAT_ID ayarlanmadığı için sinyal Telegram'a gönderilemedi.")

        return "ok", 200

    except Exception as e:
        error_details = traceback.format_exc(); print(f"💥 Sinyal Endpoint HATA: {e}\n{error_details}")
        if ADMIN_CHAT_ID:
             try: request_data = request.get_data(as_text=True)
             except Exception: request_data = "Request data could not be read."
             error_message_to_admin = f"🚨 Sinyal Endpoint Hatası!\n\nError: {e}\n\nTraceback:\n{error_details}\n\nRequest Data:\n{request_data[:1000]}"
             send_telegram_message(ADMIN_CHAT_ID, error_message_to_admin, parse_mode=None, avoid_self_notify=True)
        return "error: internal server error", 500
    finally:
        end_time = time.time(); print(f"⏱️ Sinyal işleme süresi: {end_time - start_time:.4f} saniye")


# --- Sunucuyu Başlatma ---

if __name__ == "__main__":
    # ... (Başlangıç ASCII Art ve logları - Değişiklik yok) ...
    print(f" HHHHHH   EEEEEEE  RRRRRR   EEEEEEE   SSSSSS\n"
            f" H::::H   E:::::E  R::::R   E:::::E  SS::::SS\n"
            f" H::::H   E:::::E  R:::::R  E:::::E S:::::S\n"
            f" HH::HH   E:::::E  R:::::R  E:::::E S:::::S\n"
            f"   H::::H   E:::::E  RR:::::R   E:::::E  S:::::S\n"
            f"   H::::H   E:::::E   R::::R    E:::::E   S::::SS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E    SS::::SS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E     SSS::::S\n"
            f"   H::::H   E:::::E   R::::R    E:::::E       SSSSS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E       SSSSS\n"
            f"   H::::H   E:::::E   R::::R    E:::::E       SSSSS\n"
            f"   H::::H   E:::::E  RR:::::R   E:::::E       SSSSS\n"
            f" HH::HH   E:::::E  R:::::R  E:::::E S:::::S  SSSSS\n"
            f" H::::H   E:::::E  R:::::R  E:::::E S:::::S  SSSSS\n"
            f" H::::H   E:::::E  R:::::R  E:::::E SS::::SS SSSSS\n"
            f" HHHHHH   EEEEEEE  RRRRRR   EEEEEEE  SSSSSS  SSSSS\n")
    print("==============================================")
    print("✅ SignalCihangir Flask Bot Başlatılıyor...")
    print(f"🔧 Ortam: {'Production' if not os.getenv('FLASK_DEBUG') else 'Development'}")
    print(f"🔗 Dinlenen Adres: http://0.0.0.0:5000")
    print(f"📄 ABD Analiz Dosyası: {ANALIZ_FILE}")
    print(f"📄 BIST Analiz Dosyası: {BIST_ANALIZ_FILE}")
    print(f"📄 Sinyal Log Dosyası: {SIGNAL_LOG_FILE}") # Yeni log
    print(f"👤 Yönetici Chat ID: {ADMIN_CHAT_ID if ADMIN_CHAT_ID else 'Ayarlanmadı'}")
    print("==============================================")
    # Production için waitress kullan
    from waitress import serve
    serve(app, host="0.0.0.0", port=5000)
    # Geliştirme için Flask'ın kendi sunucusunu debug modunda kullanabilirsin:
    # app.run(host="0.0.0.0", port=5000, debug=True)
