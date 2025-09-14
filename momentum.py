import yfinance as yf
import pandas as pd

class MomentumStrategy:
    def analyze(self, symbol):
        try:
            # Download 1 day of 1-minute interval data
            data = yf.download(symbol, period="1d", interval="1m", progress=False)

            if not isinstance(data, pd.DataFrame) or data.empty:
                return False  # No data available

            # Calculate price movement (momentum)
            recent = data['Close'].iloc[-1]
            prev = data['Close'].iloc[0]
            change = (recent - prev) / prev

            # If price changed by more than 2% in the day, consider it momentum
            return abs(change) > 0.02

        except Exception as e:
            print(f"⚠️ Error analyzing {symbol}: {e}")
            return False
