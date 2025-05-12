import asyncio
import websockets
import json
import datetime
import pytz
import time
import requests
import os
from telegram import Bot
from solana.rpc.api import Client
from dotenv import load_dotenv

# Ładuj zmienne środowiskowe z pliku .env
load_dotenv()

# Dane dostępowe z zmiennych środowiskowych
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HELIUS_RPC_URL = os.getenv("HELIUS_RPC_URL")

bot = Bot(token=TELEGRAM_TOKEN)
solana_client = Client("https://api.mainnet-beta.solana.com")

def format_simple_datetime(dt):
    return dt.strftime("%d-%m-%Y %H:%M")

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
    except Exception as e:
        print(f"Błąd przy pobieraniu tokenów dev'a: {e}")
        return 999

def get_oldest_transaction_time(dev_address):
    attempts = 0
    while attempts < 3:
        try:
            transactions = solana_client.get_signatures_for_address(dev_address, limit=50)
            if not transactions['result']:
                print(f"Brak transakcji dla dev'a {dev_address}")
                return None
            oldest_tx = transactions['result'][-1]
            timestamp = oldest_tx['blockTime']
            return datetime.datetime.utcfromtimestamp(timestamp).replace(tzinfo=pytz.utc)
        except Exception as e:
            attempts += 1
            time.sleep(1)
    return None

def get_emoji_for_time(token_creation_utc, oldest_tx_utc):
    if not token_creation_utc or not oldest_tx_utc:
        return ""
    delta = token_creation_utc - oldest_tx_utc
    seconds = delta.total_seconds()
    if seconds <= 600:
        return "🟥"
    elif 600 < seconds < 86400:
        return "🟩"
    elif seconds >= 86400:
        return "🟫"
    return ""

async def handle_token(data):
    print("\n--- NOWY TOKEN ---")
    print(json.dumps(data, indent=2))

    ca = data.get("mint")
    name = data.get("name", "Brak nazwy")
    symbol = data.get("symbol", "Brak symbolu")
    dev = data.get("traderPublicKey", "Brak dev'a")

    # Pobierz liczbę tokenów twórcy
    token_count = get_token_count_by_creator(dev)

    # Jeśli liczba tokenów twórcy jest większa niż 2, nie przetwarzaj dalej
    if token_count > 2:
        print(f"Dev {dev} ma {token_count} tokenów. Ignoruję token.")
        return  # Zakończ funkcję bez dalszego przetwarzania

    # Jeśli liczba tokenów twórcy wynosi 0, ustaw na 1
    display_count = 1 if token_count == 0 else token_count

    # Oblicz procent initial buy (zakup deva w odniesieniu do całkowitej podaży)
    initial_buy = data.get("initialBuy", 0)  # Wartość zakupu deva z logów
    total_supply = 1_000_000_000  # Maksymalna podaż tokenów, np. 1 miliard

    if initial_buy > 0:
        initial_buy_percentage = (initial_buy / total_supply) * 100
    else:
        initial_buy_percentage = 0

    # Sformatuj procent do dwóch miejsc po przecinku
    formatted_initial_buy = f"{initial_buy_percentage:.2f}%"

    # Pobierz datę utworzenia tokena
    timestamp_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    token_creation_utc = timestamp_utc
    token_creation_pl = token_creation_utc.astimezone(pytz.timezone("Europe/Warsaw"))
    formatted_timestamp = format_simple_datetime(token_creation_pl)

    oldest_tx_utc = get_oldest_transaction_time(dev)
    if oldest_tx_utc:
        oldest_tx_pl = oldest_tx_utc.astimezone(pytz.timezone("Europe/Warsaw"))
        formatted_last_tx = format_simple_datetime(oldest_tx_pl)
    else:
        formatted_last_tx = "Brak"

    emoji = get_emoji_for_time(token_creation_utc, oldest_tx_utc)

    ca_link = f"https://neo.bullx.io/terminal?chainId=1399811149&address={ca}" if ca else "Brak linku"

    # Przygotowanie wiadomości do wysłania na Telegram
    message = (
        f"*new token!*\n\n"
        f"*Nazwa:* {name}\n"
        f"*Symbol:* {symbol}\n"
        f"*CA:* [{ca}]({ca_link})\n"
        f"*Dev:* [Kliknij](https://solscan.io/account/{dev})\n"
        f"*Data utworzenia:* {formatted_timestamp}\n"
        f"*Data ostatniej transakcji:* {formatted_last_tx} {emoji}\n"
        f"*Dev deployed:* {display_count}\n"
        f"*Dev initial buy:* {formatted_initial_buy}"  # Dodanie informacji o procencie zakupu deva
    )

    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown", disable_web_page_preview=True)
    print(f"Wysłano na Telegram: {name} ({symbol})")

async def listen_for_tokens():
    uri = "wss://pumpportal.fun/api/data"
    async with websockets.connect(uri) as websocket:
        print("Połączono z PumpPortal i nasłuchiwanie rozpoczęte...")

        # Subskrypcja dla nowych tokenów
        payload = {
            "method": "subscribeNewToken",
        }
        await websocket.send(json.dumps(payload))

        while True:
            try:
                message = await websocket.recv()
                data = json.loads(message)

                if data.get("txType") == "create":
                    await handle_token(data)

            except websockets.ConnectionClosed:
                print("Połączenie WebSocket zostało zamknięte. Próba ponownego połączenia...")
                await asyncio.sleep(5)
                return await listen_for_tokens()
            except Exception as e:
                print(f"Błąd: {e}")
                await asyncio.sleep(1)

def main():
    asyncio.run(listen_for_tokens())

if __name__ == "__main__":
    main()