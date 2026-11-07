"""Tight/Nit test opponent: folds quickly to bets, plays only top 25% hands."""
import sys, json

RANKS = "23456789TJQKA"

def choose_action(req):
    legal = req["legal_actions"]
    to_call = req["to_call"]
    hole = req.get("hole_cards", [])
    
    # Check is always free
    if "check" in legal:
        return {"type": "action", "action": "check"}
        
    # Folds to any bet unless it's tiny
    if to_call <= 2:
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
