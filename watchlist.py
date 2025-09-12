def get_watchlist():
    # Hardcoded for now, but you could load from a file or DB later
    return ["AAPL", "MSFT", "TSLA"]

def add_to_watchlist(ticker, watchlist):
    if ticker not in watchlist:
        watchlist.append(ticker)
    return watchlist
