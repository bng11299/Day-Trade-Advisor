advisor_list = set()

def add_to_advisor(ticker):
    advisor_list.add(ticker)

def remove_from_advisor(ticker):
    advisor_list.discard(ticker)

def get_advisor_list():
    return list(advisor_list)
