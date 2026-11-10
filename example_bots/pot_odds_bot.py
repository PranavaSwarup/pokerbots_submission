"""
Pot Odds Bot: purely mathematical. Calls only when pot odds exceed a fixed
equity threshold. Never bluffs. Raises only with very strong hands.
Estimates equity by hole card rank percentile.
"""
import sys, json, random

RANKS = "23456789TJQKA"

def estimate_equity(hole_cards, board_cards):
    """
    Quick equity estimate based on hole card ranks and board pairing.
    Returns a float 0.0-1.0.
    """
    if not hole_cards:
        return 0.3
    hole_ranks = [RANKS.index(c[0]) for c in hole_cards]
    board_ranks = [RANKS.index(c[0]) for c in board_cards]

    # Check for pairs, trips, etc.
    all_ranks = hole_ranks + board_ranks
    from collections import Counter
    cnt = Counter(all_ranks)
    max_match = max(cnt.values()) if cnt else 1

    # Base equity from hole card strength
    avg_hole = sum(hole_ranks) / len(hole_ranks)
    base = 0.25 + (avg_hole / 12.0) * 0.30   # 0.25 to 0.55

    # Bonus for hitting the board
    hole_set = set(hole_ranks)
    board_hits = sum(1 for r in board_ranks if r in hole_set)
    pair_bonus = board_hits * 0.12

    # Bonus for high pairs in hole
    if len(hole_ranks) >= 2 and hole_ranks[0] == hole_ranks[1]:
        pair_bonus += 0.10 + hole_ranks[0] * 0.005

    # Multi-card match (trips/full house)
    multi_bonus = 0.0
    if max_match == 3:
        multi_bonus = 0.20
    elif max_match >= 4:
        multi_bonus = 0.40

    # Flush draw (suited hole cards with matching board suit)
    hole_suits = [c[1] for c in hole_cards]
    board_suits = [c[1] for c in board_cards]
    flush_bonus = 0.0
    if hole_suits:
        from collections import Counter as C
        hs = C(hole_suits)
        bs = C(board_suits)
        for s in hs:
            if hs[s] + bs.get(s, 0) >= 4:
                flush_bonus = 0.10
                break

    equity = min(0.95, base + pair_bonus + multi_bonus + flush_bonus)
    return equity

def choose_action(req):
    legal = req["legal_actions"]
    to_call = req["to_call"]
    pot = req["pot"]
    hole = req.get("hole_cards", [])
    board = req.get("board_cards", [])

    equity = estimate_equity(hole, board)

    if "check" in legal:
        # Value bet with strong equity
        if "raise" in legal and equity >= 0.65:
            size = 0.6 if equity < 0.80 else 0.85
            target = req["opp_bet"] + int(size * pot)
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        return {"type": "action", "action": "check"}

    # Pot odds: only call if equity > pot_odds
    pot_odds = to_call / (pot + to_call) if (pot + to_call) > 0 else 1.0

    if equity > pot_odds + 0.05:  # small edge buffer
        if "raise" in legal and equity >= 0.75 and random.random() < 0.40:
            # Re-raise for value
            target = req["opp_bet"] + int(0.75 * (pot + to_call))
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        if "call" in legal:
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

