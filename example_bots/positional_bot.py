"""
Positional Bot: plays tighter OOP (out of position), looser in position.
Raises value hands aggressively, folds marginal hands to pressure.
Uses street + position + pot-odds to make decisions.
"""
import sys, json, random

RANKS = "23456789TJQKA"

def hand_strength(hole_cards):
    """Simple hand strength: pair rank or high card rank sum."""
    if len(hole_cards) < 2:
        return 0
    ranks = sorted([RANKS.index(c[0]) for c in hole_cards], reverse=True)
    # Pairs score higher
    if len(set(r for r in ranks)) < len(ranks):
        # has at least one pair
        from collections import Counter
        cnt = Counter(RANKS.index(c[0]) for c in hole_cards)
        pair_rank = max(r for r, n in cnt.items() if n >= 2)
        return 20 + pair_rank
    return ranks[0] * 1.5 + ranks[1]

def choose_action(req):
    legal = req["legal_actions"]
    street = req["street"]
    to_call = req["to_call"]
    pot = req["pot"]
    my_stack = req.get("my_stack", 200)
    hole = req.get("hole_cards", [])
    seat = req.get("my_seat", "big_blind")  # positional info if available

    # Check if free
    if "check" in legal:
        # In position: check less (bet for value more)
        if "raise" in legal and random.random() < 0.25:
            target = req["opp_bet"] + int(0.6 * pot)
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        return {"type": "action", "action": "check"}

    # Pot odds calculation
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0

    strength = hand_strength(hole)
    # Normalize: treat 25+ as very strong, <8 as weak
    strong_threshold = 22
    medium_threshold = 12

    if strength >= strong_threshold:
        # Strong hand: raise or call
        if "raise" in legal and random.random() < 0.60:
            size = 0.75 if street in ("flop", "turn") else 0.5
            target = req["opp_bet"] + int(size * (pot + to_call))
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        if "call" in legal:
            return {"type": "action", "action": "call"}
    elif strength >= medium_threshold:
        # Medium hand: call if pot odds are OK
        if pot_odds < 0.35 and "call" in legal:
            return {"type": "action", "action": "call"}
        # Occasionally bluff raise in position
        if "raise" in legal and random.random() < 0.10:
            target = req["opp_bet"] + int(0.5 * pot)
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
    else:
        # Weak hand: fold to any significant bet, call tiny ones
        if to_call <= 2 and "call" in legal:
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

