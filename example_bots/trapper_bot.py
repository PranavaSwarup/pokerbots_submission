"""
Trapper Bot: slowplays strong hands to induce bluffs, check-raises with monsters.
Plays passively with strong hands early, then springs the trap on the river.
"""
import sys, json, random

RANKS = "23456789TJQKA"

def hand_rank_sum(hole_cards):
    return sum(RANKS.index(c[0]) for c in hole_cards)

def hand_has_pair(hole_cards, board_cards):
    hole_ranks = [c[0] for c in hole_cards]
    board_ranks = [c[0] for c in board_cards]
    for r in hole_ranks:
        if r in board_ranks or hole_ranks.count(r) > 1:
            return True
    return False

def choose_action(req):
    legal = req["legal_actions"]
    street = req["street"]
    to_call = req["to_call"]
    pot = req["pot"]
    hole = req.get("hole_cards", [])
    board = req.get("board_cards", [])

    strong = hand_has_pair(hole, board) or hand_rank_sum(hole) >= 20

    if "check" in legal:
        if street == "river":
            # Spring the trap on the river: bet big with strong hands
            if strong and "raise" in legal and random.random() < 0.80:
                target = req["opp_bet"] + int(0.9 * pot)
                amount = max(req["min_raise"], min(req["max_raise"], target))
                return {"type": "action", "action": "raise", "amount": amount}
        elif street in ("flop", "turn") and strong:
            # Slowplay - mostly check
            if "raise" in legal and random.random() < 0.10:
                target = req["opp_bet"] + int(0.4 * pot)
                amount = max(req["min_raise"], min(req["max_raise"], target))
                return {"type": "action", "action": "raise", "amount": amount}
        return {"type": "action", "action": "check"}

    # Facing a bet:
    if strong:
        # Check-raise trap with strong hands (delay the raise)
        if "raise" in legal and random.random() < (0.70 if street == "river" else 0.30):
            target = req["opp_bet"] + int(1.2 * (pot + to_call))
            amount = max(req["min_raise"], min(req["max_raise"], target))
            return {"type": "action", "action": "raise", "amount": amount}
        if "call" in legal:
            return {"type": "action", "action": "call"}
    else:
        # Weak hand: fold unless very cheap
        if to_call <= 3 and "call" in legal:
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

