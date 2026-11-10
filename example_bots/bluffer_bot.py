"""
Bluffer Bot: bluffs frequently on scary boards, semi-bluffs draws,
value bets monsters. Tries to represent strength on paired/flushed boards.
"""
import sys, json, random

RANKS = "23456789TJQKA"
SUITS = "shdc"

def board_is_scary(board):
    """Return True if the board is a good bluffing texture."""
    if not board:
        return False
    suits = [c[1] for c in board]
    ranks = [c[0] for c in board]
    # Flush-possible board
    if max(suits.count(s) for s in SUITS) >= 2:
        return True
    # Paired board
    if len(ranks) != len(set(ranks)):
        return True
    # High card board (A or K present)
    if any(r in ("A", "K") for r in ranks):
        return True
    return False

def choose_action(req):
    legal = req["legal_actions"]
    street = req["street"]
    to_call = req["to_call"]
    pot = req["pot"]
    board = req.get("board_cards", [])
    hole = req.get("hole_cards", [])

    if "check" in legal:
        # Bluff bet on scary boards or when heads-up with a draw
        if "raise" in legal and board_is_scary(board) and random.random() < 0.55:
            size = random.choice([0.6, 0.75, 1.0])
            target = req["opp_bet"] + int(size * pot)
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        # Random probe bet
        if "raise" in legal and random.random() < 0.25:
            target = req["opp_bet"] + int(0.5 * pot)
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        return {"type": "action", "action": "check"}

    # Facing a bet: bluff-raise on scary boards, otherwise call/fold based on odds
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0

    if "raise" in legal and board_is_scary(board) and random.random() < 0.35:
        # Bluff re-raise
        target = req["opp_bet"] + int(1.0 * (pot + to_call))
        amount = max(req["min_raise"], min(req["max_raise"], target))
        return {"type": "action", "action": "raise", "amount": amount}

    if "call" in legal:
        # Call if pot odds are reasonable or small bet
        if pot_odds < 0.40 or to_call <= 4:
            return {"type": "action", "action": "call"}

    return {"type": "action", "action": "fold"}

def choose_discard(req):
    cards = req["hole_cards"]
    # Keep suited cards for flush bluff potential
    suits = [c[1] for c in cards]
    if len(set(suits)) < len(suits):
        # Has a suited pair - keep them, discard the odd one
        from collections import Counter
        sc = Counter(suits)
        common_suit = sc.most_common(1)[0][0]
        for c in cards:
            if c[1] != common_suit:
                return {"type": "discard", "card": c}
    # Else discard lowest rank
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

