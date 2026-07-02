# Generation bake-off report

- run (UTC): 2026-07-02T12:18:03.077032+00:00
- crop source: photo items of guykalir19@gmail.com
- crops: 4
- providers: flux_kontext, seedream, nano_banana
- verify: two-image pass (gemini-2.5-flash-lite)
- estimated spend: $0.822 (actual generation spend: $0.696)

## Per-provider results

| provider | attempts | generated | gen-fail | pass | fail | skipped | logo! | pattern! | pass-rate | mean score | mean latency (s) | gen cost ($) |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| flux_kontext | 4 | 4 | 0 | 3 | 1 | 0 | 0 | 0 | 75% | 0.71 | 10.0 | 0.160 |
| seedream | 4 | 0 | 4 | 0 | 0 | 0 | 0 | 0 | — | — | — | 0.000 |
| nano_banana | 4 | 4 | 0 | 2 | 1 | 1 | 1 | 1 | 67% | 0.63 | 16.4 | 0.536 |

## Mean verify score by category (non-skipped verifies only)

| category | flux_kontext | seedream | nano_banana |
|---|--:|--:|--:|
| shoes | 0.10 | — | 0.90 |
| bottom | 0.90 | — | — |
| outerwear | 0.90 | — | 0.90 |
| top | 0.95 | — | 0.10 |

## Recommended defaults

- shoes          -> nano_banana   (pass 1/1 scored, pass-rate 100%, mean score 0.90, $0.134/img)
- bottom         -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.90, $0.040/img)
- outerwear      -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.90, $0.040/img)
- top            -> flux_kontext  (pass 1/1 scored, pass-rate 100%, mean score 0.95, $0.040/img)
- OVERALL        -> flux_kontext  (pass 3/4 scored, pass-rate 75%, mean score 0.71, $0.040/img)
