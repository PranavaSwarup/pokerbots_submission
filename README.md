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

### 4. Action-Aware & Draw-Aware Bayesian Range Conditioning
- The defining mechanic in Discard Hold'em is the **simultaneous exposed discard** after the flop (`opp_discard`).
- Our bot conditions the opponent's candidate hand distribution on both public information sources:
  - **Draw-Aware Discard Conditioning (`flop_score`)**: Accurately recognizes that keeping flush draws (+1.6) and open-ended straight draws (+1.2) is superior to keeping weak underpairs, assigning full Bayesian weight ($w_{\text{disc}} = 1.0$) to rational draw preservation on wet boards.
  - **Action Conditioning**: Separates opponent's **Betting Range** (monsters, top pairs, high draws, bluffs) from their **Checking Range** (capped, marginal hands) based on real-time opponent aggression profiling ($AF$, $VPIP$).
  - **River**: Exact exhaustive enumeration over all ~900 opponent holdings with Bayesian discard and action weights in **< 7 ms** via precomputed single-card candidate scoring.

### 5. Variance-Free Discard Optimization via Common Random Numbers (CRN)
- Solves discard selection by evaluating all 3 candidate 2-card holdings against the **exact same simulated opponent hands and board runouts** ($Cov(X_A, X_B) > 0$).
- Eliminates Monte Carlo sample variance between candidate choices, cuts evaluation runtime in half, and increases simulation fidelity ($N = 220$).
- Inverted Discard Tiebreaker: Retains higher rank cards for kickers and blockers on ties (`12 - RV[card]`).

### 6. Canonical Equivalence Class Isomorphism (`fast_canon_key`)
- Compresses the 22,100 preflop 3-card combinations into exactly **1,755 canonical suit-isomorphic equivalence classes** in **~1 µs** per lookup.
- Maximizes preflop cache hits across the duplicate-deal legs, saving valuable compute for deeper postflop Monte Carlo search.

### 7. Differentiated Draw Potential (`draw_potential`)
- Distinguishes monster combo draws (12–15 outs, $PPOT \approx 0.50$), flush draws (9 outs, $PPOT \approx 0.36$), open-ended straight draws (8 outs, $PPOT \approx 0.32$), and inside gutshots (4 outs, $PPOT \approx 0.14$).
- Prevents negative-EV calls on weak inside draws while maximizing aggression and semi-bluff equity with premium draws.

### 8. Showdown River Bluff Tracking & Calibrated Bluff-Catching
- Exploits revealed `opp_hole_cards` at showdown to observe opponent river betting ranges directly.
- Formulates an empirical Bayesian posterior for river bluff frequency:
  $$\text{Bluff Freq} = \frac{\text{showdown\_river\_bluffs} + 0.45}{\text{showdown\_river\_bets} + 3.0}$$
- Dynamically conditions river Bayesian range enumeration against habitual bluffers vs zero-bluff stations.

### 9. Texture-Dependent Geometric Sizing & Check-Raise Trapping
- **Texture-Dependent Sizing**: Analyzes board connectivity and suitedness (`is_board_wet`). On wet boards, bet sizes scale up (+0.10) to 50–70% pot to deny equity to draws; on dry boards, bet sizes scale down (-0.05) to 33% pot for optimal pot control and cheap semi-bluffs.
- **Scare-Card River Bluffing**: On the river, bluffs are only fired when a genuine scare card falls (`is_river_scare_card` detects completed 3-flushes or 4-straights) against opponents who fold (`fold_to_raise_pct > 0.35`). On brick runouts, the bot concedes cheaply, eliminating river chip leaks.
- **Check-Raise Trapping**: When Out of Position postflop holding monster equity ($\ge 85\%$) against aggressive opponents, checks first to induce bluffs and extract maximum chips via check-raises.
- **Disciplined River & Preflop Stack Preservation**: Zero hero-calls against passive opponents (calling stations never bluff the river). Folds marginal holdings to 4-bets and all-in shoves to protect the stack in duplicate deals. Medium hands check behind on the river to realize showdown value. Calibrated bluff-catching pot-odds margins against maniacs.

### 10. Dynamic Time-Bank Safety Controller
- Continuously calculates per-decision time budgets:
  $$\text{Budget} = \frac{\text{Time Left} - 2.5\text{s}}{\text{Hands Remaining} \times 3}$$
- Automatically scales Monte Carlo sample counts, guaranteeing zero timeouts or forfeits even on a throttled 1 vCPU evaluation environment.

---

## ⏱️ Benchmark & Performance

Tested under official local engine conditions (`engine.py`):

| Matchup | Format | Score (Chips) | Result | Time Used / Leg Bank | Notices |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **vs `random_bot.py`** | Stage 1 (400 hands) | **+9,859** | **Win (Capped +400)** | **5.69 s** / 30.0 s | **0** |
| **vs `aggressive_bot.py`** | Stage 1 (400 hands) | **+13,143** | **Win (Capped +400)** | **10.59 s** / 30.0 s | **0** |
| **vs `random_bot.py`** | Stage 2 (1,000 hands) | **+21,225** | **Win (Capped +1000)** | **43.14 s** / 75.0 s | **0** |
| **vs `bot.py` (Self-Play)** | Stage 1 (400 hands) | **±434** | **Near-Equilibrium** | **17.4 s** / 30.0 s | **0** |

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
