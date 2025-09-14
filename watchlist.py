import json
import os

WATCHLIST_FILE = "watchlist.json"

def load_watchlist():
    if not os.path.exists(WATCHLIST_FILE):
        return []
    with open(WATCHLIST_FILE, "r") as f:
        return json.load(f)

def save_watchlist(stocks):
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(stocks, f, indent=2)

def add_stock(symbol):
    stocks = load_watchlist()
    if symbol not in stocks:
        stocks.append(symbol)
        save_watchlist(stocks)

def remove_stock(symbol):
    stocks = load_watchlist()
    if symbol in stocks:
        stocks.remove(symbol)
        save_watchlist(stocks)
