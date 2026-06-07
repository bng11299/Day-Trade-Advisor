import json
import os

WATCHLIST_FILE = os.path.join(os.path.dirname(__file__), "watchlist.json")


def load() -> list[str]:
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE) as f:
        return json.load(f)


def save(symbols: list[str]):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(symbols, f, indent=2)


def add(symbol: str) -> bool:
    symbols = load()
    if symbol in symbols:
        return False
    symbols.append(symbol)
    save(symbols)
    return True


def remove(symbol: str) -> bool:
    symbols = load()
    if symbol not in symbols:
        return False
    symbols.remove(symbol)
    save(symbols)
    return True
