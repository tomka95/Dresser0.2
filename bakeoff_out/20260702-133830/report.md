# Generation bake-off report

- run (UTC): 2026-07-02T13:41:13.403918+00:00
- crop source: photo items of guykalir19@gmail.com
- crops: 5
- providers: flux_kontext, seedream, nano_banana
- verify: two-image pass (gemini-2.5-flash-lite)
- estimated spend: $1.028 (actual generation spend: $0.870)

## Per-provider results

| provider | attempts | generated | gen-fail | acct-skip | pass | fail | skipped | logo! | pattern! | pass-rate | mean score | mean latency (s) | gen cost ($) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| flux_kontext | 5 | 5 | 0 | 0 | 4 | 1 | 0 | 1 | 1 | 80% | 0.76 | 10.5 | 0.200 |
| seedream | 5 | 0 | 0 | 5 | 0 | 0 | 0 | 0 | 0 | — | — | — | 0.000 |
| nano_banana | 5 | 5 | 0 | 0 | 3 | 1 | 1 | 0 | 0 | 75% | 0.70 | 16.5 | 0.670 |

## Mean verify score by category (non-skipped verifies only)

| category | flux_kontext | seedream | nano_banana |
|---|--:|--:|--:|
| shoes | 0.95 | — | 0.90 |
| bottom | 0.90 | — | 0.90 |
| outerwear | 0.90 | — | — |
| top | 0.53 | — | 0.50 |

## Recommended defaults

- shoes          -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.95, $0.040/img)
- bottom         -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.90, $0.040/img)
- outerwear      -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.90, $0.040/img)
- top            -> flux_kontext  (pass 1/2 scored, pass-rate 50%, mean score 0.53, $0.040/img)
- OVERALL        -> flux_kontext  (pass 4/5 scored, pass-rate 80%, mean score 0.76, $0.040/img)
