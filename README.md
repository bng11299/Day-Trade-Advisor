Day Trade Advisor

📈 Stock Trading Advisor built in Python to help users monitor and analyze stocks with momentum-based strategies. Users can manually maintain a watchlist and get real-time trend and trade signal recommendations.

Features

Add or remove stocks from a watchlist.

Analyze multiple stocks using a momentum strategy (e.g., SMA crossover).

Continuous monitoring of the watchlist with real-time trend detection.

Generates BUY/SELL recommendations based on selected strategies.

Multi-threaded interface for simultaneous user input and stock analysis.

Installation

Clone the repository:

git clone https://github.com/yourusername/Day-Trade-Advisor.git
cd Day-Trade-Advisor


(Recommended) Create a virtual environment:

python -m venv .venv
.\.venv\Scripts\activate  # Windows
# or
source .venv/bin/activate  # macOS/Linux


Install required libraries:

pip install -r requirements.txt


If requirements.txt is not provided, install dependencies manually:

pip install yfinance pandas pandas_ta numpy

Usage
python main.py


You can enter commands in the terminal:

add SYMBOL → Add a stock to the watchlist.

remove SYMBOL → Remove a stock from the watchlist.

list → Display the current watchlist.

quit → Exit the program.

The advisor continuously analyzes the watchlist every 2 minutes and outputs trend and signal updates.
