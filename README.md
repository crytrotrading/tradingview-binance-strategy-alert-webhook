# tradingview-binance-strategy-alert-webhook
TradingView Strategy Alert Webhook that buys and sells crypto with the Binance API

## Dragon Pattern indicator

`dragon_pattern_indicator.pine` is a Pine Script v6 overlay for detecting a
bullish Dragon reversal:

1. Head: confirmed pivot high.
2. Front foot: first pivot low.
3. Back: lower pivot high with a configurable minimum retracement.
4. Rear foot: second low near the first low, without a material breakdown.
5. Tail: a close above the back, optionally confirmed by volume and EMA.

When a breakout is confirmed, the indicator draws Entry, ATR-based Stop Loss,
and Risk/Reward Target levels. It also exposes TradingView alerts for confirmed
breakouts and invalidated setups.

To install it, open TradingView's Pine Editor, paste the contents of
`dragon_pattern_indicator.pine`, save, and select **Add to chart**. Start with
the default settings, then adjust Pivot bars and foot tolerance to the market
and timeframe. Alerts should use **Once Per Bar Close** because the setup is
defined by closing-price confirmation.

## YouTube tutorial on how to use this code

https://www.youtube.com/watch?v=gMRee2srpe8
