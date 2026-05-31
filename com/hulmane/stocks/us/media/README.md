# Stock logos

Drop ticker logos here as `<TICKER>.png` (or `.svg` / `.jpg` / `.jpeg` / `.webp`).
The dashboard looks them up at render time.

Examples:

```
media/
├── AAPL.png
├── AVGO.png
├── NVDA.svg
└── README.md   ← this file
```

If a ticker has no file in this folder, the dashboard auto-generates a
deterministic gradient letter-avatar so every row in the holdings table still
gets a colorful icon. Lookup is case-insensitive and strips trailing `**` (used
by Fidelity for cash sweeps).

Suggested sources for free, properly licensed logos:
- Vendor's own newsroom / press kit page (most permissive)
- The company's Wikipedia article (check the file's license)
- Clearbit Logo API: `https://logo.clearbit.com/<companydomain>` — fast lookup
  by domain, but verify their current ToS before redistributing

Keep files small (≤ 256×256 PNG, or SVG) — they're loaded inline as data URLs.
