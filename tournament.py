"""
╔══════════════════════════════════════════════════════════════╗
║          DISCARD HOLD'EM  –  POKERBOTS TOURNAMENT           ║
║                 Single-Elimination Bracket                   ║
╚══════════════════════════════════════════════════════════════╝

Usage:
    python tournament.py                        # full bracket, all bots
    python tournament.py --quick                # 1 stage × 5 hands (fast test)
    python tournament.py --bots a.py b.py ...  # custom bot list
    python tournament.py --seed 42              # fixed random seed for seeding
"""

import subprocess
import re
import sys
import os
import math
import random
import argparse
import json
from datetime import datetime

# ─────────────────────────── Configuration ───────────────────────────────────

ENGINE = "starter_kkit/Starter_Kit/engine.py"

# All bots available for the tournament.
# Paths are relative to the workspace root (same dir as this script).
BOT_REGISTRY = {
    # Our main bot
    "OurBot":           "bot.py",
    # Classic examples
    "Random":           "example_bots/random_bot.py",
    "Nit":              "example_bots/nit_bot.py",
    "Aggressive":       "example_bots/aggressive_bot.py",
    "AllIn":            "example_bots/all_in.py",
    "Combined":         "example_bots/player.py",
    "AG":               "example_bots/test.py",  
    # New strategy bots
    "CallingStation":   "example_bots/calling_station.py",
    "Positional":       "example_bots/positional_bot.py",
    "Bluffer":          "example_bots/bluffer_bot.py",
    "PotOdds":          "example_bots/pot_odds_bot.py",
    "Trapper":          "example_bots/trapper_bot.py",
    "MixedStrategy":    "example_bots/mixed_strategy_bot.py",
    "BestBotNew":       "example_bots/best_bot.py",
    "ChampionBot":      "example_bots/champion_bot.py",
}

# Match settings
DEFAULT_STAGES         = [1, 2]       # run both Stage 1 and Stage 2 per match
DEFAULT_HANDS_STAGE1   = 400          # engine default for stage 1
DEFAULT_HANDS_STAGE2   = 1000         # engine default for stage 2

# In "quick" mode: only Stage 1, 50 hands
QUICK_STAGE            = 1
QUICK_HANDS            = 50

# Output directory for logs and results
OUT_DIR = "tournament_results"

# ─────────────────────────── Helpers ─────────────────────────────────────────

def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)

def run_match(bot_a_path: str, bot_b_path: str,
              stage: int, hands: int | None, seed: int,
              log_path: str) -> dict:
    """
    Run one match between bot_a and bot_b via the engine.
    Returns {"net_a": int, "net_b": int, "error": str|None}
    """
    cmd = [
        sys.executable,
        ENGINE,
        bot_a_path,
        bot_b_path,
        "--stage", str(stage),
        "--seed",  str(seed),
    ]
    if hands is not None:
        cmd += ["--hands", str(hands)]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return {"net_a": 0, "net_b": 0, "error": "timeout"}

    output = proc.stdout + proc.stderr

    with open(log_path, "w", encoding="utf-8") as f:
        f.write(f"CMD: {' '.join(cmd)}\n\n")
        f.write(output)

    # Parse final net scores.  Engine prints lines like:
    #   "A  bot_a.py  stack 237  net +37"
    #   "B  bot_b.py  stack 163  net -37"
    nets_a = re.findall(r"^\s*A\s+.*?net\s+([+-]?\d+)", output, re.MULTILINE)
    nets_b = re.findall(r"^\s*B\s+.*?net\s+([+-]?\d+)", output, re.MULTILINE)

    if nets_a and nets_b:
        return {"net_a": int(nets_a[-1]), "net_b": int(nets_b[-1]), "error": None}

    # Fallback: look for any "net +N" near bot names (older engine formats)
    all_nets = re.findall(r"net\s+([+-]?\d+)", output)
    if len(all_nets) >= 2:
        return {"net_a": int(all_nets[-2]), "net_b": int(all_nets[-1]), "error": None}

    return {"net_a": 0, "net_b": 0, "error": "parse_failed"}


def head_to_head(name_a: str, path_a: str,
                 name_b: str, path_b: str,
                 stages: list[int], hands_per_stage: dict[int, int | None],
                 base_seed: int, run_id: str, out_dir: str) -> dict:
    """
    Run a full head-to-head series (all stages) between two bots.
    Returns:
        {
          "winner": name_a | name_b | "tie",
          "net_a": total, "net_b": total,
          "stage_results": {stage: {"net_a":..,"net_b":..}},
        }
    """
    total_net_a = 0
    total_net_b = 0
    stage_results = {}

    for stage in stages:
        hands = hands_per_stage.get(stage)
        seed  = base_seed + stage   # slightly different seed per stage
        log_path = os.path.join(
            out_dir, f"{run_id}_S{stage}.log"
        )
        print(f"      Stage {stage}  seed={seed}  hands={hands or 'default'}  ...", end="", flush=True)
        result = run_match(path_a, path_b, stage, hands, seed, log_path)

        if result["error"]:
            print(f" ERROR ({result['error']})")
        else:
            diff = result["net_a"] - result["net_b"]
            sign = "+" if diff >= 0 else ""
            print(f" A={result['net_a']:+d}  B={result['net_b']:+d}  Δ={sign}{diff}")

        total_net_a += result["net_a"]
        total_net_b += result["net_b"]
        stage_results[stage] = {"net_a": result["net_a"], "net_b": result["net_b"],
                                "error": result["error"]}

    if total_net_a > total_net_b:
        winner = name_a
    elif total_net_b > total_net_a:
        winner = name_b
    else:
        winner = "tie"

    return {
        "winner":        winner,
        "net_a":         total_net_a,
        "net_b":         total_net_b,
        "stage_results": stage_results,
    }

# ─────────────────────────── Tournament Logic ────────────────────────────────

def pad_bracket(bots: list) -> list:
    """
    Pad the bot list to the next power-of-2 with BYE slots.
    Returns a list of (name, path) or ("BYE", None).
    """
    n = len(bots)
    target = 1 << math.ceil(math.log2(max(n, 2)))
    byes_needed = target - n
    return list(bots) + [("BYE", None)] * byes_needed

def run_tournament(bots: list[tuple[str, str]],
                   stages: list[int],
                   hands_per_stage: dict[int, int | None],
                   base_seed: int,
                   out_dir: str) -> dict:
    """
    Run a single-elimination tournament.
    bots: list of (name, path)
    Returns bracket summary dict.
    """
    bracket = pad_bracket(bots)
    n_total = len(bracket)
    n_rounds = int(math.log2(n_total))

    all_rounds = []        # list of round dicts
    match_counter = [0]    # mutable counter

    current_round = bracket

    for rnd in range(1, n_rounds + 1):
        round_name = {
            1: "Round of " + str(n_total),
        }.get(rnd, f"Round {rnd}")
        # Override for well-known late rounds
        remaining = len(current_round)
        if remaining == 2:
            round_name = "FINAL"
        elif remaining == 4:
            round_name = "Semi-Finals"
        elif remaining == 8:
            round_name = "Quarter-Finals"

        sep = "═" * 60
        print(f"\n{sep}")
        print(f"  {round_name}  ({remaining} bots)")
        print(sep)

        next_round = []
        round_matches = []

        pairs = [(current_round[i], current_round[i + 1])
                 for i in range(0, len(current_round), 2)]

        for (name_a, path_a), (name_b, path_b) in pairs:
            match_counter[0] += 1
            mid = match_counter[0]

            # Handle BYE slots
            if name_b == "BYE":
                print(f"  Match {mid}: {name_a}  vs  BYE  →  {name_a} advances (bye)")
                next_round.append((name_a, path_a))
                round_matches.append({
                    "match": mid, "bot_a": name_a, "bot_b": "BYE",
                    "winner": name_a, "net_a": 0, "net_b": 0,
                    "stage_results": {}, "bye": True,
                })
                continue
            if name_a == "BYE":
                print(f"  Match {mid}: BYE  vs  {name_b}  →  {name_b} advances (bye)")
                next_round.append((name_b, path_b))
                round_matches.append({
                    "match": mid, "bot_a": "BYE", "bot_b": name_b,
                    "winner": name_b, "net_a": 0, "net_b": 0,
                    "stage_results": {}, "bye": True,
                })
                continue

            # Real match
            print(f"\n  Match {mid}: {name_a}  vs  {name_b}")
            run_id = f"R{rnd}_M{mid}_{name_a}_vs_{name_b}"
            result = head_to_head(
                name_a, path_a,
                name_b, path_b,
                stages, hands_per_stage,
                base_seed + mid * 97,   # unique seed per match
                run_id, out_dir
            )

            w = result["winner"]
            if w == "tie":
                # Tiebreaker: tiny coin flip (randomise; could also replay)
                w = name_a if random.random() < 0.5 else name_b
                print(f"      TIE — coin-flip winner: {w}")

            winner_path = path_a if w == name_a else path_b
            arrow = "→"
            print(f"      {arrow}  WINNER: {w}  (Net {name_a}={result['net_a']:+d}, {name_b}={result['net_b']:+d})")
            next_round.append((w, winner_path))

            round_matches.append({
                "match": mid,
                "bot_a": name_a, "bot_b": name_b,
                "winner": w,
                "net_a": result["net_a"], "net_b": result["net_b"],
                "stage_results": result["stage_results"],
                "bye": False,
            })

        all_rounds.append({"round": rnd, "name": round_name, "matches": round_matches})
        current_round = next_round

    champion = current_round[0][0] if current_round else "unknown"
    return {"champion": champion, "rounds": all_rounds}

# ─────────────────────────── Report Generation ───────────────────────────────

def print_bracket_summary(result: dict, bots: list[tuple[str, str]]):
    sep  = "═" * 60
    sep2 = "─" * 60

    print(f"\n\n{'█' * 60}")
    print(f"  TOURNAMENT COMPLETE")
    print(f"{'█' * 60}")
    print(f"\n  🏆  CHAMPION:  {result['champion']}")
    print(f"\n{sep}")
    print("  FULL BRACKET")
    print(sep)

    for rnd_data in result["rounds"]:
        print(f"\n  ── {rnd_data['name']} ──")
        for m in rnd_data["matches"]:
            if m.get("bye"):
                print(f"     Match {m['match']:>2}: {m['bot_a']:20s} BYE → {m['winner']}")
            else:
                net_a_str = f"{m['net_a']:+d}"
                net_b_str = f"{m['net_b']:+d}"
                print(
                    f"     Match {m['match']:>2}: "
                    f"{m['bot_a']:20s} ({net_a_str:>6}) "
                    f"vs  {m['bot_b']:20s} ({net_b_str:>6})  →  {m['winner']}"
                )

    print(f"\n{sep}")

def save_json_report(result: dict, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)
    print(f"  JSON report saved → {path}")

def save_text_report(result: dict, bots: list[tuple[str, str]], path: str):
    lines = []
    sep  = "=" * 60
    lines.append(sep)
    lines.append("  DISCARD HOLD'EM – TOURNAMENT REPORT")
    lines.append(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(sep)
    lines.append(f"\n  CHAMPION: {result['champion']}\n")

    for rnd_data in result["rounds"]:
        lines.append(f"\n── {rnd_data['name']} ──")
        for m in rnd_data["matches"]:
            if m.get("bye"):
                lines.append(f"  Match {m['match']:>2}: {m['bot_a']} BYE → {m['winner']}")
            else:
                lines.append(
                    f"  Match {m['match']:>2}: "
                    f"{m['bot_a']} ({m['net_a']:+d}) "
                    f"vs {m['bot_b']} ({m['net_b']:+d}) "
                    f"→ {m['winner']}"
                )
                for stage, sr in m["stage_results"].items():
                    lines.append(
                        f"           Stage {stage}: "
                        f"{m['bot_a']}={sr['net_a']:+d}  "
                        f"{m['bot_b']}={sr['net_b']:+d}"
                        + (f"  [ERR: {sr['error']}]" if sr.get("error") else "")
                    )

    lines.append(f"\n{sep}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  Text report saved  → {path}")

# ─────────────────────────── Entry Point ─────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="Discard Hold'em Bot Tournament")
    p.add_argument("--quick",  action="store_true",
                   help="Quick mode: Stage 1 only, 50 hands per match")
    p.add_argument("--bots", nargs="+", metavar="BOT_PATH",
                   help="Custom list of bot .py paths (overrides registry)")
    p.add_argument("--seed",  type=int, default=None,
                   help="Base random seed for match randomisation")
    p.add_argument("--no-stage2", action="store_true",
                   help="Skip Stage 2 (run Stage 1 only with default hands)")
    p.add_argument("--hands", type=int, default=None,
                   help="Override hands per stage (both stages)")
    return p.parse_args()


def main():
    args = parse_args()

    # ── Seed ──
    base_seed = args.seed if args.seed is not None else random.randint(1, 999999)
    random.seed(base_seed)
    print(f"\nTournament seed: {base_seed}")

    # ── Bot list ──
    if args.bots:
        bots = []
        for path in args.bots:
            name = os.path.splitext(os.path.basename(path))[0]
            bots.append((name, path))
    else:
        # Use registry; filter out bots whose files don't exist
        bots = []
        for name, path in BOT_REGISTRY.items():
            if os.path.isfile(path):
                bots.append((name, path))
            else:
                print(f"  [WARN] Bot file not found, skipping: {path}  ({name})")

    if len(bots) < 2:
        print("ERROR: Need at least 2 bots to run a tournament.")
        sys.exit(1)

    # Shuffle to randomise bracket seeding
    random.shuffle(bots)

    # ── Match settings ──
    if args.quick:
        stages = [QUICK_STAGE]
        hands_per_stage = {QUICK_STAGE: QUICK_HANDS}
    elif args.no_stage2:
        stages = [1]
        hands_per_stage = {1: args.hands}
    else:
        stages = DEFAULT_STAGES
        if args.hands is not None:
            hands_per_stage = {s: args.hands for s in stages}
        else:
            hands_per_stage = {
                1: None,     # None → engine uses its own default (400)
                2: None,     # None → engine uses its own default (1000)
            }

    # ── Output directory ──
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = os.path.join(OUT_DIR, f"run_{ts}_seed{base_seed}")
    ensure_dir(run_dir)

    # ── Print header ──
    sep = "═" * 60
    print(f"\n{sep}")
    print("  DISCARD HOLD'EM  –  POKERBOTS TOURNAMENT")
    mode_label = "QUICK" if args.quick else ("Stage 1 only" if args.no_stage2 else "Full (Stage 1 + 2)")
    print(f"  Mode: {mode_label}")
    print(f"  Bots ({len(bots)}):")
    for name, path in bots:
        print(f"    • {name:22s}  ←  {path}")
    n_padded = 1 << math.ceil(math.log2(max(len(bots), 2)))
    byes = n_padded - len(bots)
    print(f"  Bracket size: {n_padded}  ({byes} bye{'s' if byes != 1 else ''})")
    print(f"  Results dir:  {run_dir}")
    print(sep)

    # ── Run tournament ──
    result = run_tournament(bots, stages, hands_per_stage, base_seed, run_dir)

    # ── Print & save results ──
    print_bracket_summary(result, bots)

    json_path = os.path.join(run_dir, "results.json")
    txt_path  = os.path.join(run_dir, "results.txt")
    save_json_report(result, json_path)
    save_text_report(result, bots, txt_path)

    print(f"\n  🏆  Champion: {result['champion']}")
    print(f"  Results: {run_dir}\n")
    return result


if __name__ == "__main__":
    main()
