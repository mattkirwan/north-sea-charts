# Surf reports

Conditions reported from the app's Predictions tab (beta): one JSON file per
report in `reports/`, named by when it was reported. Each holds what was seen
(spot, size, quality, surface, notes) and a snapshot of what the app knew at
that moment (nearest buoys, wind, tide, storm alerts, model run) with its own
size estimate, so predictions can be checked against what really happened.

Written by the app with the owner's GitHub token; nothing else writes here.
