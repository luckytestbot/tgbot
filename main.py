import asyncio
import websockets
import json
import datetime
import pytz
import time
import requests
from telegram import Bot
import os

# Dane dostępowe z ustawionych zmiennych środowiskowych
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HELIUS_RPC_URL = os.getenv("HELIUS_RPC_URL")

# Inicjalizacja bota Telegram
bot = Bot(token=TELEGRAM_TOKEN)

# Zbiór przechowujący już obsłużone tokeny (CA)
last_seen_cas = set()
last_seen_cas_lock = asyncio.Lock()

# Formatowanie daty
def format_simple_datetime(dt):
    return dt.strftime("%d-%m-%Y %H:%M")

# ✅ Zmodyfikowana funkcja do pobierania tokenów dev'a
async def get_token_count_by_creator(creator_address):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": "helius",
            "method": "getAssetsByCreator",
            "params": {
                "creatorAddress": creator_address,
                "onlyVerified": False,
                "page": 1,
                "limit": 2
            }
        }
        response = await asyncio.to_thread(requests.post, HELIUS_RPC_URL, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        data = response.json()
        assets = data.get("result", {}).get("items", [])
        fungible_tokens = [asset for asset in assets if asset.get("interface") == "FungibleToken"]
        return len(fungible_tokens)
    except Exception as e:
        print(f"Błąd przy pobieraniu tokenów dev'a: {e}")
        return 999

# ✅ Zmodyfikowana funkcja do pobierania transakcji (zawsze 50)
async def get_oldest_transaction_time(dev_address):
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": "helius",
            "method": "getSignaturesForAddress",
            "params": [
                dev_address,
                {"limit": 50}
            ]
        }
        response = await asyncio.to_thread(requests.post, HELIUS_RPC_URL, json=payload, headers={"Content-Type": "application/json"})
        response.raise_for_status()
        data = response.json()
        transactions = data.get("result", [])
        if not transactions:
            print(f"Brak transakcji dla dev'a {dev_address}")
            return None
        oldest_tx = transactions[-1]
        timestamp = oldest_tx.get("blockTime")
        if timestamp:
            return datetime.datetime.utcfromtimestamp(timestamp).replace(tzinfo=pytz.utc)
        else:
            print(f"Brak blockTime w transakcji dla {dev_address}")
            return None
    except Exception as e:
        print(f"Błąd przy pobieraniu transakcji: {e}")
        return None

# Emoji na podstawie różnicy czasu
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

# Obsługa tokena
async def handle_token(data):
    ca = data.get("mint")
    if not ca:
        print("Brak CA, ignoruję.")
        return

    async with last_seen_cas_lock:
        if ca in last_seen_cas:
            print(f"Token {ca} już obsłużony. Ignoruję.")
            return
        last_seen_cas.add(ca)

    print("\n--- NOWY TOKEN ---")
    print(json.dumps(data, indent=2))

    name = data.get("name", "Brak nazwy")
    symbol = data.get("symbol", "Brak symbolu")
    dev = data.get("traderPublicKey", "Brak dev'a")

    token_count = await get_token_count_by_creator(dev)
    if token_count > 2:
        print(f"Dev {dev} ma {token_count} tokenów. Ignoruję token.")
        return

    display_count = 1 if token_count == 0 else token_count
    initial_buy = data.get("initialBuy", 0)
    total_supply = 1_000_000_000
    initial_buy_percentage = (initial_buy / total_supply) * 100 if initial_buy > 0 else 0
    formatted_initial_buy = f"{initial_buy_percentage:.2f}%"

    token_creation_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    token_creation_pl = token_creation_utc.astimezone(pytz.timezone("Europe/Warsaw"))
    formatted_timestamp = format_simple_datetime(token_creation_pl)

    oldest_tx_utc = await get_oldest_transaction_time(dev)
    if oldest_tx_utc:
        oldest_tx_pl = oldest_tx_utc.astimezone(pytz.timezone("Europe/Warsaw"))
        formatted_last_tx = format_simple_datetime(oldest_tx_pl)
    else:
        formatted_last_tx = "Brak"

    emoji = get_emoji_for_time(token_creation_utc, oldest_tx_utc)
    ca_link = f"https://neo.bullx.io/terminal?chainId=1399811149&address={ca}" if ca else "Brak linku"

    message = (
        f"*new token!*\n\n"
        f"*Nazwa:* {name}\n"
        f"*Symbol:* {symbol}\n"
        f"*CA:* [{ca}]({ca_link})\n"
        f"*Dev:* [Kliknij](https://solscan.io/account/{dev})\n"
        f"*Data utworzenia:* {formatted_timestamp}\n"
        f"*Data ostatniej transakcji:* {formatted_last_tx} {emoji}\n"
        f"*Dev deployed:* {display_count}\n"
        f"*Dev initial buy:* {formatted_initial_buy}"
    )

    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown", disable_web_page_preview=True)
    print(f"Wysłano na Telegram: {name} ({symbol})")

# Nasłuch na WebSocket
async def listen_for_tokens():
    uri = "wss://pumpportal.fun/api/data"
    async with websockets.connect(uri) as websocket:
        print("Połączono z PumpPortal i nasłuchiwanie rozpoczęte...")

        payload = {"method": "subscribeNewToken"}
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
