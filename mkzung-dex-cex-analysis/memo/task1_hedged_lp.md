# Task 1. Hedging a Uniswap LP with a CEX perpetual

**Setup.** You provide liquidity to a Uniswap V2 ETH/USDT pool and deposit 50/50 by USD value at entry. Let `P` be the ETH price in USDT and `V` the total USD value deposited. A 50/50 split means `V/2` of USDT and `V/2` worth of ETH, i.e. `n = (V/2)/P` ETH in the pool at entry.

## 1. Entry hedge size

A constant-product pool holds reserves `x` (ETH) and `y` (USDT) with `x*y = k` and pool price `P = y/x`. Solving the two relations gives `x(P) = sqrt(k/P)` and `y(P) = sqrt(kP)`, so the USD value of the position is

```
W(P) = x*P + y = 2*sqrt(kP).
```

Its sensitivity to the ETH price, the delta in ETH terms, is

```
dW/dP = sqrt(k/P) = x(P),
```

which is exactly the ETH the pool is currently holding for you. At entry that is `x = n = (V/2)/P`. To first order the LP behaves like being long `n` ETH, so to make it locally delta-neutral you short the same quantity on a CEX perpetual:

```
short size = n = (V/2)/P  ETH.
```

Worked number: `V = $100,000`, `P = $2,500`. The ETH leg is `$50,000 = 20 ETH`, so you short 20 ETH-perp and net delta at entry is about zero.

**Why "locally".** The hedge is a tangent. The perp short has constant delta (-1 ETH per ETH shorted), but the LP's delta `x(P) = sqrt(k/P)` falls as `P` rises and grows as `P` falls. The combined book is delta-neutral only at the entry price. The LP is short gamma (this curvature is impermanent loss) and a static short does not offset curvature, only direction. Away from entry you re-hedge: resize the short to the new `x(P)`, or set rebalance bands and accept some tracking error between adjustments.

## 2. Other costs to account for

Removing first-order price risk does not make the trade free. What actually drives PnL:

- **LP fees earned.** The reason to do this at all. You collect the pool's swap fees on your share. This is the carry you are trying to harvest.
- **Impermanent loss (negative gamma).** Hedged or not, the LP underperforms simply holding the two assets as price moves. The delta hedge neutralizes direction, not convexity. Net edge is roughly `fees - IL - costs`.
- **Perp funding.** Holding a short perp, you pay or receive the funding rate each interval. Persistent positive funding (longs pay shorts) is income; negative funding is a cost. Over a long hold this can dominate the result.
- **Rebalancing cost.** Keeping delta near zero means trading the perp, and sometimes the LP, as price moves. Each adjustment pays exchange fees and slippage, traded off against the tracking error you accept by rebalancing less often.
- **Gas.** Entry, exit, and any on-chain rebalance cost gas. On a small position this is a real drag.
- **CEX frictions.** Taker/maker fees on the perp, margin posted against the short (capital not earning the LP yield), and liquidation risk if ETH rallies hard into a thin margin.
- **Basis and venue risk.** The perp mark can diverge from the pool price, the two venues settle on different clocks, and you carry smart-contract risk on the DEX plus counterparty risk on the CEX.

So this is a fee-harvest, short-gamma, funding-sensitive carry trade, not an arbitrage. It makes money when fees plus any favorable funding beat IL plus the running costs.

## 3. Uniswap V3, +/-10% range

Now the same capital is concentrated in a V3 range `[P_low, P_high]` set at +/-10% around `P`. Inside the range the position is still a constant-product curve, so the entry logic is unchanged in spirit: short the ETH the position currently holds. The V3 holdings at price `P` inside the range are

```
ETH held:  n = L*(1/sqrt(P) - 1/sqrt(P_high))
USDT held:     L*(sqrt(P)   - sqrt(P_low))
```

where `L` is the position's liquidity. You compute `n` from your deposit and the chosen range, then short `n` ETH at entry, the same move as in V2.

What changes is how that hedge behaves:

- **Concentration amplifies fees and gamma together.** Packing liquidity into +/-10% instead of the whole price range earns a far larger share of fees for the same capital, but delta also moves much faster with price. The static short goes stale sooner and you rebalance more often.
- **The hedge ratio is bounded by the range.** As `P` rises toward `P_high` the position rotates into USDT and its ETH holding falls to zero at the top edge. As `P` falls toward `P_low` it rotates fully into ETH and delta peaks at the bottom edge. The correct short sweeps from the whole position at the low edge to nothing at the high edge over just a +/-10% move.
- **Range exit breaks the linearity.** Once `P` leaves `[P_low, P_high]` the position is 100% one asset and earns no fees. Above the range it is all USDT with delta near zero, so a standing short becomes a naked short that must be closed. Below the range it is all ETH with constant delta equal to the full ETH amount, so it behaves like just holding ETH and the short should cover the whole position. A V3 hedger needs an explicit rule at the boundaries that a V2 hedger never reaches.

**Net.** V3 gives more fee yield per dollar and a tighter, more capital-efficient position, at the cost of much higher gamma, more frequent and costlier rebalancing, and discrete hedge changes when price crosses the range edges. The entry calculation is the same idea as V2 (short the ETH leg); the ongoing management is materially harder.
