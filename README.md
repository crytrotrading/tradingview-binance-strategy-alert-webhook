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
`dragon_pattern_indicator.pine`, save, and select **Add to chart**. Alerts
should use **Once Per Bar Close** because the setup is defined by closing-price
confirmation.

A status table in the top-right corner always reports what the indicator
currently sees, so an empty chart can be told apart from a broken script. While
no dragon is present it reads "ยังไม่พบโครงสร้างมังกร" and pivot markers still
appear on the chart.

If no setup is ever found on your market, loosen the structure settings: raise
the foot tolerance and the maximum rear-foot undercut, lower the minimum head
drop and the minimum back retracement, or reduce the pivot bars so smaller
swings qualify. Note that pivots are only confirmed `rightBars` bars after they
form, so the dragon anatomy is drawn with that delay.

## YouTube tutorial on how to use this code

https://www.youtube.com/watch?v=gMRee2srpe8
