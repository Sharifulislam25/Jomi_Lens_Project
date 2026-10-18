"""Builds data/admin/hierarchy.csv (Division > District > Upazila) from the real BBS/OCHA boundaries
downloaded via geoBoundaries (data/admin/bd_adm*.geojson). Run once."""
from pathlib import Path
import geopandas as gpd
import pandas as pd

D = Path(__file__).resolve().parent.parent / "data" / "admin"
a1, a2, a3 = (gpd.read_file(D / f"bd_adm{i}.geojson")[["shapeName", "geometry"]] for i in (1, 2, 3))

def parent_of(child, parent, col):
    pts = child.copy(); pts["geometry"] = child.representative_point()
    j = gpd.sjoin(pts, parent.rename(columns={"shapeName": col}), how="left", predicate="within")
    j = j[~j.index.duplicated()]
    miss = j[col].isna()
    if miss.any():  # border cases: use the nearest parent
        n = gpd.sjoin_nearest(pts[miss], parent.rename(columns={"shapeName": col}), how="left")
        j.loc[miss, col] = n[~n.index.duplicated()][col]
    return j[col]

a2["division"] = parent_of(a2, a1, "division")
a3["district"] = parent_of(a3, a2[["shapeName", "geometry"]], "district")
a3 = a3.merge(a2[["shapeName", "division"]].rename(columns={"shapeName": "district"}), on="district", how="left")
b = a3.geometry.bounds
out = pd.DataFrame({"division": a3["division"], "district": a3["district"], "upazila": a3["shapeName"],
                    "lat": a3.representative_point().y.round(5), "lon": a3.representative_point().x.round(5),
                    "minlon": b.minx.round(5), "minlat": b.miny.round(5), "maxlon": b.maxx.round(5), "maxlat": b.maxy.round(5)})
out = out.sort_values(["division", "district", "upazila"])
out.to_csv(D / "hierarchy.csv", index=False)
print(len(out), "upazilas;", out.district.nunique(), "districts;", out.division.nunique(), "divisions;",
      "missing:", int(out.isna().any(axis=1).sum()))
print(out[out.upazila.isin(["Sreepur", "Savar"])].to_string(index=False))
