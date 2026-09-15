"""options_desk — daily pre-open option-trade alert desk (paper/advisory only).

Reads the qlib_lab vol_desk signal flag (VRP richness + surprise-shift + magnitude
proxy + vol surface) fail-safe, builds a ranked multi-strategy option candidate set
with Black-Scholes estimates, publishes a candidate flag + history, and pushes a
Telegram alert. Serves a 127.0.0.1 UI. NEVER touches a broker; the human places
every order. Robinhood enrichment (P3) is read-only.
"""
