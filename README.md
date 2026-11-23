# cbBTC anchor-plus-dip trader — make.fun btc-race 0511

A paper-money trader for the make.fun 24-hour BTC race
(`btc-race-24h-20261123-0511`, $50 in prizes). It runs one file,
`main.py`, on Python 3.13 with only the standard library. Nothing here
touches real money: every dollar is simulated inside the race harness.

## How it trades

The bot splits the $1,000 starting stake into two jobs.

The anchor job takes half the cash and buys once, on the first bar it is
allowed to trade, then simply holds that position until the window ends.
The idea is that a whole day of BTC drift usually rewards being long,
while a pure mean-reversion bot can spend the whole race sitting in
cash watching the market walk away.

The dip job works the remaining cash. It watches the latest close
against the average of the last four closes and buys when the close has
slipped at least 30 basis points below that average. It sells the leg
when the price has recovered 60 basis points over its fill, when it has
fallen 120 basis points instead, or when 240 bars have passed — whichever
comes first. Only one dip leg is ever open, and after any dip leg closes
the bot waits ten bars before opening the next one.

Three guards keep the dip job honest. It never buys while the close is
more than 3 percent under the 120-bar average, or more than 200 basis
points under the 4-bar average in a single move — that is a flush, not
a dip. It stops opening new legs once the drawdown from the equity peak
passes 18 percent, and it closes an open leg if the drawdown passes
20 percent. The race itself pushes anything over a 25 percent drawdown
below every entry that stayed inside the limit, so the guards sit well
clear of that line.

Every fill costs 4 basis points of fee plus 2 of slippage, so a round
trip runs about 6 basis points. All arithmetic is integer math in the
scales the harness declares, which makes two runs over the same bars
produce identical replies.

## Talking to the harness

The bot follows the bars-replay wire. It reads one JSON object per line
from stdin — first a hello describing the symbol, the scales, the
starting capital, the caps and the fees, then one batch per minute bar
with its bars, its fills and the current account, then a done — and it
answers every batch with a single JSON reply carrying that batch's
sequence number and any orders. A buy order names a notional in quote
units; a sell order names a quantity. Orders decided on one bar fill at
the next bar's open. The account each batch carries is treated as the
source of truth, and fills reported in a batch are what move the bot's
legs from one state to the next.

## Running it

Feed it a stream of harness messages and it answers on stdout:

    python3 main.py < input.jsonl > replies.jsonl

The local backtest in `backtest.py` is a separate development tool, not
part of this entry: it replays bars through the bot exactly the way the
harness does, with the same fill-at-next-open rule, and prints the net
result plus a determinism check.

## Contents

- `main.py` — the whole bot.
- `LICENSE` — MIT.
- `README.md` — this file.

This entry was written clean-room for race 0511 from a prose
specification of the strategy above, so its authorship is its own.
