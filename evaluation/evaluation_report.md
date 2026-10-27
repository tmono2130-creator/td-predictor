# NFL PM historical model evaluation

All rows are retrospective backfills conditioned on verified offensive participation; metrics do not establish genuine pregame forecasting accuracy on the full player pool.
Week cutoffs are enforced, but upstream data vintages are not archived, so later corrections to earlier-week source statistics cannot be ruled out.
The V5 fixed estimate curve was excluded; V5 ranking score was calibrated using each fold's earlier seasons only.
Validation season: 2024; test season: 2025.
Training data seasons available: [2023, 2024, 2025]; numeric features: ['opportunity_score', 'red_zone_score', 'efficiency_score', 'opportunities_pg', 'redzone_opportunity_pg', 'td_rate', 'targets_pg', 'carries_pg', 'receptions_pg', 'target_share', 'receiving_yards_pg', 'rushing_yards_pg', 'matchup_score', 'team_environment_score', 'is_home', 'days_rest', 'recent_ppg', 'recent_points_allowed', 'opp_recent_ppg', 'opp_recent_points_allowed', 'role_score', 'games'].
V5 weights are unchanged. Neither 2024 nor 2025 is an independent V5 test: weight development used evidence from both years. V5 metrics are descriptive only.

## Overall metrics

| Model | N | Scorers | Actual | Predicted | Bias | Brier | Log loss | AUC | ECE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| V5 ranking score + train-only isotonic | 12886 | 2201 | 0.1708 | 0.1645 | -0.0063 | 0.12829 | 0.41023 | 0.7304 | 0.01029 |
| Logistic regression | 12886 | 2201 | 0.1708 | 0.1633 | -0.0075 | 0.12534 | 0.40146 | 0.7503 | 0.01647 |
| Gradient boosting | 12886 | 2201 | 0.1708 | 0.1642 | -0.0066 | 0.12543 | 0.40192 | 0.7468 | 0.01054 |
| Opportunity logistic baseline | 12886 | 2201 | 0.1708 | 0.1630 | -0.0078 | 0.12556 | 0.40218 | 0.7476 | 0.01427 |
| Prior player TD rate (shrunk) | 12886 | 2201 | 0.1708 | 0.1761 | +0.0053 | 0.12837 | 0.41324 | 0.7203 | 0.00758 |
| Recent six TD frequency (smoothed) | 12886 | 2201 | 0.1708 | 0.1728 | +0.0019 | 0.13133 | 0.42599 | 0.6994 | 0.02895 |
| Training position/global rate | 12886 | 2201 | 0.1708 | 0.1635 | -0.0073 | 0.13915 | 0.44868 | 0.5957 | 0.00734 |

## Validation and test results by season

| Season | Model | N | Scorers | Actual | Predicted | Bias | Brier | Log loss | AUC | ECE |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024 | V5 ranking score + train-only isotonic | 6457 | 1105 | 0.1711 | 0.1601 | -0.0110 | 0.12851 | 0.41067 | 0.7308 | 0.01505 |
| 2025 | V5 ranking score + train-only isotonic | 6429 | 1096 | 0.1705 | 0.1688 | -0.0017 | 0.12807 | 0.40979 | 0.7305 | 0.00706 |
| 2024 | Logistic regression | 6457 | 1105 | 0.1711 | 0.1605 | -0.0106 | 0.12505 | 0.40031 | 0.7548 | 0.01880 |
| 2025 | Logistic regression | 6429 | 1096 | 0.1705 | 0.1660 | -0.0045 | 0.12563 | 0.40262 | 0.7464 | 0.01486 |
| 2024 | Gradient boosting | 6457 | 1105 | 0.1711 | 0.1600 | -0.0111 | 0.12550 | 0.40246 | 0.7492 | 0.01405 |
| 2025 | Gradient boosting | 6429 | 1096 | 0.1705 | 0.1684 | -0.0021 | 0.12536 | 0.40138 | 0.7454 | 0.00900 |
| 2024 | Opportunity logistic baseline | 6457 | 1105 | 0.1711 | 0.1595 | -0.0117 | 0.12602 | 0.40304 | 0.7492 | 0.02089 |
| 2025 | Opportunity logistic baseline | 6429 | 1096 | 0.1705 | 0.1666 | -0.0039 | 0.12509 | 0.40132 | 0.7466 | 0.01207 |
| 2024 | Prior player TD rate (shrunk) | 6457 | 1105 | 0.1711 | 0.1711 | -0.0001 | 0.12697 | 0.40924 | 0.7289 | 0.01122 |
| 2025 | Prior player TD rate (shrunk) | 6429 | 1096 | 0.1705 | 0.1812 | +0.0107 | 0.12977 | 0.41726 | 0.7112 | 0.01276 |
| 2024 | Recent six TD frequency (smoothed) | 6457 | 1105 | 0.1711 | 0.1701 | -0.0010 | 0.13011 | 0.42376 | 0.7038 | 0.02883 |
| 2025 | Recent six TD frequency (smoothed) | 6429 | 1096 | 0.1705 | 0.1754 | +0.0049 | 0.13256 | 0.42823 | 0.6955 | 0.02906 |
| 2024 | Training position/global rate | 6457 | 1105 | 0.1711 | 0.1608 | -0.0103 | 0.13895 | 0.44735 | 0.6065 | 0.01033 |
| 2025 | Training position/global rate | 6429 | 1096 | 0.1705 | 0.1661 | -0.0043 | 0.13934 | 0.45002 | 0.5865 | 0.01355 |

## 2025 retrospective test by position

| Position | Model | N | Scorers | Actual | Predicted | Bias | Brier | Log loss | AUC |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| QB | V5 ranking score + train-only isotonic | 687 | 90 | 0.1310 | 0.1827 | +0.0517 | 0.11002 | 0.36863 | 0.7190 |
| RB | V5 ranking score + train-only isotonic | 1460 | 372 | 0.2548 | 0.1705 | -0.0843 | 0.17345 | 0.52298 | 0.7409 |
| TE | V5 ranking score + train-only isotonic | 1646 | 207 | 0.1258 | 0.1623 | +0.0366 | 0.10096 | 0.33887 | 0.7533 |
| WR | V5 ranking score + train-only isotonic | 2636 | 427 | 0.1620 | 0.1683 | +0.0064 | 0.12457 | 0.40212 | 0.7189 |
| QB | Logistic regression | 687 | 90 | 0.1310 | 0.1330 | +0.0020 | 0.10530 | 0.35648 | 0.7109 |
| RB | Logistic regression | 1460 | 372 | 0.2548 | 0.2383 | -0.0165 | 0.16677 | 0.50524 | 0.7406 |
| TE | Logistic regression | 1646 | 207 | 0.1258 | 0.1220 | -0.0038 | 0.09994 | 0.33530 | 0.7537 |
| WR | Logistic regression | 2636 | 427 | 0.1620 | 0.1620 | +0.0000 | 0.12418 | 0.39986 | 0.7258 |
| QB | Gradient boosting | 687 | 90 | 0.1310 | 0.1394 | +0.0084 | 0.10636 | 0.35839 | 0.7038 |
| RB | Gradient boosting | 1460 | 372 | 0.2548 | 0.2340 | -0.0208 | 0.16672 | 0.50230 | 0.7341 |
| TE | Gradient boosting | 1646 | 207 | 0.1258 | 0.1270 | +0.0012 | 0.09938 | 0.33423 | 0.7485 |
| WR | Gradient boosting | 2636 | 427 | 0.1620 | 0.1655 | +0.0036 | 0.12361 | 0.39861 | 0.7269 |
| QB | Opportunity logistic baseline | 687 | 90 | 0.1310 | 0.1312 | +0.0002 | 0.10565 | 0.35632 | 0.7173 |
| RB | Opportunity logistic baseline | 1460 | 372 | 0.2548 | 0.2402 | -0.0146 | 0.16492 | 0.50010 | 0.7405 |
| TE | Opportunity logistic baseline | 1646 | 207 | 0.1258 | 0.1320 | +0.0062 | 0.09938 | 0.33380 | 0.7559 |
| WR | Opportunity logistic baseline | 2636 | 427 | 0.1620 | 0.1566 | -0.0054 | 0.12416 | 0.40049 | 0.7242 |
| QB | Prior player TD rate (shrunk) | 687 | 90 | 0.1310 | 0.1485 | +0.0175 | 0.10823 | 0.36626 | 0.6758 |
| RB | Prior player TD rate (shrunk) | 1460 | 372 | 0.2548 | 0.2709 | +0.0161 | 0.17258 | 0.52183 | 0.6945 |
| TE | Prior player TD rate (shrunk) | 1646 | 207 | 0.1258 | 0.1085 | -0.0172 | 0.10336 | 0.34981 | 0.7092 |
| WR | Prior player TD rate (shrunk) | 2636 | 427 | 0.1620 | 0.1854 | +0.0235 | 0.12816 | 0.41475 | 0.6920 |
| QB | Recent six TD frequency (smoothed) | 687 | 90 | 0.1310 | 0.1430 | +0.0120 | 0.11181 | 0.37752 | 0.6573 |
| RB | Recent six TD frequency (smoothed) | 1460 | 372 | 0.2548 | 0.2572 | +0.0024 | 0.17507 | 0.53017 | 0.6837 |
| TE | Recent six TD frequency (smoothed) | 1646 | 207 | 0.1258 | 0.1149 | -0.0108 | 0.10716 | 0.36988 | 0.6629 |
| WR | Recent six TD frequency (smoothed) | 2636 | 427 | 0.1620 | 0.1763 | +0.0143 | 0.13028 | 0.42142 | 0.6736 |
| QB | Training position/global rate | 687 | 90 | 0.1310 | 0.1407 | +0.0097 | 0.11394 | 0.38869 | 0.5000 |
| RB | Training position/global rate | 1460 | 372 | 0.2548 | 0.2459 | -0.0089 | 0.18995 | 0.56775 | 0.5000 |
| TE | Training position/global rate | 1646 | 207 | 0.1258 | 0.0987 | -0.0270 | 0.11068 | 0.38206 | 0.5000 |
| WR | Training position/global rate | 2636 | 427 | 0.1620 | 0.1707 | +0.0087 | 0.13582 | 0.44322 | 0.5000 |

## 2025 weekly ranking performance

Mean actual touchdown scorers in each weekly top group; the test rows are participation-conditional.

| Model | Top 10 mean hits | Top 20 mean hits | Top 30 mean hits |
|---|---:|---:|---:|
| V5 ranking score + train-only isotonic | 4.22 | 7.67 | 12.00 |
| Logistic regression | 5.50 | 9.39 | 13.11 |
| Gradient boosting | 5.33 | 9.50 | 12.61 |
| Opportunity logistic baseline | 5.56 | 9.44 | 13.39 |
| Prior player TD rate (shrunk) | 5.17 | 9.28 | 12.11 |
| Recent six TD frequency (smoothed) | 4.72 | 8.72 | 12.50 |
| Training position/global rate | 5.50 | 9.61 | 13.33 |

Predicted minus actual above zero means overestimation; below zero means underestimation.
Top-N ranking metrics and season/week/position slices are in the machine-readable metrics file.
V5 raw td_score is a ranking score, not a probability. Legacy td_estimate is retained for reference only and is not evaluated.
