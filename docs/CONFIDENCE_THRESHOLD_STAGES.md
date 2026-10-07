# Jev confidence threshold stages

On 2026-10-07 the user requested lowering the prospective confidence gate from
75% to **60%**, then reviewing increases in stages. Equality is eligible:
confidence >= 0.60. This applies to new Jev shadow simulations and the existing
Jev Alpaca Paper executor. It does not change the frozen Options-System
hypothesis predicates or the separate local LIVE_PAPER virtual balance.

`engine.CONFIG['threshold']` is the single active source for simulation entry,
the broker paper entry gate, the results API and the calibration report header.
The dashboard reads the active value from the API. Each decision retains its
original execution configuration, so the Comparator and historical outcome
replay preserve the policy used when the decision was created. Historical 75%
decisions are not retroactively converted into 60% entries. Diagnostics count
eligibility against each decision's own frozen threshold and segment outcomes
by execution configuration. Confidence bands include 60–65%, 65–70%, 70–75%
and higher bands for descriptive review.

Proposed review sequence: **60% -> 65% -> 70% -> 75%**. These are review steps,
not automatic scheduled changes. Gather an initial block of at least 10 market
sessions and assess nonoverlapping completed opportunities before reviewing
the first increase; extend the block if labels are scarce. Keep a primary
review at 30 market sessions. Review gross/net P&L where supported, drawdown,
entry frequency and contract eligibility, and validate any chosen threshold
on later sessions. A confidence score is not a validated probability of profit.

The one-contract cap, executable-contract filters, TP/SL, holding period and
existing paper account risk controls remain in force. Provider responses stay
unchanged. The calibration report remains advisory and never applies a mapping
or threshold automatically.
