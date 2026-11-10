"""
Championship Discard Hold'em Bot for Pokerbots (Synergy '26 @ IIIT Bangalore).
Team: Pranava Swarup (pranava)

Unified Game-Theoretic & Action-Aware Bayesian Architecture:
- Direct 5, 6, 7-card integer bitmask evaluator (100% engine match, ~2.5us).
- Phantom-Draw Prevention (requires hole card participation in draws).
- Action-Aware Bayesian River & Turn Range Conditioning.
- Granular Opponent Modeling (Early Maniac/Nit Detection & River Bluff profiling).
- Professional Heads-Up Bet Sizing & Check-Raise Trapping.
"""

import sys
import json
import random
import base64
import zlib
import traceback
from itertools import combinations

# ============================================================================
# CONSTANTS & ENCODINGS
# ============================================================================

RANKS = "23456789TJQKA"
SUITS = "shdc"
RV = {r: i + 2 for i, r in enumerate(RANKS)}   # 2..14
SUIT_ORDER = {s: i for i, s in enumerate(SUITS)}
ALL_CARD_STRS = [r + s for r in RANKS for s in SUITS]
VALID_CARDS_SET = set(ALL_CARD_STRS)

# Card integer encoding: card_int = ((rank - 2) << 2) | suit_idx (0..51)
CARD_TO_INT = {c: ((RV[c[0]] - 2) << 2) | SUIT_ORDER[c[1]] for c in ALL_CARD_STRS}
INT_TO_CARD = {v: k for k, v in CARD_TO_INT.items()}
FULL_DECK_INTS = list(range(52))

STARTING_STACK = 200
SMALL_BLIND = 1
BIG_BLIND = 2

# ============================================================================
# ULTRA-FAST 5, 6, 7-CARD BITMASK EVALUATOR & O(1) LOOKUP TABLES
# ============================================================================

def _init_draw_tables():
    straight_bonus = [0.0] * 8192
    draw_type = [0] * 8192
    is_4straight = [False] * 8192
    straight_high = [0] * 8192

    for mask in range(8192):
        st_high = 0
        for r in range(12, 3, -1):
            pattern = 0x1F << (r - 4)
            if (mask & pattern) == pattern:
                st_high = r + 2
                break
        if st_high == 0 and (mask & 0x100F) == 0x100F:
            st_high = 5
        straight_high[mask] = st_high

        bonus = 0.0
        for r in range(12, 3, -1):
            if (mask & (0x1F << (r - 4))).bit_count() == 4:
                bonus += 1.2
                break
        if bonus < 2.0 and (mask & 0x100F).bit_count() == 4:
            bonus += 0.8
        straight_bonus[mask] = bonus

        is_oesd = False
        for shift in range(9):
            if ((mask >> shift) & 0x0F) == 0x0F:
                is_oesd = True
                break
        if is_oesd:
            draw_type[mask] = 2
        else:
            is_gut = False
            for r in range(12, 3, -1):
                if (mask & (0x1F << (r - 4))).bit_count() == 4:
                    is_gut = True
                    break
            if not is_gut and (mask & 0x100F).bit_count() == 4:
                is_gut = True
            if is_gut:
                draw_type[mask] = 1

        is_4s = False
        for r in range(12, 3, -1):
            if (mask & (0x1F << (r - 4))).bit_count() >= 4:
                is_4s = True
                break
        if not is_4s and (mask & 0x100F).bit_count() >= 4:
            is_4s = True
        is_4straight[mask] = is_4s

    return straight_bonus, draw_type, is_4straight, straight_high

STRAIGHT_BONUS_TABLE, DRAW_TYPE_TABLE, IS_4STRAIGHT_TABLE, STRAIGHT_HIGH_TABLE = _init_draw_tables()


def eval_fast(c_ints):
    """
    Evaluates best 5-card poker hand from 5, 6, or 7 card integers.
    Returns: (category, tiebreakers...)
    """
    rank_counts = [0] * 13
    suit_counts = [0] * 4
    mask = 0
    for ci in c_ints:
        r = ci >> 2
        rank_counts[r] += 1
        suit_counts[ci & 3] += 1
        mask |= (1 << r)

    # 1. Flush check
    flush_suit = -1
    for s in range(4):
        if suit_counts[s] >= 5:
            flush_suit = s
            break

    if flush_suit != -1:
        f_ranks = [ci >> 2 for ci in c_ints if (ci & 3) == flush_suit]
        f_ranks.sort(reverse=True)
        f_mask = 0
        for r in f_ranks:
            f_mask |= (1 << r)
        sf_high = STRAIGHT_HIGH_TABLE[f_mask]
        if sf_high > 0:
            return (8, sf_high)
        return (5, f_ranks[0] + 2, f_ranks[1] + 2, f_ranks[2] + 2, f_ranks[3] + 2, f_ranks[4] + 2)

    # 2. Quads check
    for r in range(12, -1, -1):
        if rank_counts[r] == 4:
            kicker = max(k for k in range(12, -1, -1) if k != r and rank_counts[k] > 0)
            return (7, r + 2, kicker + 2)

    # 3. Full House / Trips / Two Pair / One Pair
    trips = []
    pairs = []
    for r in range(12, -1, -1):
        cnt = rank_counts[r]
        if cnt >= 3:
            trips.append(r)
        elif cnt == 2:
            pairs.append(r)

    if len(trips) >= 2:
        return (6, trips[0] + 2, trips[1] + 2)
    if trips and pairs:
        return (6, trips[0] + 2, pairs[0] + 2)

    # 4. Straight check
    st_high = STRAIGHT_HIGH_TABLE[mask]
    if st_high > 0:
        return (4, st_high)

    # 5. Trips
    if trips:
        t = trips[0]
        kickers = [k for k in range(12, -1, -1) if k != t and rank_counts[k] > 0][:2]
        return (3, t + 2, kickers[0] + 2, kickers[1] + 2)

    # 6. Two Pair
    if len(pairs) >= 2:
        p1, p2 = pairs[0], pairs[1]
        kicker = max(k for k in range(12, -1, -1) if k != p1 and k != p2 and rank_counts[k] > 0)
        return (2, p1 + 2, p2 + 2, kicker + 2)

    # 7. One Pair
    if len(pairs) == 1:
        p = pairs[0]
        kickers = [k for k in range(12, -1, -1) if k != p and rank_counts[k] > 0][:3]
        return (1, p + 2, kickers[0] + 2, kickers[1] + 2, kickers[2] + 2)

    # 8. High Card
    kickers = [k for k in range(12, -1, -1) if rank_counts[k] > 0][:5]
    return (0, kickers[0] + 2, kickers[1] + 2, kickers[2] + 2, kickers[3] + 2, kickers[4] + 2)


# ============================================================================
# CANONICAL ISOMORPHISM & REALISTIC PREFLOP DISCARD HOLD'EM SIMULATION
# ============================================================================

def fast_canon_key(cards):
    ranks = sorted([RV[c[0]] for c in cards], reverse=True)
    r1, r2, r3 = ranks[0], ranks[1], ranks[2]
    s1, s2, s3 = [c[1] for c in sorted(cards, key=lambda c: RV[c[0]], reverse=True)]
    if r1 == r2 == r3:
        return (r1, r2, r3, 0)
    elif r1 == r2 or r2 == r3:
        if r1 == r2:
            kicker_s = [c[1] for c in cards if RV[c[0]] == r3][0]
            pair_s = [c[1] for c in cards if RV[c[0]] == r1]
        else:
            kicker_s = [c[1] for c in cards if RV[c[0]] == r1][0]
            pair_s = [c[1] for c in cards if RV[c[0]] == r2]
        return (r1, r2, r3, 1 if kicker_s in pair_s else 2)
    else:
        if s1 == s2 == s3: p = 3
        elif s1 == s2: p = 4
        elif s1 == s3: p = 5
        elif s2 == s3: p = 6
        else: p = 7
        return (r1, r2, r3, p)

PREFLOP_B85 = (
    "c-kFQX_M4O68(MqVIAy_jbTpuP`6rA>nuqnmG1k#x+V2Y&p><ef&l{qJA+{`#)hyR!LPEs^(iAWEA!>c7kPI<(*!nM+_`(}_CE*?FuXvp)ZWoow{8J`fB*Ps@A&rK?SCqQh$K@oNCy1t@T+hB%?XExhbMan2VZ}?r-H+yqi;{{9*y?DzH@wXd`A~UXxfgdAe~-LC!_J6usoj4#`}lU{qa5&7t7grb}*Tb_fL+o@nLA=GmM!ps3~@QZ!(@8oh<SBfvJa?m!zrh#(@Q>!^!kyAHgY(9o)gl$>gqO%t?GSqL<_O?BL!MKXDzJn9oN`j-V)PHkuvJC)4>!Y%yR-QVWJ<a2%g6=ERsJkH#!EIrh@Ft5#`|R#h0riA+xL@i+Hm=?I?^)A<a?DBr_pgSDVoYPR4>60<FCG5LQFX37$Cju=LvMouj73Qe;NBh0{3T(S$AVu+ErVCH4XC=@S1nE|9IF)YszJR{&D!D9qYGI(8_|EJq-&Nj`a-$Z@aN)k1iO{SJe5*U7nv-F6tOp3%Qf&?Oq5d_6?g}<C(<cK3llHeFXkfI;~P=>;=JQ_fZCIy-iX<4QrFY}zhH#M)QjHn7gp;ZHLtSE8_ad0`{1RTWb2a-DYHK<6utV#&l2C@MXB_Oc6$kRM43CnK%?7{cnKREyIlk?qrcfRZT9fAvroMW=N1k#iu2w{miF3Yk5+ce41OOdD8%+qLkIcFt>W(RpOj0ky}tWq6t3IzbK2!bfFlB{Yf3rtyoO>RLBiO3XWSrrEm$WS5BH4{pl26=wdYL265x~{33XzQ9RnFd0p>;CQ1MF~p7+wDSRJErAonx4hT(F{L!)F^NgdnjibrX`}GrGdci!H>^>c=___<JXU$+<&@zbpO%ryO#*eITmM;#X}Aw0Sg!+atE+;hGAuvk`R(WkdP2iO9UY+N}43fvaTYy&2=Ej+`u<47_zEDsKWt~p-KF<MNk)^p{lB+tF|myu3{JiL`8E9&oFme<N;`_fg)+DYsj|g1j9tJZ@69@dX{5bj`;8*3FCo)*tg6yaw8>*oxqDi#}C3ZOdP}Z%pi6VLQfxizUgT}5>#<gIKCNHY3L>HDh~5HFa6YY1Jg4@q#M5NNS8mndHv?<`sM3auirj-`{McK<LA$Qe0C`U3D6`RX+Q)#r;4%&a!rF45KK=I1<lX|-j8IY4N5aTDA=mWOM`r%c)IbSrW=Oof+0)Meb=@Tw1(Z8ZKp-Zgr;JtvhI4wkbO5$13e5-=mkcwy9iC+kwVwC3@^-G)3Y7V4QwAdsgs0$9A%OB=wX?7z8~d57^kThn^70#W*j(?n>1D7rBPEv?r=c-7gt5$B=JC88a7psMqV1EVVOr!os>yjH|wPQ+im(rXea)wS8+4MlXaPftG+0*Y+V)Ysw?WUt5<Q__Dz+=WnOv7D$MLCDWd$%_0_NM-u-lQbM@xte?Py!xqf?fd42uU`x{M?5tMktQyot-2BmUxmTD?ekm0!oG~xilKC$C4F;&ZV(6D1o4-DNl@-s8eT_^T@!w&s{1h)x7!w83SxZM<G?s!R&xJDY+u9+sb7wUs3{InQ8JbIWW!LaZ;P2#G^>u?|;3X*l=1Vxz!p<Ar;{Kb<vF9Ne%)oI*iO<0#%?MF?yDvM&3XGPaUtEBDgvV8V@U1nLmYMLxPz2CHLQ+HKauB)c%`_ro3wDo3vwpp*LRo_+B<yE`w%2nSt*`~eN^vMvb+J3X{yVa_%+TyHh*8SPKZ}XyS>#psy?A_bbzF(KyP21<~P-?Ti*fh=QY10ixf4bg&*PmZ>-RAyj-&WhAU-#!tHKb)9KE40)@$(;F{`m8k&!2z)`SYhQAAWiN+sEHNe){ki@cnTB"
)

def _init_preflop_lut():
    deck = [r + s for r in RANKS for s in SUITS]
    keys = sorted({(r1 << 11) | (r2 << 7) | (r3 << 3) | p for c in combinations(deck, 3) for r1, r2, r3, p in [fast_canon_key(c)]})
    vals = zlib.decompress(base64.b85decode(PREFLOP_B85))
    return {k: v / 255.0 for k, v in zip(keys, vals)}

PREFLOP_LUT = _init_preflop_lut()

def get_preflop_equity(hole_cards):
    r1, r2, r3, p = fast_canon_key(hole_cards)
    pk = (r1 << 11) | (r2 << 7) | (r3 << 3) | p
    return PREFLOP_LUT.get(pk, 0.50)

def flop_score(c1, c2, flop_ints):
    s = eval_fast([c1, c2] + flop_ints)
    suits = [0, 0, 0, 0]
    suits[c1 & 3] += 1
    suits[c2 & 3] += 1
    mask = (1 << (c1 >> 2)) | (1 << (c2 >> 2))
    for c in flop_ints:
        suits[c & 3] += 1
        mask |= (1 << (c >> 2))

    has_flush = (suits[0] >= 4 or suits[1] >= 4 or suits[2] >= 4 or suits[3] >= 4)
    sb = STRAIGHT_BONUS_TABLE[mask]
    draw_bonus = (1.6 + 1.2) if (has_flush and sb >= 2.0) else ((1.6 if has_flush else 0.0) + sb)
    return (s[0] + draw_bonus, s[1:])

# ============================================================================
# ACTION-AWARE EFFECTIVE HAND STRENGTH (EHS) & DRAW ANALYSIS
# ============================================================================

def draw_potential(c_ints, is_turn=False):
    """
    Evaluates draw strength and Positive Potential (PPOT) for flop or turn holdings.
    Requires at least one hole card to contribute to the draw, eliminating false-positive
    phantom draws from wet board textures.
    """
    if len(c_ints) < 5:
        return ('none', 0.03)

    hole = c_ints[:2]
    board = c_ints[2:]
    h_ranks = {c >> 2 for c in hole}

    # 1. Flush draw: 4+ cards of a suit, with at least 1 in our hole cards
    b_suits = [0, 0, 0, 0]
    for c in board:
        b_suits[c & 3] += 1

    is_flush_draw = False
    for s in range(4):
        h_cnt = sum(1 for c in hole if (c & 3) == s)
        if h_cnt >= 1 and (b_suits[s] + h_cnt) >= 4:
            is_flush_draw = True
            break

    # 2. Straight draw: count ranks completing a straight that uses our hole cards
    b_mask = 0
    for c in board:
        b_mask |= (1 << (c >> 2))

    straight_outs = 0
    for r in range(13):
        if not (b_mask & (1 << r)):
            new_b_mask = b_mask | (1 << r)
            board_only_st = STRAIGHT_HIGH_TABLE[new_b_mask]
            total_mask = new_b_mask
            for hr in h_ranks:
                total_mask |= (1 << hr)
            with_hole_st = STRAIGHT_HIGH_TABLE[total_mask]
            if with_hole_st > 0 and with_hole_st > board_only_st:
                straight_outs += 1

    is_oesd = (straight_outs >= 2)
    is_gutshot = (straight_outs == 1)

    if is_turn:
        if is_flush_draw and (is_oesd or is_gutshot): return ('combo', 0.28)
        elif is_flush_draw: return ('flush', 0.20)
        elif is_oesd: return ('oesd', 0.17)
        elif is_gutshot: return ('gutshot', 0.09)
        return ('none', 0.03)
    else:
        if is_flush_draw and (is_oesd or is_gutshot): return ('combo', 0.45)
        elif is_flush_draw: return ('flush', 0.35)
        elif is_oesd: return ('oesd', 0.32)
        elif is_gutshot: return ('gutshot', 0.15)
        return ('none', 0.05)


def has_draw(c_ints, is_turn=False):
    cat, _ = draw_potential(c_ints, is_turn=is_turn)
    return cat != 'none'


def is_board_wet(board_ints):
    if len(board_ints) < 3: return False
    suits = [0] * 4
    ranks = []
    for c in board_ints:
        suits[c & 3] += 1
        ranks.append(c >> 2)
    if max(suits) >= 3:
        return True
    ranks.sort()
    gaps = [ranks[i + 1] - ranks[i] for i in range(len(ranks) - 1)]
    connected = sum(1 for g in gaps if g <= 2)
    return (max(suits) >= 2 and connected >= 2) or (connected >= 3)


def is_river_scare_card(board_ints):
    if len(board_ints) < 5: return False
    suits = [0, 0, 0, 0]
    mask = 0
    for c in board_ints:
        suits[c & 3] += 1
        mask |= (1 << (c >> 2))
    return (max(suits) >= 3) or IS_4STRAIGHT_TABLE[mask]


def board_value_floor(board_ints):
    if len(board_ints) < 3: return 2
    suits = [0, 0, 0, 0]
    ranks = [0] * 13
    mask = 0
    for c in board_ints:
        suits[c & 3] += 1
        ranks[c >> 2] += 1
        mask |= (1 << (c >> 2))

    if max(suits) >= 4: return 5
    if IS_4STRAIGHT_TABLE[mask]: return 4
    if max(ranks) >= 3: return 6
    if sum(1 for r in ranks if r >= 2) >= 2: return 6
    elif max(ranks) == 2 and max(suits) >= 3: return 3
    return 2


def fast_preflop_score(c_ints):
    r0, r1, r2 = sorted([c >> 2 for c in c_ints], reverse=True)
    s0, s1, s2 = c_ints[0] & 3, c_ints[1] & 3, c_ints[2] & 3
    score = r0 * 4 + r1 * 2 + r2
    if r0 == r1 == r2: score += 80
    elif r0 == r1: score += 40 + r0 * 3
    elif r1 == r2: score += 35 + r1 * 3
    if s0 == s1 == s2: score += 25
    elif s0 == s1 or s0 == s2 or s1 == s2: score += 10
    gaps = (r0 - r1) + (r1 - r2)
    if gaps <= 3: score += 15
    elif gaps <= 5: score += 8
    return score


def compute_ehs(hole_ints, board_ints, dead_ints, opp_discard_int=None, flop_ints=None,
                facing_bet=False, opp_is_station=False, opp_is_maniac=False, river_bluff_freq=None,
                opp_is_rank_discarder=False, opp_raises_preflop=0, n_samples=200):
    known = set(hole_ints) | set(board_ints) | dead_ints
    if opp_discard_int is not None:
        known.add(opp_discard_int)
    avail = [c for c in FULL_DECK_INTS if c not in known]
    board_needed = 5 - len(board_ints)
    disc_rv = (opp_discard_int >> 2) if opp_discard_int is not None else -1

    # --- RIVER (Exact Evaluation) ---
    if board_needed == 0:
        my_score = eval_fast(hole_ints + board_ints)
        wins_c, total_weight = 0.0, 0.0
        bluff_freq = river_bluff_freq if river_bluff_freq is not None else (0.40 if opp_is_maniac else (0.02 if opp_is_station else 0.15))
        max_board_rank = max(c >> 2 for c in board_ints)
        v_floor = board_value_floor(board_ints)
        alt_scores = {o: flop_score(o, opp_discard_int, flop_ints) for o in avail} if not opp_is_rank_discarder and opp_discard_int is not None and flop_ints and len(flop_ints) == 3 else None

        for o1, o2 in combinations(avail, 2):
            w_pref = 1.0
            if opp_discard_int is not None and not opp_is_maniac:
                pf_score = fast_preflop_score([o1, o2, opp_discard_int])
                if opp_raises_preflop >= 1:
                    if pf_score < 45: w_pref = 0.15
                    elif pf_score < 60: w_pref = 0.50
                elif opp_raises_preflop == 0 and pf_score >= 120:
                    w_pref = 0.25

            w_disc = 1.0
            if opp_is_rank_discarder and disc_rv != -1:
                w_disc = 0.02 if min(o1 >> 2, o2 >> 2) < disc_rv else 1.0
            elif alt_scores is not None:
                s_kept = flop_score(o1, o2, flop_ints)
                s_alt1, s_alt2 = alt_scores[o1], alt_scores[o2]
                if s_kept >= s_alt1 and s_kept >= s_alt2: w_disc = 1.0
                elif s_kept >= min(s_alt1, s_alt2): w_disc = 0.40
                else: w_disc = 0.10

            s_opp = eval_fast([o1, o2] + board_ints)
            cat = s_opp[0]
            opp_ranks = {o1 >> 2, o2 >> 2}

            if facing_bet:
                if cat >= v_floor:
                    w_act = bluff_freq if (cat == 2 and (s_opp[1] - 2) not in opp_ranks and (s_opp[2] - 2) not in opp_ranks) else 1.0
                elif cat >= 2 and v_floor > 2:
                    w_act = bluff_freq if (cat == 3 and v_floor == 6 and (s_opp[1] - 2) not in opp_ranks and not any((c >> 2) in opp_ranks for c in board_ints if (c >> 2) != (s_opp[1] - 2))) else 0.05
                elif cat == 1:
                    pair_r = s_opp[1] - 2
                    w_act = bluff_freq if pair_r not in opp_ranks else (0.60 if opp_is_maniac else (0.80 if (pair_r >= max_board_rank and v_floor == 2) else 0.05))
                else:
                    w_act = bluff_freq
            else:
                if cat >= v_floor: w_act = 0.20
                elif cat >= 2: w_act = 1.00 if (cat == 2 and (s_opp[1] - 2) not in opp_ranks and (s_opp[2] - 2) not in opp_ranks) else 0.70
                elif cat == 1: w_act = 1.00 if (s_opp[1] - 2) not in opp_ranks else 0.90
                else: w_act = 1.00

            w_total = w_pref * w_disc * w_act
            if my_score > s_opp: wins_c += 1.0 * w_total
            elif my_score == s_opp: wins_c += 0.5 * w_total
            total_weight += w_total

        equity = wins_c / max(total_weight, 1.0)
        return equity, 0.0, 0.0, equity

    # --- FLOP / TURN (Transition Matrix) ---
    my_curr = eval_fast(hole_ints + board_ints)
    hp = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
    b_suits = [0] * 4
    b_mask = 0
    for c in board_ints:
        b_suits[c & 3] += 1
        b_mask |= (1 << (c >> 2))
    max_b_suit = max(b_suits)
    is_turn_4straight = IS_4STRAIGHT_TABLE[b_mask]

    valid_samples, attempts, max_attempts = 0, 0, n_samples * 4
    opp_pool = [c for c in avail if (c >> 2) >= disc_rv] if (opp_is_rank_discarder and disc_rv != -1) else None
    if opp_pool and len(opp_pool) < 2: opp_pool = None
    alt_scores = {o: flop_score(o, opp_discard_int, flop_ints) for o in avail} if not opp_pool and opp_discard_int is not None and flop_ints and len(flop_ints) == 3 else None

    while valid_samples < n_samples and attempts < max_attempts:
        attempts += 1
        if opp_pool and random.random() < 0.95:
            opp = random.sample(opp_pool, 2)
            while True:
                r = random.choice(avail)
                if r != opp[0] and r != opp[1]:
                    runout = [r]
                    break
        else:
            sampled = random.sample(avail, 3)
            opp, runout = sampled[:2], [sampled[2]]
            if opp_is_rank_discarder and disc_rv != -1 and min(opp[0] >> 2, opp[1] >> 2) < disc_rv and random.random() > 0.05: continue

        if opp_discard_int is not None and not opp_is_maniac:
            pf_score = fast_preflop_score([opp[0], opp[1], opp_discard_int])
            if opp_raises_preflop >= 1 and pf_score < 45 and random.random() < 0.80: continue
            elif opp_raises_preflop == 0 and pf_score >= 120 and random.random() < 0.75: continue

        if alt_scores:
            s_kept = flop_score(opp[0], opp[1], flop_ints)
            s_alt1, s_alt2 = alt_scores[opp[0]], alt_scores[opp[1]]
            keep_prob = 1.00 if s_kept >= s_alt1 and s_kept >= s_alt2 else (0.40 if s_kept >= min(s_alt1, s_alt2) else 0.10)
            if random.random() > keep_prob: continue

        opp_curr = eval_fast(opp + board_ints)
        if facing_bet and board_needed == 1 and not opp_is_maniac:
            is_opp_air = (opp_curr[0] == 0) or (opp_curr[0] == 1 and (opp_curr[1] - 2) not in {opp[0] >> 2, opp[1] >> 2})
            if is_opp_air:
                draw_cat, _ = draw_potential(opp + board_ints, is_turn=True)
                bluff_p = river_bluff_freq if river_bluff_freq is not None else (0.02 if opp_is_station else 0.15)
                if draw_cat not in ('combo', 'flush', 'oesd') and random.random() > bluff_p: continue
            elif max_b_suit >= 4 and opp_curr[0] < 5 and random.random() > 0.05: continue
            elif is_turn_4straight and opp_curr[0] < 4 and random.random() > 0.05: continue

        valid_samples += 1
        c_idx = 0 if my_curr > opp_curr else (1 if my_curr == opp_curr else 2)
        full_b = board_ints + runout
        my_fin = eval_fast(hole_ints + full_b)
        opp_fin = eval_fast(opp + full_b)
        f_idx = 0 if my_fin > opp_fin else (1 if my_fin == opp_fin else 2)
        hp[c_idx][f_idx] += 1

    total_samples = sum(hp[0]) + sum(hp[1]) + sum(hp[2])
    if total_samples == 0: return 0.5, 0.0, 0.0, 0.5

    hs = (sum(hp[0]) + 0.5 * sum(hp[1])) / total_samples
    ppot = (hp[2][0] + 0.5 * hp[2][1] + 0.5 * hp[1][0]) / max(sum(hp[2]) + sum(hp[1]), 1)
    npot = (hp[0][2] + 0.5 * hp[0][1]) / max(sum(hp[0]), 1)
    return hs, ppot, npot, hs * (1.0 - npot) + (1.0 - hs) * ppot


def select_best_discard_ehs(hole_strs, board_strs, dead_strs, opp_raises_preflop=0, opp_is_rank_discarder=False, n_samples=200):
    hole_ints = [CARD_TO_INT[c] for c in hole_strs]
    board_ints = [CARD_TO_INT[c] for c in board_strs]
    dead_ints = {CARD_TO_INT[c] for c in dead_strs} | set(hole_ints) | set(board_ints)
    avail = [c for c in FULL_DECK_INTS if c not in dead_ints]
    candidates = [[hole_ints[1], hole_ints[2]], [hole_ints[0], hole_ints[2]], [hole_ints[0], hole_ints[1]]]
    s_my_currs = [eval_fast(c + board_ints) for c in candidates]
    hp = [[[0, 0, 0], [0, 0, 0], [0, 0, 0]] for _ in range(3)]
    
    valid_samples, attempts = 0, 0
    while valid_samples < n_samples and attempts < n_samples * 3:
        attempts += 1
        sampled = random.sample(avail, 5)
        opp3, runout = sampled[:3], sampled[3:]

        if opp_raises_preflop >= 1 and fast_preflop_score(opp3) < 55 and random.random() < 0.75: continue
        elif opp_raises_preflop == 0 and fast_preflop_score(opp3) >= 120 and random.random() < 0.70: continue

        valid_samples += 1
        full_b = board_ints + runout

        if opp_is_rank_discarder:
            opp_best = sorted(opp3, key=lambda c: (c >> 2), reverse=True)[:2]
        else:
            c0, c1, c2 = opp3[0], opp3[1], opp3[2]
            sc0, sc1, sc2 = flop_score(c0, c1, board_ints), flop_score(c0, c2, board_ints), flop_score(c1, c2, board_ints)
            opp_best = (c0, c1) if sc0 >= sc1 and sc0 >= sc2 else ((c0, c2) if sc1 >= sc2 else (c1, c2))

        s_opp_curr = eval_fast(list(opp_best) + board_ints)
        s_opp_fin = eval_fast(list(opp_best) + full_b)

        for i in range(3):
            s_my_curr = s_my_currs[i]
            s_my_fin = eval_fast(candidates[i] + full_b)
            c_idx = 0 if s_my_curr > s_opp_curr else (1 if s_my_curr == s_opp_curr else 2)
            f_idx = 0 if s_my_fin > s_opp_fin else (1 if s_my_fin == s_opp_fin else 2)
            hp[i][c_idx][f_idx] += 1

    ehs_vals, ppot_vals = [0.5]*3, [0.0]*3
    total_samples = max(valid_samples, 1)

    for i in range(3):
        na, nt, nb = sum(hp[i][0]), sum(hp[i][1]), sum(hp[i][2])
        hs = (na + 0.5 * nt) / total_samples
        ppot = (hp[i][2][0] + 0.5 * hp[i][2][1] + 0.5 * hp[i][1][0]) / max(nb + nt, 1)
        npot = (hp[i][0][2] + 0.5 * hp[i][0][1]) / max(na, 1)
        ehs_vals[i] = hs * (1.0 - npot) + (1.0 - hs) * ppot
        ppot_vals[i] = ppot

    best_idx = max(range(3), key=lambda i: ehs_vals[i] + 0.0001 * (12 - RV.get(hole_strs[i][0], 0)))
    return hole_strs[best_idx], ehs_vals[best_idx], ppot_vals[best_idx]


# ============================================================================
# OPPONENT MODEL (Tracking & Adaptation)
# ============================================================================

class OpponentModel:
    def __init__(self):
        self.hands_seen = 0
        self.vpip, self.pfr = 0, 0
        self.total_actions, self.agg_actions, self.passive_actions, self.folds = 0, 0, 0, 0
        self.discard_ranks = []
        self.fold_to_raise_count, self.faced_raise_count = 0, 0
        self.showdown_river_bets, self.showdown_river_bluffs = 0, 0.0
        self.opp_rank_discard_count, self.opp_discard_showdown_count = 0, 0
        self.rb_faced, self.rb_fold = 0, 0
        self.vb_called, self.vb_called_lost = 0, 0.0
        self.street_bet_faced = {"flop": 0, "turn": 0}
        self.street_bet_fold = {"flop": 0, "turn": 0}

    def record_street_bet_response(self, history, street):
        bet_idx = next((i for i, h in enumerate(history) if h.get("street") == street and h.get("actor") == "me" and h.get("action") == "raise"), None)
        if bet_idx is None: return
        for h in history[bet_idx + 1:]:
            if h.get("street") == street and h.get("actor") == "opp":
                self.street_bet_faced[street] += 1
                if h.get("action") == "fold": self.street_bet_fold[street] += 1
                return

    def street_fold_rate(self, street):
        return (self.street_bet_fold[street] + 1.2) / (self.street_bet_faced[street] + 3.0)

    def record_river_bet_response(self, history, bet_ehs, net):
        last_bet_idx = next((i for i, h in enumerate(history) if h.get("street") == "river" and h.get("actor") == "me" and h.get("action") == "raise"), None)
        if last_bet_idx is None: return
        resp = next((h.get("action") for h in history[last_bet_idx + 1:] if h.get("street") == "river" and h.get("actor") == "opp"), None)
        if not resp: return
        self.rb_faced += 1
        if resp == "fold": self.rb_fold += 1
        elif resp == "call" and bet_ehs >= 0.55:
            self.vb_called += 1
            if net < 0: self.vb_called_lost += 1.0
            elif net == 0: self.vb_called_lost += 0.5

    @property
    def river_fold_rate(self):
        return (self.rb_fold + 1.2) / (self.rb_faced + 3.0)

    @property
    def value_call_lose_rate(self):
        return (self.vb_called_lost + 1.0) / (self.vb_called + 3.0)

    def update(self, result, opp_discard, history, opp_hole_cards=None, board=None):
        self.hands_seen += 1
        if opp_discard and opp_discard in CARD_TO_INT:
            self.discard_ranks.append(RV.get(opp_discard[0], 7))

        if result == "showdown" and opp_hole_cards and opp_discard:
            self.opp_discard_showdown_count += 1
            if RV.get(opp_discard[0], 0) <= min([RV.get(c[0], 0) for c in opp_hole_cards]):
                self.opp_rank_discard_count += 1

        if result == "showdown" and opp_hole_cards and board and len(board) == 5:
            if any(h.get("actor") == "opp" and h.get("action") == "raise" and h.get("street") == "river" for h in history):
                self.showdown_river_bets += 1
                opp_eval = eval_fast([CARD_TO_INT[c] for c in opp_hole_cards] + [CARD_TO_INT[c] for c in board])
                opp_cat = opp_eval[0]
                if opp_cat == 0:
                    self.showdown_river_bluffs += 1.0
                elif opp_cat == 1:
                    opp_ranks = {CARD_TO_INT[c] >> 2 for c in opp_hole_cards}
                    pair_r = opp_eval[1] - 2
                    if pair_r not in opp_ranks:
                        self.showdown_river_bluffs += 1.0
                    else:
                        if pair_r < max(CARD_TO_INT[c] >> 2 for c in board):
                            self.showdown_river_bluffs += 0.5

        preflop_counted, last_actor_was_me_raise = False, False
        for h in history:
            actor, action, street = h.get("actor"), h.get("action"), h.get("street")
            if actor == "me" and action == "raise":
                last_actor_was_me_raise = True
            elif actor == "opp":
                self.total_actions += 1
                if last_actor_was_me_raise:
                    self.faced_raise_count += 1
                    if action == "fold": self.fold_to_raise_count += 1
                    last_actor_was_me_raise = False
                if action == "raise":
                    self.agg_actions += 1
                    if street == "preflop" and not preflop_counted:
                        self.vpip += 1
                        self.pfr += 1
                        preflop_counted = True
                elif action == "call":
                    self.passive_actions += 1
                    if street == "preflop" and not preflop_counted:
                        self.vpip += 1
                        preflop_counted = True
                elif action == "check": self.passive_actions += 1
                elif action == "fold": self.folds += 1

    @property
    def vpip_pct(self): return self.vpip / max(self.hands_seen, 1)

    @property
    def pfr_pct(self): return self.pfr / max(self.hands_seen, 1)

    @property
    def af(self): return (self.agg_actions + 1.0) / (self.passive_actions + 1.0)

    @property
    def fold_to_raise_pct(self): return (self.fold_to_raise_count + 0.4) / (self.faced_raise_count + 1.0)

    @property
    def is_rank_discarder(self):
        if self.opp_discard_showdown_count >= 3: return (self.opp_rank_discard_count / self.opp_discard_showdown_count) >= 0.80
        if self.opp_discard_showdown_count >= 2: return self.opp_rank_discard_count == self.opp_discard_showdown_count
        if len(self.discard_ranks) >= 3:
            avg_r, max_r = sum(self.discard_ranks) / len(self.discard_ranks), max(self.discard_ranks)
            if len(self.discard_ranks) >= 6 and avg_r <= 5.8 and max_r <= 9: return True
            if len(self.discard_ranks) >= 5 and avg_r <= 5.5 and max_r <= 8: return True
            if len(self.discard_ranks) >= 4 and avg_r <= 5.0 and max_r <= 7: return True
            if len(self.discard_ranks) == 3 and avg_r <= 4.5 and max_r <= 6: return True
        return False

    @property
    def river_bluff_freq(self):
        if self.is_maniac: return (self.showdown_river_bluffs + 1.9) / (self.showdown_river_bets + 5.0)
        elif self.is_station: return (self.showdown_river_bluffs + 0.15) / (self.showdown_river_bets + 5.0)
        else: return (self.showdown_river_bluffs + 0.8) / (self.showdown_river_bets + 5.0)

    @property
    def is_station(self):
        return self.hands_seen >= 8 and self.vpip_pct > 0.60 and self.af < 0.85 and self.fold_to_raise_pct < 0.35

    @property
    def is_maniac(self):
        if self.hands_seen >= 4 and self.pfr_pct >= 0.75 and self.af >= 3.0: return True
        if self.total_actions < 16: return False
        return self.af >= 2.0 and (self.pfr_pct >= 0.40 or self.vpip_pct >= 0.55)

    @property
    def is_nit(self):
        if self.hands_seen < 8: return False
        if self.vpip_pct < 0.32: return True
        if self.pfr_pct < 0.08 and self.af < 0.5 and self.fold_to_raise_pct > 0.50: return True
        if self.faced_raise_count >= 4 and self.fold_to_raise_pct > 0.65: return True
        return False


# ============================================================================
# MAIN BOT CLASS
# ============================================================================

class PokerBot:
    def __init__(self):
        self.opp_model = OpponentModel()
        self.seat = None
        self.hole_cards, self.dead_cards, self.flop_cards = [], set(), []
        self.hand_id, self.total_hands, self.hands_remaining = 0, 200, 200
        self.time_left_ms, self.cumulative_net, self.opp_raises_preflop = 30000, 0, 0
        self.my_discard, self.opp_discard = None, None
        self.river_bet_ehs, self.last_ehs, self.first_bet_streets = None, 0.5, set()

    def roll(self, tag=""):
        h = (self.hand_id * 0x9E3779B9) & 0xFFFFFFFF
        for ch in tag: h = ((h * 31) ^ ord(ch)) & 0xFFFFFFFF
        h = ((h ^ (h >> 16)) * 0x85EBCA6B) & 0xFFFFFFFF
        h = ((h ^ (h >> 13)) * 0xC2B2AE35) & 0xFFFFFFFF
        return ((h ^ (h >> 16)) & 0xFFFFFFFF) / 4294967296.0

    def get_sim_budget(self, base=150):
        avg_ms_left = max(10.0, (self.time_left_ms - 2500.0) / max(self.hands_remaining * 3, 1))
        if self.time_left_ms < 4000: return 40
        if avg_ms_left > 35.0: return int(base * 1.25)
        elif avg_ms_left > 20.0: return base
        elif avg_ms_left > 12.0: return int(base * 0.75)
        elif avg_ms_left > 6.0: return int(base * 0.50)
        return max(30, int(base * 0.30))

    def handle_init(self, msg):
        self.total_hands = self.hands_remaining = msg.get("total_hands", 200)
        self.time_left_ms = msg.get("time_bank_ms", 30000)
        self.opp_model, self.cumulative_net, self.opp_raises_preflop = OpponentModel(), 0, 0

    def handle_new_hand(self, msg):
        self.hand_id, self.hole_cards, self.seat = msg["hand_id"], list(msg["hole_cards"]), msg["seat"]
        self.my_discard, self.opp_discard, self.dead_cards, self.flop_cards = None, None, set(), []
        self.cached_discard, self.cached_flop_ehs, self.cached_flop_ppot = None, None, None
        self.opp_raises_preflop, self.river_bet_ehs, self.last_ehs, self.first_bet_streets = 0, None, 0.5, set()

    def handle_discard_result(self, msg):
        self.my_discard, self.opp_discard = msg["my_discard"], msg["opp_discard"]
        self.hole_cards = list(msg["hole_cards"])
        self.dead_cards = {self.my_discard, self.opp_discard}

    def handle_hand_result(self, msg):
        self.cumulative_net += msg.get("net", 0)
        self.hands_remaining -= 1
        for st in self.first_bet_streets: self.opp_model.record_street_bet_response(msg.get("history", []), st)
        self.first_bet_streets = set()
        if self.river_bet_ehs is not None:
            self.opp_model.record_river_bet_response(msg.get("history", []), self.river_bet_ehs, msg.get("net", 0))
            self.river_bet_ehs = None
        self.opp_model.update(msg.get("result"), msg.get("opp_discard"), msg.get("history", []), msg.get("opp_hole_cards"), msg.get("board", []))

    def choose_discard(self, req):
        hole, board = list(req["hole_cards"]), list(req["board"])
        self.flop_cards = list(board)

        if self.cached_discard and self.cached_discard in hole:
            return {"type": "discard", "card": self.cached_discard}

        best_card, best_ehs, best_ppot = select_best_discard_ehs(
            hole, board, self.dead_cards, opp_raises_preflop=self.opp_raises_preflop,
            opp_is_rank_discarder=self.opp_model.is_rank_discarder, n_samples=self.get_sim_budget(base=200)
        )
        self.cached_discard, self.cached_flop_ehs, self.cached_flop_ppot = best_card, best_ehs, best_ppot
        return {"type": "discard", "card": best_card}

    def choose_action(self, req):
        self.time_left_ms, street, board = req.get("time_left_ms", self.time_left_ms), req["street"], req.get("board", [])
        if street == "flop" and len(board) == 3: self.flop_cards = list(board)
        if street == "preflop": return self.act_preflop(req)

        reply = self.act_postflop(req)
        if street == "river" and req.get("to_call", 0) == 0 and reply.get("action") == "raise": self.river_bet_ehs = self.last_ehs
        if street in ("flop", "turn") and req.get("to_call", 0) == 0 and reply.get("action") == "raise": self.first_bet_streets.add(street)
        return reply

    def act_preflop(self, req):
        legal, to_call, pot, raises_left = req["legal_actions"], req["to_call"], req["pot"], req.get("raises_left", 0)
        is_button = (self.seat == "button")
        eq = get_preflop_equity(self.hole_cards)
        opp_raises = sum(1 for h in req.get("history", []) if h.get("actor") == "opp" and h["action"] == "raise" and h["street"] == "preflop")
        self.opp_raises_preflop = opp_raises
        pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0

        if self.opp_model.is_nit:
            if is_button and opp_raises == 0:
                if "raise" in legal and raises_left > 0: return self.build_raise(req, 0.30)
                return self.call_or_check(legal)
            elif not is_button and to_call == 0:
                if "raise" in legal and raises_left > 0: return self.build_raise(req, 0.30)
                return self.call_or_check(legal)

        if eq >= 0.70:
            if "raise" in legal and raises_left > 0: return self.build_raise(req, 0.70)
            return self.call_or_check(legal)
        if eq >= 0.55:
            if to_call > 35 and eq < (0.62 if self.opp_model.is_maniac else 0.68): return self.fold_or_check(legal)
            if to_call > 20 and eq < (0.58 if self.opp_model.is_maniac else 0.60): return self.fold_or_check(legal)
            if opp_raises >= 2 and eq < (0.58 if self.opp_model.is_maniac else 0.62): return self.fold_or_check(legal)
            if opp_raises == 1 and eq < 0.66 and not self.opp_model.is_maniac: return self.call_or_check(legal)
            if "raise" in legal and raises_left > 0: return self.build_raise(req, 0.50)
            return self.call_or_check(legal)
        if eq >= 0.45:
            if opp_raises >= 2 or to_call > 15: return self.fold_or_check(legal)
            if opp_raises == 1:
                if self.opp_model.is_nit and eq < 0.52: return self.fold_or_check(legal)
                if to_call >= 8 and not self.opp_model.is_maniac and eq < 0.52: return self.fold_or_check(legal)
                if to_call <= 6 or eq >= pot_odds + 0.05: return self.call_or_check(legal)
                return self.fold_or_check(legal)
            if is_button:
                open_freq = 0.98 if self.opp_model.is_nit else (0.92 if self.opp_model.fold_to_raise_pct > 0.50 else (0.72 if self.opp_model.is_station else 0.82))
                if "raise" in legal and self.roll("pf:btn_playable") < open_freq: return self.build_raise(req, 0.30)
                return self.call_or_check(legal)
            else:
                def_freq = 0.60 if self.opp_model.fold_to_raise_pct > 0.50 else (0.00 if self.opp_model.is_station else 0.45)
                if "raise" in legal and self.roll("pf:bb_playable") < def_freq: return self.build_raise(req, 0.35)
                return self.call_or_check(legal)
        if eq >= 0.30:
            if opp_raises >= 1:
                if self.opp_model.is_nit: return self.fold_or_check(legal)
                if to_call <= 2 or (to_call <= 3 and (eq >= pot_odds or (self.opp_model.is_maniac and eq >= pot_odds - 0.03))): return self.call_or_check(legal)
                return self.fold_or_check(legal)
            if is_button:
                open_freq = 0.95 if self.opp_model.is_nit else (0.75 if self.opp_model.fold_to_raise_pct > 0.50 else (0.00 if self.opp_model.is_station else 0.50))
                if "raise" in legal and self.roll("pf:btn_marginal") < open_freq: return self.build_raise(req, 0.25)
                return self.call_or_check(legal)
            else:
                if to_call == 0 and "raise" in legal and raises_left > 0:
                    if self.opp_model.fold_to_raise_pct > 0.50 and self.roll("pf:bb_limp_iso_fold") < 0.85: return self.build_raise(req, 0.30)
                    elif not self.opp_model.is_station and eq >= 0.38 and self.roll("pf:bb_limp_iso") < 0.55: return self.build_raise(req, 0.30)
                return self.call_or_check(legal)
        
        if is_button and opp_raises == 0:
            if self.opp_model.is_nit and "raise" in legal and self.roll("pf:nit_steal") < 0.90: return self.build_raise(req, 0.25)
            elif self.opp_model.fold_to_raise_pct > 0.55 and "raise" in legal and self.roll("pf:folder_steal") < 0.85: return self.build_raise(req, 0.25)
            if eq >= 0.18 and not self.opp_model.is_maniac: return self.call_or_check(legal)
        return self.fold_or_check(legal)

    def act_postflop(self, req):
        legal, street, board, pot, to_call = req["legal_actions"], req["street"], list(req.get("board", [])), req["pot"], req["to_call"]
        my_stack, opp_stack, raises_left, history = req["my_stack"], req["opp_stack"], req.get("raises_left", 0), req.get("history", [])

        if legal == ["check"]: return {"type": "action", "action": "check"}

        hole_ints, board_ints, dead_ints = [CARD_TO_INT[c] for c in self.hole_cards], [CARD_TO_INT[c] for c in board], {CARD_TO_INT[c] for c in self.dead_cards}
        opp_disc_int = CARD_TO_INT[self.opp_discard] if self.opp_discard and self.opp_discard in CARD_TO_INT else None
        flop_ints = [CARD_TO_INT[c] for c in self.flop_cards] if self.flop_cards else board_ints[:3]
        n_samples = self.get_sim_budget(base=150)

        i_raised_preflop = any(h.get("actor") == "me" and h.get("action") == "raise" and h.get("street") == "preflop" for h in history)
        opp_raises_preflop = sum(1 for h in history if h.get("actor") == "opp" and h["action"] == "raise" and h["street"] == "preflop")
        opp_bet_flop = any(h.get("actor") == "opp" and h.get("action") == "raise" and h.get("street") == "flop" for h in history)
        opp_bet_turn = any(h.get("actor") == "opp" and h.get("action") == "raise" and h.get("street") == "turn" for h in history)
        checked_through_prev = (street == "turn" and not any(h.get("action") == "raise" and h.get("street") == "flop" for h in history)) or (street == "river" and not any(h.get("action") == "raise" and h.get("street") == "turn" for h in history))

        if street == "flop":
            if self.cached_flop_ehs is not None and self.cached_discard is not None:
                ehs, best_card, ppot = self.cached_flop_ehs, self.cached_discard, self.cached_flop_ppot or 0.0
            else:
                best_card, ehs, ppot = select_best_discard_ehs(self.hole_cards, board, self.dead_cards, opp_raises_preflop, self.opp_model.is_rank_discarder, n_samples)
                self.cached_discard, self.cached_flop_ehs, self.cached_flop_ppot = best_card, ehs, ppot
            kept_ints = [c for c in hole_ints if c != CARD_TO_INT[best_card]]
            made_rank = eval_fast(kept_ints + board_ints)
            draw_cat, ppot_val = draw_potential(kept_ints + board_ints, is_turn=False)
            has_draw_flag = (draw_cat in ('combo', 'flush', 'oesd'))
            ppot = max(ppot, ppot_val)
        else:
            _, ppot, _, ehs = compute_ehs(hole_ints, board_ints, dead_ints, opp_disc_int, flop_ints, to_call > 0, self.opp_model.is_station, self.opp_model.is_maniac, self.opp_model.river_bluff_freq, self.opp_model.is_rank_discarder, opp_raises_preflop, n_samples)
            made_rank = eval_fast(hole_ints + board_ints) if len(board_ints) >= 3 else (0,)
            draw_cat, has_draw_flag = 'none', False
            if street == "turn":
                draw_cat, ppot_val = draw_potential(hole_ints + board_ints, is_turn=True)
                has_draw_flag = (draw_cat in ('combo', 'flush', 'oesd'))
                ppot = max(ppot, ppot_val)

        hand_cat, self.last_ehs = made_rank[0], ehs
        max_b_rank = max((c >> 2 for c in board_ints), default=0)
        hole_ranks = {c >> 2 for c in (hole_ints if street != "flop" else kept_ints)}
        pair_r = (made_rank[1] - 2) if hand_cat == 1 else -1
        is_second_pair_or_lower = (hand_cat == 1 and (pair_r not in hole_ranks or pair_r < max_b_rank))
        pot_odds = to_call / (pot + to_call) if to_call > 0 else 0.0
        spr = min(my_stack, opp_stack) / max(pot, 1)
        opp_raises_this_street = sum(1 for h in history if h.get("actor") == "opp" and h["action"] == "raise" and h["street"] == street)

        # 1. MONSTER / NUTS
        if ehs >= 0.85 and hand_cat >= 2:
            if opp_raises_this_street >= 2 and not self.opp_model.is_maniac:
                if to_call > 50 and ehs < 0.93 and hand_cat < 7: return self.fold_or_check(legal)
                if "raise" in legal and ehs < 0.96 and hand_cat < 7: return self.call_or_check(legal)
            if to_call == 0 and self.seat == "big_blind" and (self.opp_model.af > 1.2 or self.opp_model.is_maniac) and street in ("flop", "turn") and self.roll(f"{street}:oop_trap") < 0.75: return {"type": "action", "action": "check"}
            if to_call == 0 and self.seat == "button" and street == "flop" and not is_board_wet(board_ints) and (self.opp_model.af > 1.2 or self.opp_model.is_maniac) and self.roll("flop:dry_trap") < 0.30: return {"type": "action", "action": "check"}
            if to_call == 0 and street == "river" and ehs < 0.95 and self.opp_model.vb_called >= 4 and self.opp_model.value_call_lose_rate >= 0.50: return self.build_raise(req, 0.30)
            if "raise" in legal and raises_left > 0:
                if street == "river":
                    v_floor = board_value_floor(board_ints)
                    sizing = 0.50 if (hand_cat < 3 or (hand_cat < 4 and (is_board_wet(board_ints) or v_floor >= 3))) else (1.00 if ehs >= 0.95 and (self.opp_model.is_station or self.opp_model.fold_to_raise_pct < 0.35) else (0.85 if ehs >= 0.98 else (0.85 if spr < 2.0 else 0.70)))
                else: sizing = 0.85 if spr < 2.0 else 0.65
                return self.build_raise(req, sizing)
            return self.call_or_check(legal)

        # 2. VERY STRONG
        if ehs >= 0.70:
            if to_call == 0:
                if street == "river":
                    if hand_cat < board_value_floor(board_ints) or (self.opp_model.vb_called >= 4 and self.opp_model.value_call_lose_rate >= 0.50): return {"type": "action", "action": "check"}
                    if "raise" in legal and raises_left > 0: return self.build_raise(req, 0.75 if self.opp_model.is_station else (0.65 if self.opp_model.is_maniac else 0.45))
                    return {"type": "action", "action": "check"}
                if "raise" in legal and raises_left > 0: return self.build_raise(req, 0.75 if self.opp_model.is_station else (0.60 if spr > 2.5 else 0.70))
                return {"type": "action", "action": "check"}
            else:
                if opp_raises_this_street >= 2 and hand_cat <= 1: return self.fold_or_check(legal)
                if street == "turn" and opp_raises_this_street >= 1 and any(h.get("actor") == "me" and h.get("action") == "raise" and h.get("street") == "turn" for h in history) and hand_cat <= 1 and not self.opp_model.is_maniac: return self.fold_or_check(legal)
                if street == "river" and (to_call > 50 or to_call > pot * 1.25) and not self.opp_model.is_maniac and self.opp_model.river_bluff_freq < 0.22:
                    v_floor = board_value_floor(board_ints)
                    if hand_cat < 3 and not (hand_cat == 2 and v_floor == 2 and ehs >= 0.75): return self.fold_or_check(legal)
                    if hand_cat <= 3 and (is_board_wet(board_ints) or v_floor >= 3) and ehs < 0.82: return self.fold_or_check(legal)
                if street == "river" and to_call > 50 and not self.opp_model.is_maniac and self.opp_model.river_bluff_freq < 0.22 and hand_cat < 2: return self.fold_or_check(legal)
                if street in ("flop", "turn") and "raise" in legal and raises_left > 0 and opp_raises_this_street <= 1:
                    if ehs >= 0.76 and hand_cat >= 2 and (to_call <= 18 or self.opp_model.is_station or self.opp_model.is_maniac): return self.build_raise(req, 0.60 if spr > 2.5 else 0.70)
                if ehs >= pot_odds + (0.00 if self.opp_model.is_maniac else 0.02): return self.call_or_check(legal)
                return self.fold_or_check(legal)

        # 3. SOLID MADE HAND
        if ehs >= 0.55:
            if to_call == 0:
                if street == "river":
                    if self.opp_model.is_station and "raise" in legal and raises_left > 0 and self.roll("river:station_val") < 0.60: return self.build_raise(req, 0.40)
                    return {"type": "action", "action": "check"}
                bet_freq = 0.75 if self.seat == "button" else 0.55
                if street == "turn" and checked_through_prev: bet_freq = 0.88
                if self.opp_model.is_nit: bet_freq = 1.00
                elif self.opp_model.fold_to_raise_pct > 0.50: bet_freq = 0.90
                if "raise" in legal and raises_left > 0 and self.roll(f"{street}:val_bet") < bet_freq: return self.build_raise(req, 0.40)
                return {"type": "action", "action": "check"}
            else:
                if street == "river" and self.opp_model.is_station and self.opp_model.river_bluff_freq <= 0.10 and hand_cat < 2: return self.fold_or_check(legal)
                if street == "flop" and not self.opp_model.is_maniac and opp_raises_this_street >= 1 and any(h.get("actor") == "me" and h.get("action") == "raise" and h.get("street") == "flop" for h in history):
                    if to_call >= 12 and (hand_cat == 0 or is_second_pair_or_lower) and not (has_draw_flag or ppot >= 0.22): return self.fold_or_check(legal)
                if opp_raises_this_street >= 2 and hand_cat <= 1: return self.fold_or_check(legal)
                if street == "turn" and not self.opp_model.is_maniac:
                    if (opp_bet_flop or opp_raises_preflop >= 1) and (to_call > 20 or to_call > pot * 0.40):
                        if (hand_cat == 0 or is_second_pair_or_lower) and not (has_draw_flag or ppot >= 0.20): return self.fold_or_check(legal)
                    if opp_raises_this_street >= 1 and any(h.get("actor") == "me" and h.get("action") == "raise" and h.get("street") == "turn" for h in history):
                        if hand_cat <= 1 and draw_cat != 'combo': return self.fold_or_check(legal)
                if street == "river" and opp_bet_flop and opp_bet_turn and to_call > 20 and not self.opp_model.is_maniac and self.opp_model.river_bluff_freq < 0.22 and hand_cat <= 1: return self.fold_or_check(legal)
                if street == "river" and (to_call > 50 or to_call > pot * 1.25) and not self.opp_model.is_maniac and self.opp_model.river_bluff_freq < 0.22:
                    v_floor = board_value_floor(board_ints)
                    if hand_cat < 3 and not (hand_cat == 2 and v_floor == 2 and ehs >= 0.75): return self.fold_or_check(legal)
                    if hand_cat <= 3 and (is_board_wet(board_ints) or v_floor >= 3) and ehs < 0.82: return self.fold_or_check(legal)
                
                call_margin = max(-0.04, min(0.08, 0.20 - self.opp_model.river_bluff_freq))
                if street == "river" and to_call > 40 and not self.opp_model.is_maniac: call_margin = max(0.05, call_margin)
                if ehs >= pot_odds + call_margin: return self.call_or_check(legal)
                return self.fold_or_check(legal)

        # 4. DRAWING / SEMI-BLUFF
        if ehs >= 0.35 or (street in ("flop", "turn") and (has_draw_flag or ppot >= 0.20)):
            if to_call == 0:
                cbet_freq = 0.55 if self.seat == "button" else 0.30
                if i_raised_preflop and self.seat == "button": cbet_freq = 0.72
                if ppot > 0.25 or has_draw_flag: cbet_freq += 0.25
                if self.opp_model.is_nit: cbet_freq = 1.00
                elif self.opp_model.fold_to_raise_pct > 0.55: cbet_freq = 0.85
                elif self.opp_model.is_station or self.opp_model.fold_to_raise_pct < 0.25: cbet_freq *= 0.40
                if "raise" in legal and street != "river" and self.roll(f"{street}:cbet") < cbet_freq: return self.build_raise(req, 0.38)
                return {"type": "action", "action": "check"}
            else:
                if street == "river":
                    if to_call > 20: return self.fold_or_check(legal)
                    if spr <= 0.35 and to_call <= 15 and ehs >= pot_odds: return self.call_or_check(legal)
                    if to_call <= 5 and pot >= 18 and ehs >= pot_odds: return self.call_or_check(legal)
                    if self.opp_model.is_maniac or self.opp_model.river_bluff_freq >= 0.25:
                        if hand_cat >= 1 and ehs >= pot_odds + 0.02: return self.call_or_check(legal)
                    elif hand_cat >= 1 and hand_cat >= board_value_floor(board_ints) and ehs >= pot_odds + 0.05: return self.call_or_check(legal)
                    return self.fold_or_check(legal)
                if street == "turn":
                    if not self.opp_model.is_maniac:
                        if (opp_bet_flop or opp_raises_preflop >= 1) and (to_call > 20 or to_call > pot * 0.40) and (hand_cat == 0 or is_second_pair_or_lower) and not (has_draw_flag or ppot >= 0.20): return self.fold_or_check(legal)
                        if opp_raises_this_street >= 1 and any(h.get("actor") == "me" and h.get("action") == "raise" and h.get("street") == "turn" for h in history) and hand_cat <= 1 and draw_cat != 'combo': return self.fold_or_check(legal)
                    if "raise" in legal and raises_left > 0 and opp_raises_this_street <= 1 and draw_cat == 'combo' and to_call <= 18 and self.opp_model.fold_to_raise_pct > 0.45 and not self.opp_model.is_station and self.roll("turn:semi_raise") < 0.40: return self.build_raise(req, 0.60)
                    if ehs >= pot_odds: return self.call_or_check(legal)
                    if to_call <= 22 and spr > 1.8 and (ehs + ppot * 0.20) >= pot_odds: return self.call_or_check(legal)
                    return self.fold_or_check(legal)
                if ehs >= pot_odds: return self.call_or_check(legal)
                if "raise" in legal and raises_left > 0 and opp_raises_this_street <= 1 and (draw_cat == 'combo' or (has_draw_flag and ehs >= 0.40)) and to_call <= 15 and not self.opp_model.is_station and self.opp_model.fold_to_raise_pct >= 0.30 and self.roll("flop:semi_raise") < 0.40: return self.build_raise(req, 0.55)
                if spr > 2.0 and (ehs + ppot * 0.28) >= pot_odds: return self.call_or_check(legal)
                return self.fold_or_check(legal)

        # 5. WEAK / MARGINAL
        if ehs >= 0.20:
            if to_call == 0:
                if "raise" in legal and (self.opp_model.is_nit or self.should_bluff(street, board_ints, checked_through_prev)): return self.build_raise(req, 0.40)
                return {"type": "action", "action": "check"}
            else:
                if ehs >= pot_odds: return self.call_or_check(legal)
                if street == "flop" and self.seat == "button" and to_call <= 3 and ehs >= 0.18 and not self.opp_model.is_station: return self.call_or_check(legal)
                if to_call <= 2 and pot >= 8 and self.roll(f"{street}:cheap_call") < 0.25: return self.call_or_check(legal)
                return self.fold_or_check(legal)

        # 6. PURE AIR
        if to_call == 0:
            if "raise" in legal and (self.opp_model.is_nit or self.should_bluff(street, board_ints, checked_through_prev)): return self.build_raise(req, 0.45)
            return {"type": "action", "action": "check"}
        if street == "river" or ehs < pot_odds: return self.fold_or_check(legal)
        return self.call_or_check(legal)

    def should_bluff(self, street, board_ints=None, checked_through_prev=False):
        if street == "river" and self.opp_model.rb_faced >= 5:
            rfr = self.opp_model.river_fold_rate
            if rfr >= 0.55: return self.roll("river:fold_exploit") < min(0.75, (rfr - 0.33) * 2.0)
            elif rfr < 0.33: return False
        if street in ("flop", "turn") and self.opp_model.street_bet_faced[street] >= 8 and self.opp_model.street_fold_rate(street) < 0.33: return False
        if self.opp_model.is_station or self.opp_model.fold_to_raise_pct < 0.25: return False
        if street == "river":
            if board_ints and not is_river_scare_card(board_ints): return False
            freq = 0.15 if self.opp_model.fold_to_raise_pct > 0.40 else 0.05
            if checked_through_prev: freq += 0.10
        else:
            freq = 0.26 if self.seat == "button" else 0.15
            if checked_through_prev: freq += 0.15
        if self.opp_model.is_nit: freq *= 1.8
        elif self.opp_model.fold_to_raise_pct > 0.50: freq *= 1.4
        return self.roll(f"{street}:bluff") < min(0.85, freq)

    def build_raise(self, req, sizing):
        if "raise" not in req["legal_actions"]: return self.call_or_check(req["legal_actions"])
        mn, mx, pot, to_call, opp_bet, street = req["min_raise"], req["max_raise"], req["pot"], req["to_call"], req["opp_bet"], req["street"]
        if mn >= mx: return {"type": "action", "action": "raise", "amount": mn}

        if street == "preflop":
            if to_call <= 1: target = 4 if self.opp_model.is_nit else (8 if self.opp_model.is_station and sizing >= 0.65 else (7 if self.seat == "big_blind" and sizing >= 0.50 else 5))
            else: target = int(opp_bet * 3.5) if self.opp_model.is_station and sizing >= 0.70 else (int(opp_bet * 2.5) if opp_bet >= 10 else opp_bet * 3) if sizing >= 0.70 else (opp_bet * 3 if sizing >= 0.45 else mn)
        else:
            pot_after_call = pot + to_call
            eff_sizing = sizing if street == "river" else (min(1.0, sizing + 0.10) if is_board_wet([CARD_TO_INT[c] for c in req.get("board", [])]) else max(0.25, sizing - 0.05))
            if eff_sizing >= 0.85: target = mx if (eff_sizing >= 0.95) else (opp_bet + int(pot_after_call * 0.85))
            elif eff_sizing >= 0.65: target = opp_bet + int(pot_after_call * 0.70)
            elif eff_sizing >= 0.45: target = opp_bet + int(pot_after_call * 0.50)
            else: target = opp_bet + max(3, int(pot_after_call * 0.35))

        amount = max(mn, min(mx, target))
        if amount >= mx * 0.75 and not (street == "river" and eff_sizing < 0.85): amount = mx
        return {"type": "action", "action": "raise", "amount": amount}

    @staticmethod
    def call_or_check(legal):
        return {"type": "action", "action": "check"} if "check" in legal else ({"type": "action", "action": "call"} if "call" in legal else {"type": "action", "action": "fold"})

    @staticmethod
    def fold_or_check(legal):
        return {"type": "action", "action": "check"} if "check" in legal else {"type": "action", "action": "fold"}


def fallback_action(msg):
    legal = msg.get("legal_actions", [])
    if "check" in legal: return {"type": "action", "action": "check"}
    if "call" in legal and msg.get("to_call", 999) <= 2: return {"type": "action", "action": "call"}
    return {"type": "action", "action": "fold"}

def fallback_discard(msg):
    hole = msg.get("hole_cards") or []
    if not hole: return {"type": "discard", "card": ""}
    return {"type": "discard", "card": min(hole, key=lambda c: (RV.get(c[0], 0), SUIT_ORDER.get(c[1], 0)) if c and len(c) == 2 else (0, 0))}


def main():
    bot = PokerBot()
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        try: msg = json.loads(line)
        except ValueError: continue
        if not isinstance(msg, dict): continue

        msg_type = msg.get("type")
        if msg_type == "action_request":
            try: reply = bot.choose_action(msg)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                reply = fallback_action(msg)
            print(json.dumps(reply), flush=True)
        elif msg_type == "discard_request":
            try: reply = bot.choose_discard(msg)
            except Exception:
                traceback.print_exc(file=sys.stderr)
                reply = fallback_discard(msg)
            print(json.dumps(reply), flush=True)
        elif msg_type == "match_end": break
        else:
            try:
                if msg_type == "init": bot.handle_init(msg)
                elif msg_type == "new_hand": bot.handle_new_hand(msg)
                elif msg_type == "discard_result": bot.handle_discard_result(msg)
                elif msg_type == "hand_result": bot.handle_hand_result(msg)
            except Exception:
                traceback.print_exc(file=sys.stderr)

if __name__ == "__main__":
    main()