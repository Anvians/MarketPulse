# Brazil state boundaries

`brazil_states.geojson` is a simplified copy of the Brazilian state boundaries
from the `click_that_hood` project (Code for America, MIT License,
<https://github.com/codeforgermany/click_that_hood>). Geometry was simplified
(tolerance 0.02 degrees) and trimmed to two properties (`sigla` = state code,
`name`) so the app can draw a choropleth without any network access.
It is used only for map drawing, never for analysis.
