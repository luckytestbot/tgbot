import requests
import asyncio
from telegram import Bot
import datetime
import pytz
from solana.rpc.api import Client
import time
import os

# Dane dostępowe z zmiennych środowiskowych
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HELIUS_RPC_URL = os.getenv("HELIUS_RPC_URL")
bot = Bot(token=TELEGRAM_TOKEN)

# API
PUMPFUN_URL = "https://api.pumpfunapi.org/pumpfun/new/tokens"

# Do unikania duplikatów
sent_tokens = set()

# Solana client
solana_client = Client("https://api.mainnet-beta.solana.com")

def get_token_count_by_creator(creator_address):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": "helius",
            "method": "getAssetsByCreator",
            "params": {
                "creatorAddress": creator_address,
                "onlyVerified": False,
                "page": 1,
                "limit": 1000
            }
        }

        response = requests.post(HELIUS_RPC_URL, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        data = response.json()

        assets = data.get("result", {}).get("items", [])
        fungible_tokens = [asset for asset in assets if asset.get("interface") == "FungibleToken"]
        return len(fungible_tokens)
    except Exception:
        return "Brak danych"

def get_first_transaction_time(dev_address):
    attempts = 0
    while attempts < 5:
        try:
            # Sprawdzamy 50 transakcji
            transactions = solana_client.get_signatures_for_address(dev_address, limit=50)
            if not transactions['result']:
                raise Exception("Brak transakcji")
            first_tx = transactions['result'][-1]
            timestamp = first_tx['blockTime']
            timestamp_utc = datetime.datetime.utcfromtimestamp(timestamp).replace(tzinfo=pytz.utc)
            timestamp_pl = timestamp_utc.astimezone(pytz.timezone("Europe/Warsaw"))
            return timestamp_pl.strftime("%Y-%m-%d %H:%M")
        except Exception as e:
            print(f"Błąd przy pobieraniu transakcji: {e}")
            attempts += 1
            time.sleep(2)  # Poczekaj 2 sekundy przed ponowną próbą
    return "Brak transakcji"  # Jeśli próby zawiodły, zwróć komunikat

def get_emoji_for_time(first_tx_time):
    try:
        current_time = datetime.datetime.now(pytz.timezone("Europe/Warsaw"))
        first_tx_time_obj = datetime.datetime.strptime(first_tx_time, "%Y-%m-%d %H:%M")
        first_tx_time_obj = pytz.timezone("Europe/Warsaw").localize(first_tx_time_obj)
        time_diff = current_time - first_tx_time_obj

        if time_diff.total_seconds() < 300:  # Mniej niż 5 minut
            return "🟥"
        elif 600 <= time_diff.total_seconds() < 86400:  # Więcej niż 10 minut, ale mniej niż 24 godziny
            return "🟩"
        else:  # Ponad 24 godziny
            return "🟫"
    except Exception:
        return ""  # Jeśli wystąpi błąd, nie zwracamy żadnego emoji

async def fetch_and_notify():
    while True:
        try:
            response = requests.get(PUMPFUN_URL, timeout=10)
            response.raise_for_status()
            token = response.json()

            ca = token.get("mint")
            name = token.get("name", "Brak nazwy")
            symbol = token.get("symbol", "Brak symbolu")
            dev = token.get("dev", "Brak dev'a")
            timestamp = token.get("timestamp", "Brak daty")

            # Ponowne próby uzyskania danych o pierwszej transakcji w przypadku błędów
            first_tx_time = get_first_transaction_time(dev)
            if first_tx_time == "Brak transakcji":
                first_tx_time = "Brak"

            emoji = get_emoji_for_time(first_tx_time)
            token_count = get_token_count_by_creator(dev)

            if ca:
                ca_link = f"https://neo.bullx.io/terminal?chainId=1399811149&address={ca}"
            else:
                ca_link = "Brak linku"

            if timestamp != "Brak daty":
                timestamp_utc = datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
                timestamp_utc_plus_6 = timestamp_utc + datetime.timedelta(hours=6)
                timestamp_pl = timestamp_utc_plus_6.replace(tzinfo=pytz.utc).astimezone(pytz.timezone("Europe/Warsaw"))
                formatted_timestamp = timestamp_pl.strftime("%Y-%m-%d %H:%M")
            else:
                formatted_timestamp = "Brak"

            message = (
                f"*new token!*\n\n"
                f"*Nazwa:* {name}\n"
                f"*Symbol:* {symbol}\n"
                f"*CA:* [{ca}]({ca_link})\n"
                f"*Dev:* [Kliknij](https://solscan.io/account/{dev})\n"
                f"*Data utworzenia:* {formatted_timestamp}\n"
                f"*Data 1. transakcji:* {first_tx_time} {emoji}\n"
                f"*Dev deployed:* {token_count}"
            )

            if ca and ca not in sent_tokens:
                await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown", disable_web_page_preview=True)
                sent_tokens.add(ca)
                print(f"Wysłano: {name} ({symbol})")

        except Exception as e:
            print(f"Błąd pobierania danych: {e}")

        # Zwiększamy czas między zapytaniami na 5 sekund, aby zwiększyć niezawodność
        await asyncio.sleep(5)

def main():
    asyncio.run(fetch_and_notify())

main()