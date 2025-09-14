from advisor import Advisor
import threading
import time

advisor = Advisor()

def user_input_loop():
    """Threaded loop to handle user input."""
    while True:
        try:
            cmd = input().strip().split()
            if not cmd:
                continue

            action = cmd[0].lower()
            if action == "add" and len(cmd) > 1:
                ticker = cmd[1].upper()
                if ticker not in advisor.watchlist:
                    advisor.watchlist.append(ticker)
                    print(f"✅ Added {ticker} to watchlist")
                else:
                    print(f"⚠️ {ticker} is already in watchlist")

            elif action == "remove" and len(cmd) > 1:
                ticker = cmd[1].upper()
                if ticker in advisor.watchlist:
                    advisor.watchlist.remove(ticker)
                    print(f"❌ Removed {ticker} from watchlist")
                else:
                    print(f"⚠️ {ticker} not found in watchlist")

            elif action == "list":
                print("📋 Current watchlist:", advisor.watchlist)

            elif action == "quit":
                print("Exiting...")
                break

            else:
                print("❗ Unknown command. Use 'add SYMBOL', 'remove SYMBOL', 'list', or 'quit'.")

        except EOFError:
            break
        except KeyboardInterrupt:
            break

def run():
    """Continuous analysis loop."""
    # Start user input in a separate thread
    threading.Thread(target=user_input_loop, daemon=True).start()

    print("📈 Stock Advisor running... analyzing every 2 minutes.")

    try:
        while True:
            if advisor.watchlist:
                advisor.run_analysis()
            else:
                print("📭 No stocks in watchlist.")
            time.sleep(120)  # 2 minutes
    except KeyboardInterrupt:
        print("\nStopped by user.")

if __name__ == "__main__":
    print("📈 Stock Advisor started.")
    print("Type 'add SYMBOL', 'remove SYMBOL', 'list', or 'quit'.")
    run()
