"""Aggressive test opponent: raises frequently, c-bets flop, bluffs turns."""
import sys, json, random

RANKS = "23456789TJQKA"

def choose_action(req):
    legal = req["legal_actions"]
    street = req["street"]
    to_call = req["to_call"]
    
    if "raise" in legal:
        # Very aggressive: 60% raise on preflop/flop, 40% on turn/river
        prob = 0.60 if street in ("preflop", "flop") else 0.40
        if random.random() < prob:
            # Sizable raise
            target = req["opp_bet"] + int(0.75 * (req["pot"] + to_call))
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
            
    if "check" in legal:
        return {"type": "action", "action": "check"}
    if "call" in legal:
        # Call 70% of the time facing bet
        if random.random() < 0.70 or to_call <= 6:
            return {"type": "action", "action": "call"}
    return {"type": "action", "action": "fold"}

def choose_discard(req):
    cards = req["hole_cards"]
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
