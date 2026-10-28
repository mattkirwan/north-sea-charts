Exact versions for the Python jobs, so a new release upstream can't break
every run at once: `frames.txt` (frames.yml), `charts.txt` (charts.yml) and
`forecast.txt` (forecast.yml). Pinned to what the jobs were running on
27 Oct 2026. To move them on, regenerate one and run its job by hand:

    uv pip compile --python-version 3.12 - -o requirements/frames.txt <<< $'cfgrib\neccodes\nxarray\nscipy\npyshp\nshapely'
    uv pip compile --python-version 3.12 - -o requirements/charts.txt <<< $'cfgrib\neccodes\nxarray\nmatplotlib\ncartopy\nscipy'
    uv pip compile --python-version 3.12 - -o requirements/forecast.txt <<< $'numpy\nscipy\nshapely\npyshp'
