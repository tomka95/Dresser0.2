# Generation bake-off report

- run (UTC): 2026-07-02T14:04:11.060587+00:00
- crop source: photo items of guykalir19@gmail.com
- crops: 5
- providers: flux_kontext, seedream, nano_banana
- verify: two-image pass (gemini-2.5-flash)
- estimated spend: $1.028 (actual generation spend: $0.870)

## Per-provider results

| provider | attempts | generated | gen-fail | acct-skip | pass | fail | skipped | logo! | pattern! | pass-rate | mean score | mean latency (s) | gen cost ($) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| flux_kontext | 5 | 5 | 0 | 0 | 2 | 3 | 0 | 2 | 0 | 40% | 0.73 | 11.5 | 0.200 |
| seedream | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | — | 0.000 |
| nano_banana | 5 | 5 | 0 | 0 | 4 | 1 | 0 | 1 | 0 | 80% | 0.92 | 16.9 | 0.670 |

## Mean verify score by category (non-skipped verifies only)

| category | flux_kontext | seedream | nano_banana |
|---|--:|--:|--:|
| shoes | 0.90 | — | 1.00 |
| bottom | 0.60 | — | 1.00 |
| outerwear | 0.95 | — | 0.60 |
| top | 0.60 | — | 1.00 |

## Recommended defaults

- shoes          -> nano_banana   (pass 1/1 scored, pass-rate 100%, mean score 1.00, $0.134/img)
- bottom         -> nano_banana   (pass 1/1 scored, pass-rate 100%, mean score 1.00, $0.134/img)
- outerwear      -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.95, $0.040/img)
- top            -> nano_banana   (pass 2/2 scored, pass-rate 100%, mean score 1.00, $0.134/img)
- OVERALL        -> nano_banana   (pass 4/5 scored, pass-rate 80%, mean score 0.92, $0.134/img)
