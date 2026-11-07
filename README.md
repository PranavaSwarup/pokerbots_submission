# Pokerbots 2026 Submission: Synergy '26 (IIIT Bangalore)

Autonomous algorithmic poker bot designed for the **Discard Hold'em** variant under the official IIIT Bangalore Synergy '26 competition rules.

---

## 🏆 Key Architectural Breakthroughs

### 1. Ultra-Fast Bitmask Hand Evaluator (`eval_fast`)
- **Direct 5, 6, 7-card integer bitmask evaluator** matching `engine.py`'s `rank5`/`best_hand` 100% across all 15,000+ verification test cases.
- Operates at **~2.5 microseconds per evaluation** (a **25x speedup** over naive `combinations` + `Counter` approaches).
- 100% pure Python standard library: zero external dependencies, zero compilation steps, completely portable.

### 2. True 3-to-2 Preflop & Flop Simulation
- In Discard Hold'em, players are dealt 3 cards, but must discard 1 after the flop.
- Rather than evaluating hands as static 3-card poker, our engine simulates the full mechanic: both players deal 3 cards, see the flop, keep their best 2, and run out to the river.
- Prevents false-positive monster traps (e.g., holding `888` is not trips on the river—one 8 must be discarded, making it only a pair of 8s).
- On the flop pre-discard, evaluates true 3v3 equity where both players select their best 2 of 3 cards on the flop texture.

### 3. Effective Hand Strength (EHS) with Transition Potentials
- Implements the University of Alberta / Billings formulation:
  $$EHS = HS \times (1 - NPOT) + (1 - HS) \times PPOT$$
- Evaluates **Current Hand Strength ($HS$)**, **Positive Potential ($PPOT$)**, and **Negative Potential ($NPOT$)**.
- Correctly values monster draws on wet boards (e.g., straight-flush draws are evaluated at ~68% equity instead of folding high-card 9).

### 4. Discard-Conditioned Bayesian Range Evaluation
- The defining mechanic in Discard Hold'em is the **simultaneous exposed discard** after the flop (`opp_discard`).
- Our bot conditions the opponent's candidate hand distribution on their public discard:
  - If the opponent discarded $d_{opp}$, candidate hands where $d_{opp}$ would have been kept over their current holding are downweighted/eliminated.
  - River: Exact exhaustive enumeration over all ~900 opponent holdings with Bayesian discard weighting in ~15 ms.

### 5. Professional Heads-Up Bet Sizing & Check-Raise Trapping
- **Preflop Sizing**: Calibrated 2.5x BB button opens (5 chips), 3x 3-bets (12-15 chips), and 2.5x 4-bets (30 chips).
- **Postflop Sizing**: Geometric pot scaling (33% dry flop, 60% wet flop, 65% turn, 75%–100% / shove on river).
- **Check-Raise Trapping**: When Out of Position postflop holding monster equity ($\ge 85\%$) against aggressive opponents, checks first to induce bluffs and extract maximum chips via check-raises.
- **Disciplined River Defense**: Zero hero-calls against passive opponents (calling stations never bluff the river).

### 6. Dynamic Time-Bank Safety Controller
- Continuously calculates per-decision time budgets:
  $$\text{Budget} = \frac{\text{Time Left} - 2.5\text{s}}{\text{Hands Remaining} \times 3}$$
- Automatically scales Monte Carlo sample counts, guaranteeing zero timeouts or forfeits even on a throttled 1 vCPU evaluation environment.

---

## ⏱️ Benchmark & Performance

Tested under official local engine conditions (`engine.py`):

| Matchup | Format | Score (Chips) | Result | Time Used / Leg Bank | Notices |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **vs `random_bot.py`** | Stage 1 (400 hands) | **+4,528** | **Win (Capped +400)** | 4.8 s / 30.0 s | **0** |
| **vs `aggressive_bot.py`** | Stage 1 (400 hands) | **+13,161** | **Win (Capped +400)** | 8.3 s / 30.0 s | **0** |
| **vs `bot.py` (Starter)** | Stage 1 (400 hands) | **+3,078** | **Win (Capped +400)** | 11.1 s / 30.0 s | **0** |
| **vs `random_bot.py`** | Stage 2 (1,000 hands) | **+13,793** | **Win (Capped +1000)** | 33.2 s / 75.0 s | **0** |

---

## 🛠️ Testing Locally

Run a match against the example bots:
```bash
python starter_kkit/Starter_Kit/engine.py bot.py starter_kkit/Starter_Kit/example_bots/random_bot.py --stage 1
```

Run a 1,000-hand Stage 2 match:
```bash
python starter_kkit/Starter_Kit/engine.py bot.py starter_kkit/Starter_Kit/example_bots/random_bot.py --stage 2
```

---

## 📋 Compliance & Rules
- **Python Version**: 3.11
- **Allowed Libraries**: Standard Library only (`sys`, `json`, `random`, `time`, `itertools`, `collections`).
- **No external dependencies** required at runtime.
- **Strict adherence** to the protocol: zero non-protocol output on `stdout`, robust handling of all message types, and immediate flush.
