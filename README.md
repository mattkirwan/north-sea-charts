# History

The record our swell forecast is judged against, kept by the chart job
(scripts/history.py) after each new GFS run. This branch only ever grows.

Every run forecasts every hour of the next 8 days, so each hour ends up with
about 32 predictions, made from 8 days ahead down to the hour itself.

- `forecasts/<run>.json`: every run's swell forecast for Saltburn, as made.
- `days/<date>.json`: every prediction made for each hour of that day (UTC),
  from every run: rows of [hour, run, ft, m, s, from].
- `buoys/<code>.json`: every reading from the coastal buoys, merged run
  after run.
- `verify.json`: the last 30 days' predictions against the Whitby buoy, by
  how many days ahead they were made.

The app's Predictions tab (beta) lays the condition reports from the
`reports` branch over them.
