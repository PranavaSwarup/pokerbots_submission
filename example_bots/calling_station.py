"""Calling Station: calls almost everything, rarely folds, never raises bluffs."""
import sys, json, random

RANKS = "23456789TJQKA"

def choose_action(req):
    legal = req["legal_actions"]
    to_call = req["to_call"]

    # Always check if free
    if "check" in legal:
        return {"type": "action", "action": "check"}

    # Only fold if the bet is enormous (> 60% of stack)
    stack = req.get("my_stack", 200)
    if to_call > stack * 0.60 and random.random() < 0.50:
        return {"type": "action", "action": "fold"}

    # Call everything else - almost never raise
    if "call" in legal:
        if "raise" in legal and random.random() < 0.05:
            target = req["opp_bet"] + int(0.5 * (req["pot"] + to_call))
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        return {"type": "action", "action": "call"}

    return {"type": "action", "action": "fold"}

def choose_discard(req):
    cards = req["hole_cards"]
    # Discard the lowest rank card
    worst = min(cards, key=lambda c: RANKS.index(c[0]))
    return {"type": "discard", "card": worst}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        t = msg.get("type")
        if t == "action_request":
            reply = choose_action(msg)
        elif t == "discard_request":
            reply = choose_discard(msg)
        elif t == "match_end":
            break
        else:
            continue
        print(json.dumps(reply), flush=True)

if __name__ == "__main__":
    main()

