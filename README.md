# History

The record our swell predictions are judged against, kept by the chart job
(scripts/history.py) after each new GFS run. This branch only ever grows.

- `forecasts/<run>.json`: every run's swell forecast for Saltburn, as made.
- `buoys/<code>.json`: every reading from the coastal buoys, merged run
  after run.
- `held.json`: each swell held as first predicted, never changed; every later
  run's view of the same swell; and, once it has passed, the biggest Whitby
  reading over its time. The app's Predictions tab (beta) lays the condition
  reports from the `reports` branch over them.
