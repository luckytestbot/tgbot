import requests
import asyncio
from telegram import Bot
import datetime
import pytz
from solana.rpc.api import Client
import os  # <-- To powinno być tutaj, nie w komentarzu

# Twoje dane (wstawione jak prosiłeś)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = "1729940092"
bot = Bot(token=TELEGRAM_TOKEN)
# API PumpFun (pojedynczy nowy token)
API_URL = "https://api.pumpfunapi.org/pumpfun/new/tokens"

# Przechowywane tokeny, by nie duplikować wysyłek
sent_tokens = set()

# Ustawienie klienta Solany (do łączenia się z siecią Solany)
solana_client = Client("https://api.mainnet-beta.solana.com")  # Domyślny RPC

# Funkcja do pobierania daty pierwszej transakcji twórcy z Solana SDK
def get_first_transaction_time(creator_address):
    try:
        # Pobieranie transakcji dla danego adresu
        transactions = solana_client.get_signatures_for_address(creator_address, limit=100)

        if not transactions['result']:
            return "Brak transakcji"

        # Pobranie najstarszej transakcji
        first_tx = transactions['result'][-1]
        timestamp = first_tx['blockTime']

        # Konwersja timestampu na czas w Polsce
        timestamp_utc = datetime.datetime.utcfromtimestamp(timestamp).replace(tzinfo=pytz.utc)
        timestamp_pl = timestamp_utc.astimezone(pytz.timezone("Europe/Warsaw"))

        # Zwracamy czas bez sekund
        return timestamp_pl.strftime("%Y-%m-%d %H:%M")

    except Exception as e:
        print(f"Nie udało się pobrać transakcji dla adresu {creator_address}: {e}")
        return "Błąd pobierania transakcji"

# Funkcja do dodawania emoji w zależności od czasu
def get_emoji_for_time(first_tx_time):
    try:
        # Sprawdzanie, ile czasu minęło od pierwszej transakcji
        current_time = datetime.datetime.now(pytz.timezone("Europe/Warsaw"))

        # Upewniamy się, że obie daty są z tą samą strefą czasową
        first_tx_time_obj = datetime.datetime.strptime(first_tx_time, "%Y-%m-%d %H:%M")
        first_tx_time_obj = pytz.timezone("Europe/Warsaw").localize(first_tx_time_obj)  # Dodajemy strefę czasową

        # Obliczanie różnicy w czasie
        time_diff = current_time - first_tx_time_obj

        # Jeśli minęło mniej niż 5 minut, dodajemy 🟥
        if time_diff.total_seconds() < 300:
            return "🟥"
        # Jeśli minęło od 5 minut do 24 godzin, dodajemy 🟩
        elif time_diff.total_seconds() < 86400:
            return "🟩"
        # Jeśli minęło powyżej 24 godzin, dodajemy 🟫
        else:
            return "🟫"
    except Exception as e:
        print(f"Błąd przy obliczaniu czasu: {e}")
        return ""

async def fetch_and_notify():
    while True:
        try:
            response = requests.get(API_URL, timeout=10)
            response.raise_for_status()

            token = response.json()  # Oczekiwany pojedynczy obiekt

            ca = token.get("mint")
            name = token.get("name", "Brak nazwy")
            symbol = token.get("symbol", "Brak symbolu")
            creator = token.get("dev", "Brak twórcy")  # Twórca jest w polu 'dev'
            timestamp = token.get("timestamp", "Brak daty utworzenia")

            # Sprawdzanie daty pierwszej transakcji twórcy
            first_tx_time = get_first_transaction_time(creator)

            # Tworzymy link do NEO BullX z CA
            if ca:
                ca_link = f"https://neo.bullx.io/terminal?chainId=1399811149&address={ca}"
            else:
                ca_link = "Brak linku do CA"

            # Dodajemy emoji do czasu transakcji
            emoji = get_emoji_for_time(first_tx_time)

            # Formatowanie daty utworzenia, aby usunąć "T" z daty oraz przekształcenie na czas w Polsce
            if timestamp != "Brak daty utworzenia":
                # Pobranie daty utworzenia z API i jej konwersja na czas UTC
                timestamp_utc = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
                # Dodajemy 6 godzin, ponieważ data utworzenia jest w UTC
                timestamp_utc_plus_6 = timestamp_utc + datetime.timedelta(hours=6)
                # Konwertujemy na polski czas
                timestamp_pl = timestamp_utc_plus_6.replace(tzinfo=pytz.utc).astimezone(pytz.timezone("Europe/Warsaw"))
                formatted_timestamp = timestamp_pl.strftime("%Y-%m-%d %H:%M")
            else:
                formatted_timestamp = "Brak daty utworzenia"

            # Wiadomość do wysłania na Telegram
            message = (
                f"*Nowy token wykryty!*\n\n"
                f"*Nazwa:* {name}\n"
                f"*Symbol:* {symbol}\n"
                f"*CA:* [{ca}]({ca_link})\n"  # Link do CA (klikany)
                f"*Twórca:* [Kliknij tutaj](https://solscan.io/account/{creator})\n"  # Link do twórcy
                f"*Data utworzenia:* {formatted_timestamp}\n"  # Teraz w polskim czasie
                f"*Data pierwszej transakcji twórcy:* {first_tx_time} {emoji}\n"
            )

            # Jeśli token jeszcze nie został wysłany, wyślij go na Telegram z wyłączonym podglądem linków
            if ca and ca not in sent_tokens:
                await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown", disable_web_page_preview=True)
                sent_tokens.add(ca)
                print(f"Wysłano: {name} ({symbol})")

        except Exception as e:
            print(f"Błąd pobierania danych: {e}")

        await asyncio.sleep(5)

def main():
    asyncio.run(fetch_and_notify())

# Start bota
main()