"""
Mixed Strategy Bot: randomizes between aggressive and conservative play
each hand to prevent exploitation. Implements a simplified GTO-inspired
mixed strategy using randomized bet frequencies.
"""
import sys, json, random

RANKS = "23456789TJQKA"

# Strategy frequencies per street
STRATEGY = {
    "preflop": {"raise_freq": 0.40, "call_freq": 0.45, "fold_freq": 0.15},
    "flop":    {"raise_freq": 0.30, "call_freq": 0.45, "fold_freq": 0.25},
    "turn":    {"raise_freq": 0.25, "call_freq": 0.40, "fold_freq": 0.35},
    "river":   {"raise_freq": 0.30, "call_freq": 0.35, "fold_freq": 0.35},
}

def choose_action(req):
    legal = req["legal_actions"]
    street = req["street"]
    to_call = req["to_call"]
    pot = req["pot"]

    strat = STRATEGY.get(street, STRATEGY["river"])

    if "check" in legal:
        roll = random.random()
        if "raise" in legal and roll < strat["raise_freq"]:
            size = random.choice([0.5, 0.65, 0.75, 1.0])
            target = req["opp_bet"] + int(size * pot)
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        return {"type": "action", "action": "check"}

    # Facing a bet: use mixed strategy
    roll = random.random()
    threshold = strat["raise_freq"] + strat["call_freq"]

    # Adjust based on bet size relative to pot
    bet_ratio = to_call / (pot + to_call) if (pot + to_call) > 0 else 0.5
    # Large bets are harder to call: shift threshold down
    effective_threshold = threshold - bet_ratio * 0.3

    if roll < strat["raise_freq"] * 0.5 and "raise" in legal:
        # Re-raise (bluff or value mixed)
        size = random.choice([0.75, 1.0, 1.5])
        target = req["opp_bet"] + int(size * (pot + to_call))
        amount = max(req["min_raise"], min(req["max_raise"], target))
        return {"type": "action", "action": "raise", "amount": amount}
    elif roll < effective_threshold and "call" in legal:
        return {"type": "action", "action": "call"}
    elif to_call <= 2 and "call" in legal:
        return {"type": "action", "action": "call"}

    return {"type": "action", "action": "fold"}

def choose_discard(req):
    cards = req["hole_cards"]
    # Mixed: sometimes keep lowest for deception
    if random.random() < 0.15:
        return {"type": "discard", "card": random.choice(cards)}
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

