"""
All-In Stress-Test Opponent Bot for Pokerbots (Synergy '26 @ IIIT Bangalore).
Aggressively shoves (max_raise) or calls every action to test stack preservation.
"""
import sys
import json
import random

RANKS = "23456789TJQKA"

def choose_action(req):
    legal = req["legal_actions"]
    street = req["street"]
    to_call = req["to_call"]
    max_raise = req.get("max_raise", 0)
    min_raise = req.get("min_raise", 0)
    
    # Aggressively shove/raise all-in 70% of the time on preflop/flop, 50% on turn/river if raise is legal
    if "raise" in legal:
        prob = 0.70 if street in ("preflop", "flop") else 0.50
        if random.random() < prob:
            # Force an all-in shove (max_raise) to test your bot's stack preservation
            amount = max_raise
            return {"type": "action", "action": "raise", "amount": amount}
            
    if "check" in legal:
        return {"type": "action", "action": "check"}
        
    if "call" in legal:
        # Call 90% of the time facing bets (acts like an absolute calling station / maniac)
        if random.random() < 0.90 or to_call <= 10:
            return {"type": "action", "action": "call"}
            
    return {"type": "action", "action": "fold"}

def choose_discard(req):
    cards = req["hole_cards"]
    # Standard baseline discard: lowest rank card
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