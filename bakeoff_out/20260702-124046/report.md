# Generation bake-off report

- run (UTC): 2026-07-02T12:43:34.873306+00:00
- crop source: photo items of guykalir19@gmail.com
- crops: 5
- providers: flux_kontext, seedream, nano_banana
- verify: two-image pass (gemini-2.5-flash-lite)
- estimated spend: $1.028 (actual generation spend: $0.870)

## Per-provider results

| provider | attempts | generated | gen-fail | acct-skip | pass | fail | skipped | logo! | pattern! | pass-rate | mean score | mean latency (s) | gen cost ($) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| flux_kontext | 5 | 5 | 0 | 0 | 3 | 2 | 0 | 2 | 1 | 60% | 0.69 | 10.6 | 0.200 |
| seedream | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | — | 0.000 |
| nano_banana | 5 | 5 | 0 | 0 | 2 | 2 | 1 | 2 | 1 | 50% | 0.64 | 17.3 | 0.670 |

## Mean verify score by category (non-skipped verifies only)

| category | flux_kontext | seedream | nano_banana |
|---|--:|--:|--:|
| shoes | 0.90 | — | 0.90 |
| bottom | 0.90 | — | — |
| outerwear | 0.95 | — | 0.70 |
| top | 0.35 | — | 0.47 |

## Recommended defaults

- shoes          -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.90, $0.040/img)
- bottom         -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.90, $0.040/img)
- outerwear      -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.95, $0.040/img)
- top            -> nano_banana   (pass 1/2 scored, pass-rate 50%, mean score 0.47, $0.134/img)
- OVERALL        -> flux_kontext  (pass 3/5 scored, pass-rate 60%, mean score 0.69, $0.040/img)
