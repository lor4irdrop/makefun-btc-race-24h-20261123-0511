#!/usr/bin/env python3
"""Paper trader for the make.fun cbBTC race, written fresh for race 0511.

The program talks the bars-replay wire: it reads newline-delimited JSON
off stdin (a hello, then one batch per minute bar, then a done) and writes
exactly one JSON reply per batch to stdout. It runs on Python 3.13 and
uses nothing but the standard library.

The approach is deliberately plain. Half of the starting cash is put into
a single anchor purchase on the first tradable bar and left alone until
the window ends, on the view that the drift of the underlying tends to
carry a race window. The rest of the cash is worked by a dip sleeve: it
steps in only when the latest close has fallen a little below its short
mean, and steps out on a modest gain, a capped loss, or after a long
enough hold. A set of guards keeps the sleeve out of falling knives and
out of deep drawdowns, because the race ranks anything that breaches
its guardrails below every entry that stays inside them.

Every number here is an integer in the scales the hello message declares,
so the same input always produces the same replies byte for byte.
"""

import json
import sys

BPS_DENOM = 10_000

# --- strategy knobs (basis points unless noted) ---
ANCHOR_SHARE_BPS = 5_000    # share of the starting cash the anchor leg takes
PLUNGE_GAP_BPS = 30         # close must trail the 4-bar mean by at least this
PLUNGE_FLUSH_BPS = 200      # further under the 4-bar mean than this: a flush
TAKE_BPS = 60               # bank the dip leg at this gain over its fill
STOP_BPS = 120              # cut the dip leg at this loss under its fill
HOLD_LIMIT = 240            # bars after which a dip leg is closed regardless
REST_BARS = 10              # bars to wait after a dip leg closes
LONG_MEAN_BARS = 120        # bars in the slow mean behind the deep-drop guard
SHORT_MEAN_BARS = 4         # bars in the fast mean behind the dip trigger
DEEP_DROP_BPS = 300         # no dip buys while the close trails the slow mean more
FREEZE_DD_BPS = 1_800       # no new dip legs once the drawdown passes this
BAIL_DD_BPS = 2_000         # close an open dip leg once the drawdown passes this
SLIP_BPS = 100              # slack allowed on each order's fill


def _mean_tail(closes, span):
    """Mean of the last `span` closes, or of however many exist."""
    tail = closes[-span:]
    return sum(tail) // len(tail)


def _gap_bps(reference, price):
    """How far `price` sits under `reference`, in basis points."""
    return (reference - price) * BPS_DENOM // reference


class Desk:
    """The run state: what the account holds and what each leg is doing."""

    def __init__(self, hello):
        first = hello["symbols"][0]
        self.symbol = first["symbol"]
        self.price_scale = first["price_scale"]
        self.qty_scale = first["qty_scale"]
        self.quote_scale = hello["capital"]["quote_scale"]
        self.start_cash = int(hello["capital"]["quote_units"])
        self.caps = hello["caps"]
        self.min_spend = int(hello["fees"]["min_notional_quote_units"])
        self.warmup = hello.get("warmup_bars", 0)
        self.closes = []
        self.equity = self.start_cash
        self.cash = self.start_cash
        self.peak = self.start_cash
        self.anchor = "idle"        # idle | sent | held
        self.anchor_qty = 0
        self.plunge = "flat"        # flat | sent | open | closing
        self.plunge_qty = 0
        self.plunge_fill_price = 0
        self.plunge_fill_seq = -1
        self.last_close_seq = -10 ** 9
        self.tag = 0

    def worth(self, qty, price):
        """What `qty` is worth at `price`, in quote units, truncated."""
        return qty * price * 10 ** self.quote_scale // 10 ** (self.qty_scale + self.price_scale)

    def room(self, equity):
        """How much a new buy may spend under the weight cap."""
        held = self.worth(self.anchor_qty + self.plunge_qty, self.closes[-1]) if self.closes else 0
        head = self.caps["max_weight_bps"] * equity // BPS_DENOM - held
        return head if head > 0 else 0

    def drawdown_bps(self):
        """Current drawdown from the equity peak, in basis points."""
        if self.peak <= 0:
            return 0
        return (self.peak - self.equity) * BPS_DENOM // self.peak

    def absorb(self, batch):
        """Fold a batch into the state: its fills, its bars, its account."""
        seq = batch["seq"]
        for fill in batch.get("fills", []):
            if fill.get("status") == "filled":
                self._landed(fill, seq)
            else:
                self._missed(fill)
        for bar in batch.get("bars", []):
            if bar.get("symbol") == self.symbol:
                self.closes.append(int(bar["c"]))
        acct = batch.get("account", {})
        self.equity = int(acct.get("equity_quote_units", self.peak))
        self.cash = int(acct.get("cash_quote_units", 0))
        if self.equity > self.peak:
            self.peak = self.equity

    def _landed(self, fill, seq):
        """Record a fill that went through."""
        tag = fill.get("client_id", "")
        if fill.get("side") == "buy":
            if tag == "anchor":
                self.anchor = "held"
                self.anchor_qty = int(fill["qty"])
            elif tag.startswith("plunge-"):
                self.plunge = "open"
                self.plunge_qty = int(fill["qty"])
                self.plunge_fill_price = int(fill["price"])
                self.plunge_fill_seq = seq
        elif tag.startswith("release-"):
            self.plunge = "flat"
            self.plunge_qty = 0
            self.last_close_seq = seq

    def _missed(self, fill):
        """A rejected fill frees its leg to be tried again."""
        tag = fill.get("client_id", "")
        if fill.get("side") == "buy":
            if tag == "anchor":
                self.anchor = "idle"
            elif tag.startswith("plunge-"):
                self.plunge = "flat"
        elif tag.startswith("release-"):
            self.plunge = "open"

    def _should_bail(self, close, seq):
        """Whether an open dip leg must be closed on this bar."""
        if self.drawdown_bps() > BAIL_DD_BPS:
            return True
        if close * BPS_DENOM >= self.plunge_fill_price * (BPS_DENOM + TAKE_BPS):
            return True
        if close * BPS_DENOM <= self.plunge_fill_price * (BPS_DENOM - STOP_BPS):
            return True
        if seq - self.plunge_fill_seq >= HOLD_LIMIT:
            return True
        return False

    def _dip_ok(self, close, seq):
        """Whether a fresh dip leg may be opened on this bar."""
        if len(self.closes) < SHORT_MEAN_BARS:
            return False
        if seq - self.last_close_seq < REST_BARS:
            return False
        if self.drawdown_bps() > FREEZE_DD_BPS:
            return False
        fast = _mean_tail(self.closes, SHORT_MEAN_BARS)
        gap = _gap_bps(fast, close)
        if gap < PLUNGE_GAP_BPS or gap > PLUNGE_FLUSH_BPS:
            return False
        slow = _mean_tail(self.closes, LONG_MEAN_BARS)
        if _gap_bps(slow, close) > DEEP_DROP_BPS:
            return False
        return True

    def _buy(self, tag, spend):
        return {"side": "buy", "client_id": tag, "symbol": self.symbol,
                "notional_quote_units": str(spend), "max_slippage_bps": SLIP_BPS}

    def _sell(self):
        self.tag += 1
        return {"side": "sell", "client_id": "release-%d" % self.tag,
                "symbol": self.symbol, "qty": str(self.plunge_qty),
                "max_slippage_bps": SLIP_BPS}

    def answer(self, batch):
        """Decide the orders for one batch; at most one order per reply."""
        seq = batch["seq"]
        self.absorb(batch)
        if seq < self.warmup or not self.closes:
            return []
        close = self.closes[-1]
        if self.anchor == "idle":
            spend = min(self.start_cash * ANCHOR_SHARE_BPS // BPS_DENOM,
                        self.cash, self.room(self.equity))
            if spend >= self.min_spend:
                self.anchor = "sent"
                return [self._buy("anchor", spend)]
            return []
        if self.anchor != "held":
            return []
        if self.plunge == "open":
            if self._should_bail(close, seq):
                self.plunge = "closing"
                return [self._sell()]
            return []
        if self.plunge == "flat" and self._dip_ok(close, seq):
            spend = min(self.cash, self.room(self.equity))
            if spend >= self.min_spend:
                self.tag += 1
                self.plunge = "sent"
                return [self._buy("plunge-%d" % self.tag, spend)]
        return []


def main():
    desk = None
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        msg = json.loads(line)
        kind = msg.get("type")
        if kind == "hello":
            desk = Desk(msg)
        elif kind == "batch":
            if desk is None:
                continue
            orders = desk.answer(msg)
            sys.stdout.write(json.dumps(
                {"type": "reply", "seq": msg["seq"], "orders": orders},
                separators=(",", ":")) + "\n")
            sys.stdout.flush()
        elif kind == "done":
            break


if __name__ == "__main__":
    main()
