# Provenance

What produced the current results. Regenerated on every pipeline run — no date is recorded here on purpose, since the commit and the input checksums identify a run far more reliably than a timestamp.

## Code

- **Commit:** `4eb362b7b0a25dda1690604b74af19c813eda9f3`
- **Branch:** `claude/create-maps-86nf12`
- **Working tree clean:** False

## Environment

| Component | Version |
| --- | --- |
| python | 3.11.15 |
| platform | Linux-6.18.44-fc-v21-x86_64-with-glibc2.39 |
| geopandas | 1.1.4 |
| shapely | 2.1.2 |
| pyogrio | 0.13.0 |
| rasterio | 1.4.4 |
| pysheds | 0.5 |
| numpy | 2.4.6 |
| pandas | 3.0.5 |
| matplotlib | 3.11.1 |
| folium | 0.20.0 |
| scipy | 1.17.1 |
| contextily | 1.7.1 |
| geos | 3.13.1 |
| gdal | 3.10.3 |

## Input archives

| Archive | Bytes | SHA-256 (first 16) |
| --- | ---: | --- |
| Zone 2 Clan Land Boundaries - 14July2026.zip | 616,399 | `c6ef79c06e57f64c` |
| Zone 3 Clan Land Boundaries - 14July2026.zip | 139,335 | `5272a65475b1a149` |
| Zone 3 Savasi Clan Boundary Aug2026.zip | 14,504 | `e3fda15f0d595adb` |
| Zone 6 Clan Boundaries 16Aug2026.zip | 357,842 | `7398122a185e8da0` |
| Zone 6 Sahirut Clan Boundaries Aug2026.zip | 45,686 | `d336c88018e244c2` |
| Zone 7A Clan Boundaries 16Aug2026.zip | 195,340 | `11ac0f609db1fbc3` |
| Zone 7B Clan Boundaries 14July2026.zip | 400,152 | `b069c6a142328c67` |
| Zone 7B Clan Boundaries 16Aug2026.zip | 150,125 | `8b1cb96a2efd3c81` |
| Zone 8 Clan Land Boundaries 14July2026.zip | 280,372 | `55c2e86da6930273` |

If a figure changes between runs, compare these digests first: they say immediately whether the data moved or the code did.

## Parameters in force

| Parameter | Value |
| --- | --- |
| `clip_distance_km` | 10.0 |
| `resample_spacing_m` | 20.0 |
| `smoothing_window_points` | 3 |
| `closure_tolerance_m` | 25.0 |
| `near_closure_threshold` | 0.1 |
| `max_inferred_gap` | 0.5 |
| `metric_crs` | EPSG:32755 |
| `storage_crs` | EPSG:4326 |

## Results produced

| Measure | Value |
| --- | --- |
| surveys | 72 |
| tracks | 610 |
| clans | 49 |
| stewards | 70 |
| zones | Zone 2, Zone 3, Zone 6, Zone 7A, Zone 7B, Zone 8 |
| smoothed_km | 1139.9 |
| polygons | 37 |
| polygons_surveyed | 5 |
| area_ha_total | 33453.9 |
| area_ha_surveyed | 2542.4 |

## Data sources

**Copernicus DEM GLO-30**

- Used for: terrain, drainage and ridgelines
- Access: https://copernicus-dem-30m.s3.amazonaws.com
- Licence: Free, worldwide, non-exclusive (ESA/Copernicus)
- Cite as: European Space Agency, Sinergise (2021). Copernicus Global Digital Elevation Model. Distributed by OpenTopography. https://doi.org/10.5069/G9028PQB

**World Database on Protected Areas — Managalas Conservation Area**

- Used for: the MCA reference boundary and the 10 km clip
- Access: supplied as KML (WDPAID 555651673, WDPA_PID 555651673)
- Licence: WDPA terms of use — check before republishing the polygon
- Cite as: UNEP-WCMC and IUCN. Protected Planet: The World Database on Protected Areas (WDPA). Cambridge, UK. www.protectedplanet.net

**Clan boundary GPS surveys**

- Used for: everything else
- Access: supplied directly as zip archives per zone
- Licence: Not established — see the sensitivity note in docs/METHODS.md
- Cite as: Field surveys by clan stewards, Oro Province, Papua New Guinea, 2025–2026

## Methods to cite

- O'Callaghan, J.F. & Mark, D.M. (1984). The extraction of drainage networks from digital elevation data. Computer Vision, Graphics and Image Processing 28(3), 323–344. — D8 flow routing.
- Barnes, R., Lehman, C. & Mulla, D. (2014). Priority-flood: an optimal depression-filling and watershed-labeling algorithm. Computers & Geosciences 62, 117–127. — depression filling.
- Weiss, A. (2001). Topographic position and landforms analysis. ESRI User Conference poster. — the ridge test.
- Bartos, M. (2020). pysheds: simple and fast watershed delineation in Python. https://doi.org/10.5281/zenodo.3822494

## Background reading

Context for writing up the sacred sites; not methods used here.

- Whitmore, N., Lamaris, J., Takendu, W., Charles, D., Chuwek, T., Mohe, B., Kanau, L. & Pe-eu, S. (2016). The context and potential sustainability of traditional terrestrial periodic tambu areas: insights from Manus Island, Papua New Guinea. Pacific Conservation Biology 22(2), 151–158. https://doi.org/10.1071/PC15036 — customary closures as clan-governed conservation; how they vary between clans.
- Lamaris, J. & Whitmore, N. (2018). Forest connectivity is important for sustaining Admiralty cuscus (Spilocuscus kraemeri) in traditional terrestrial no-take areas on Manus Island, Papua New Guinea. Pacific Conservation Biology 24(1), 55–62. https://doi.org/10.1071/PC17030 — a restricted area's conservation value depends on what surrounds it, not on its own extent.
