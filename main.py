import asyncio
import websockets
import json
import datetime
import pytz
import os
import httpx
from telegram import Bot

# Dane dostępowe z ustawionych zmiennych środowiskowych
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
HELIUS_RPC_URL = os.getenv("HELIUS_RPC_URL")

bot = Bot(token=TELEGRAM_TOKEN)
last_seen_cas = set()
dev_cache = {}  # Pamięć podręczna wyników devów

def format_simple_datetime(dt):
    return dt.strftime("%d-%m-%Y %H:%M")

async def get_token_count_by_creator(client, creator_address):
    if creator_address in dev_cache:
        return dev_cache[creator_address]
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
        resp = await client.post(HELIUS_RPC_URL, json=payload)
        data = resp.json()
        assets = data.get("result", {}).get("items", [])
        fungible_tokens = [a for a in assets if a.get("interface") == "FungibleToken"]
        count = len(fungible_tokens)
        dev_cache[creator_address] = count
        return count
    except Exception as e:
        print(f"Błąd przy pobieraniu tokenów dev'a: {e}")
        return 999

async def get_oldest_transaction_time(client, dev_address):
    for limit in [50, 100]:
        try:
            payload = {
                "jsonrpc": "2.0",
                "id": "helius",
                "method": "getSignaturesForAddress",
                "params": [dev_address, {"limit": limit}]
            }
            resp = await client.post(HELIUS_RPC_URL, json=payload)
            data = resp.json()
            txs = data.get("result", [])
            if not txs:
                continue
            ts = txs[-1].get("blockTime")
            if ts:
                return datetime.datetime.utcfromtimestamp(ts).replace(tzinfo=pytz.utc)
        except Exception as e:
            print(f"Błąd przy pobieraniu transakcji: {e}")
            await asyncio.sleep(0.5)
    return None

def get_emoji_for_time(token_time, tx_time):
    if not token_time or not tx_time:
        return ""
    delta = (token_time - tx_time).total_seconds()
    if delta <= 600:
        return "🟥"
    elif delta < 86400:
        return "🟩"
    else:
        return "🟫"

async def handle_token(client, data):
    ca = data.get("mint")
    if not ca or ca in last_seen_cas:
        return
    last_seen_cas.add(ca)

    name = data.get("name", "Brak nazwy")
    symbol = data.get("symbol", "Brak symbolu")
    dev = data.get("traderPublicKey", "Brak dev'a")

    token_count = await get_token_count_by_creator(client, dev)
    if token_count > 2:
        return

    display_count = 1 if token_count == 0 else token_count
    initial_buy = data.get("initialBuy", 0)
    total_supply = 1_000_000_000
    init_buy_pct = (initial_buy / total_supply) * 100 if initial_buy else 0

    now_utc = datetime.datetime.utcnow().replace(tzinfo=pytz.utc)
    token_time_pl = now_utc.astimezone(pytz.timezone("Europe/Warsaw"))
    formatted_now = format_simple_datetime(token_time_pl)

    oldest_tx = await get_oldest_transaction_time(client, dev)
    if oldest_tx:
        oldest_tx_pl = oldest_tx.astimezone(pytz.timezone("Europe/Warsaw"))
        formatted_tx = format_simple_datetime(oldest_tx_pl)
    else:
        formatted_tx = "Brak"

    emoji = get_emoji_for_time(now_utc, oldest_tx)
    ca_link = f"https://neo.bullx.io/terminal?chainId=1399811149&address={ca}"

    msg = (
        f"*new token!*\n\n"
        f"*Nazwa:* {name}\n"
        f"*Symbol:* {symbol}\n"
        f"*CA:* [{ca}]({ca_link})\n"
        f"*Dev:* [Kliknij](https://solscan.io/account/{dev})\n"
        f"*Data utworzenia:* {formatted_now}\n"
        f"*Data ostatniej transakcji:* {formatted_tx} {emoji}\n"
        f"*Dev deployed:* {display_count}\n"
        f"*Dev initial buy:* {init_buy_pct:.2f}%"
    )

    await bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode="Markdown", disable_web_page_preview=True)
    print(f"Wysłano: {name} ({symbol})")

async def listen_for_tokens():
    uri = "wss://pumpportal.fun/api/data"
    async with websockets.connect(uri) as ws, httpx.AsyncClient(timeout=8) as client:
        print("Połączono z WebSocketem...")
        await ws.send(json.dumps({"method": "subscribeNewToken"}))

        while True:
            try:
                msg = await ws.recv()
                data = json.loads(msg)
                if data.get("txType") == "create":
                    asyncio.create_task(handle_token(client, data))
            except Exception as e:
                print(f"Błąd: {e}")
                await asyncio.sleep(2)

def main():
    asyncio.run(listen_for_tokens())

if __name__ == "__main__":
    main()