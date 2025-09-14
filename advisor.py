import json
import os
import yfinance as yf
import pandas as pd
from strategies.momentum import MomentumStrategy

class Advisor:
    def __init__(self):
        self.watchlist_file = "watchlist.json"
        self.watchlist = self.load_watchlist()
        self.advisor_list = []
        self.strategy = MomentumStrategy()
        self.volatility_threshold = 0.02  # 2% daily movement

    def load_watchlist(self):
        if os.path.exists(self.watchlist_file):
            with open(self.watchlist_file, "r") as f:
                return json.load(f)
        return []

    def save_watchlist(self):
        with open(self.watchlist_file, "w") as f:
            json.dump(self.watchlist, f)

    def update_advisor_list(self):
        active = []
        for symbol in self.watchlist:
            try:
                df = yf.download(symbol, period="5d", interval="1d", progress=False)
                if df.empty or len(df) < 2:
                    continue
                df['Return'] = df['Close'].pct_change()
                recent_vol = df['Return'].std()
                if recent_vol is not None and recent_vol > self.volatility_threshold:
                    active.append(symbol)
            except Exception as e:
                print(f"⚠️ Error checking activity for {symbol}: {e}")
        self.advisor_list = active

    def run_analysis(self):
        self.update_advisor_list()

        if not self.advisor_list:
            print("📭 No active stocks in advisor list.")
            return

        print(f"📌 Advisor list: {self.advisor_list}")
        for symbol in self.advisor_list:
            try:
                signal = self.strategy.analyze(symbol)
                print(f"📊 {symbol}: {signal}")
            except Exception as e:
                print(f"⚠️ Error analyzing {symbol}: {e}")
