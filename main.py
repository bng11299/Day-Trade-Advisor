{
 "cells": [
  {
   "metadata": {
    "ExecuteTime": {
     "end_time": "2025-08-07T19:06:18.328295Z",
     "start_time": "2025-08-07T19:06:10.650758Z"
    }
   },
   "cell_type": "code",
   "source": [
    "import yfinance as yf\n",
    "import pandas as pd\n",
    "import pandas_ta as ta\n",
    "\n",
    "# --- Define your watchlist here ---\n",
    "watchlist = [\"AAPL\", \"MSFT\", \"NVDA\"]  # Modify this list as desired\n",
    "\n",
    "# --- Strategy Parameters ---\n",
    "start_date = \"2024-01-01\"\n",
    "end_date = \"2024-08-01\"\n",
    "\n",
    "# --- Function to analyze a single stock ---\n",
    "def analyze_stock(ticker):\n",
    "    print(f\"\\nAnalyzing {ticker}...\")\n",
    "\n",
    "    df = yf.download(ticker, start=start_date, end=end_date, auto_adjust=True)\n",
    "\n",
    "    if df.empty:\n",
    "        print(f\"⚠️ No data for {ticker}\")\n",
    "        return None\n",
    "\n",
    "    # Clean column names if needed\n",
    "    if isinstance(df.columns, pd.MultiIndex):\n",
    "        df.columns = [col[0].replace(f\"_{ticker}\", \"\") for col in df.columns]\n",
    "    df.columns = [col.replace(f\"_{ticker}\", \"\") for col in df.columns]\n",
    "\n",
    "    # Add indicators\n",
    "    df.ta.sma(length=20, append=True)\n",
    "    df.ta.sma(length=50, append=True)\n",
    "\n",
    "    # Detect trend\n",
    "    def detect_trend(row):\n",
    "        if row['Close'] > row['SMA_20'] and row['SMA_20'] > row['SMA_50']:\n",
    "            return \"Uptrend\"\n",
    "        elif row['Close'] < row['SMA_20'] and row['SMA_20'] < row['SMA_50']:\n",
    "            return \"Downtrend\"\n",
    "        else:\n",
    "            return \"Sideways\"\n",
    "\n",
    "    df['Trend'] = df.apply(detect_trend, axis=1)\n",
    "\n",
    "    # Signal generation\n",
    "    df['Signal'] = 0\n",
    "    for i in range(1, len(df)):\n",
    "        prev_trend = df.iloc[i-1]['Trend']\n",
    "        curr_trend = df.iloc[i]['Trend']\n",
    "\n",
    "        if prev_trend != \"Uptrend\" and curr_trend == \"Uptrend\":\n",
    "            df.at[df.index[i], 'Signal'] = 1  # Buy\n",
    "        elif prev_trend == \"Uptrend\" and curr_trend != \"Uptrend\":\n",
    "            df.at[df.index[i], 'Signal'] = -1  # Sell\n",
    "\n",
    "    # Extract trade signals\n",
    "    trades = df[df['Signal'] != 0][['Close', 'Signal']]\n",
    "    trades['Action'] = trades['Signal'].map({1: 'BUY', -1: 'SELL'})\n",
    "\n",
    "    print(trades[['Close', 'Action']])\n",
    "    return trades\n",
    "\n",
    "# --- Loop through watchlist ---\n",
    "for ticker in watchlist:\n",
    "    analyze_stock(ticker)\n"
   ],
   "id": "fbc121e30a2defb3",
   "outputs": [
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "\n",
      "Analyzing AAPL...\n"
     ]
    },
    {
     "name": "stderr",
     "output_type": "stream",
     "text": [
      "[*********************100%***********************]  1 of 1 completed\n"
     ]
    },
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "                Close Action\n",
      "Date                        \n",
      "2024-05-08  181.64299    BUY\n",
      "2024-07-24  217.52269   SELL\n",
      "\n",
      "Analyzing MSFT...\n"
     ]
    },
    {
     "name": "stderr",
     "output_type": "stream",
     "text": [
      "[*********************100%***********************]  1 of 1 completed\n"
     ]
    },
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "                 Close Action\n",
      "Date                         \n",
      "2024-03-13  411.199951    BUY\n",
      "2024-04-04  413.953857   SELL\n",
      "2024-04-05  421.522064    BUY\n",
      "2024-04-12  417.936096   SELL\n",
      "2024-05-29  425.904633    BUY\n",
      "2024-05-30  411.514923   SELL\n",
      "2024-06-05  420.783875    BUY\n",
      "2024-07-15  450.505981   SELL\n",
      "\n",
      "Analyzing NVDA...\n"
     ]
    },
    {
     "name": "stderr",
     "output_type": "stream",
     "text": [
      "[*********************100%***********************]  1 of 1 completed\n"
     ]
    },
    {
     "name": "stdout",
     "output_type": "stream",
     "text": [
      "                 Close Action\n",
      "Date                         \n",
      "2024-03-13   90.851837    BUY\n",
      "2024-04-02   89.416405   SELL\n",
      "2024-04-11   90.579933    BUY\n",
      "2024-04-12   88.150909   SELL\n",
      "2024-04-26   87.700096    BUY\n",
      "2024-04-30   86.367630   SELL\n",
      "2024-05-20   94.742287    BUY\n",
      "2024-06-24  118.072693   SELL\n",
      "2024-06-25  126.050171    BUY\n",
      "2024-06-28  123.500984   SELL\n",
      "2024-07-03  128.239487    BUY\n",
      "2024-07-11  127.359756   SELL\n",
      "2024-07-12  129.199188    BUY\n",
      "2024-07-16  126.320099   SELL\n"
     ]
    }
   ],
   "execution_count": 15
  },
  {
   "metadata": {},
   "cell_type": "code",
   "outputs": [],
   "execution_count": null,
   "source": "",
   "id": "3715c0307e73d63d"
  }
 ],
 "metadata": {
  "kernelspec": {
   "display_name": "Python 3",
   "language": "python",
   "name": "python3"
  },
  "language_info": {
   "codemirror_mode": {
    "name": "ipython",
    "version": 2
   },
   "file_extension": ".py",
   "mimetype": "text/x-python",
   "name": "python",
   "nbconvert_exporter": "python",
   "pygments_lexer": "ipython2",
   "version": "2.7.6"
  }
 },
 "nbformat": 4,
 "nbformat_minor": 5
}
