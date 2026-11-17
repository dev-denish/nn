"""Convert the Rekalakunta field-visit shapefiles into KML.

Input  : source/Rekalakunta_boundary.zip  (landscape polygon, EPSG:4326)
         source/Rekalakunta_all_shps.zip  (Day 1/2 plot points + routes + stay, EPSG:32644)
Output : kml/Rekalakunta_all_layers.kml  (every layer, one folder each)
         kml/Rekalakunta_<layer>.kml     (one file per layer)
         Rekalakunta_KML.zip             (all of the above)

Run    : pip install pyogrio geopandas
         python build_kml.py
"""
import shutil
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import force_2d

HERE = Path(__file__).resolve().parent
SRC = HERE / "source"
OUT = HERE / "kml"
NAME = "Rekalakunta"

# KML colours are aabbggrr
BLUE, ORANGE, RED, YELLOW = "ffff8c1a", "ff1a8cff", "ff2020e0", "ff00ffff"
DOT = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
LODGING = "http://maps.google.com/mapfiles/kml/shapes/lodging.png"


# ---------------------------------------------------------------- read + clean
def read_zip(zpath, member):
    return pyogrio.read_dataframe(f"/vsizip/{zpath}/{member}")


def clean_points(gdf, day, poly):
    gdf = gdf.to_crs(4326)
    seq_plot = gdf["Name"].str.split(" - ", n=1, expand=True)
    out = gpd.GeoDataFrame(geometry=force_2d(gdf.geometry), crs=4326)
    out["plot_id"] = seq_plot[1].str.strip()
    out["day"] = day
    out["stop_no"] = pd.to_numeric(seq_plot[0], errors="coerce").astype("Int64")
    m = gdf["descriptio"].fillna("").str.extract(r"ETA\s+(\d{1,2}:\d{2})(\s*\(\+(\d+) day\))?")
    out["eta"] = m[0].fillna("")
    out["eta_plus_d"] = pd.to_numeric(m[2], errors="coerce").fillna(0).astype(int)
    out["routed"] = out["eta"].ne("").map({True: "Yes", False: "No"})
    out["in_bound"] = out.within(poly).map({True: "Yes", False: "No"})
    out["lat"] = out.geometry.y.round(7)
    out["lon"] = out.geometry.x.round(7)
    return out.sort_values("stop_no", na_position="last")


def build_layers():
    shps = SRC / "Rekalakunta_all_shps.zip"
    bnd = read_zip(SRC / "Rekalakunta_boundary.zip", "Rekalakunta.shp").to_crs(4326)
    boundary = gpd.GeoDataFrame(
        {"landscape": bnd["Landscape"], "district": bnd["dstrctnam"],
         "mandal": bnd["mandalnam"], "area_ha": bnd["Area"].round(2)},
        geometry=force_2d(bnd.geometry), crs=4326)
    poly = boundary.geometry.iloc[0].buffer(0)

    layers = {"boundary": boundary}
    for d in (1, 2):
        layers[f"day{d}_plots"] = clean_points(read_zip(shps, f"Day {d} Rekalakunta points.shp"), d, poly)
        r = read_zip(shps, f"Day {d} Rekalakunta route.shp")
        layers[f"day{d}_route"] = gpd.GeoDataFrame(
            {"name": [f"Day {d} route"] * len(r), "day": [d] * len(r),
             "length_km": (r.to_crs(32644).length / 1000).round(2).tolist()},
            geometry=force_2d(r.to_crs(4326).geometry).tolist(), crs=4326)
    acc = read_zip(shps, "Rekalakunta Accomodation.shp").to_crs(4326)
    layers["accommodation"] = gpd.GeoDataFrame(
        {"name": ["Accommodation"], "note": acc["descriptio"].fillna("").tolist()},
        geometry=force_2d(acc.geometry), crs=4326)
    return layers


# ---------------------------------------------------------------- KML pieces
STYLES = {
    "day1": f'<Style id="day1"><IconStyle><color>{BLUE}</color><scale>0.9</scale><Icon><href>{DOT}</href>'
            "</Icon></IconStyle><LabelStyle><scale>0.7</scale></LabelStyle></Style>",
    "day2": f'<Style id="day2"><IconStyle><color>{ORANGE}</color><scale>0.9</scale><Icon><href>{DOT}</href>'
            "</Icon></IconStyle><LabelStyle><scale>0.7</scale></LabelStyle></Style>",
    "notrouted": f'<Style id="notrouted"><IconStyle><color>{RED}</color><scale>1.1</scale><Icon><href>{DOT}'
                 "</href></Icon></IconStyle><LabelStyle><scale>0.8</scale></LabelStyle></Style>",
    "stay": f'<Style id="stay"><IconStyle><scale>1.3</scale><Icon><href>{LODGING}</href></Icon></IconStyle></Style>',
    "route1": f'<Style id="route1"><LineStyle><color>{BLUE}</color><width>3</width></LineStyle></Style>',
    "route2": f'<Style id="route2"><LineStyle><color>{ORANGE}</color><width>3</width></LineStyle></Style>',
    "boundary": f'<Style id="boundary"><LineStyle><color>{YELLOW}</color><width>3</width></LineStyle>'
                "<PolyStyle><color>2000ffff</color></PolyStyle></Style>",
}


def coords(seq):
    return " ".join(f"{x:.7f},{y:.7f}" for x, y in seq)


def ext(data):
    return "<ExtendedData>" + "".join(
        f'<Data name="{k}"><value>{escape(str(v))}</value></Data>' for k, v in data.items()) + "</ExtendedData>"


def geom_kml(g):
    parts = list(getattr(g, "geoms", [g]))
    out = []
    for p in parts:
        if p.geom_type == "Point":
            out.append(f"<Point><coordinates>{p.x:.7f},{p.y:.7f}</coordinates></Point>")
        elif p.geom_type == "LineString":
            out.append(f"<LineString><tessellate>1</tessellate><coordinates>{coords(p.coords)}"
                       "</coordinates></LineString>")
        elif p.geom_type == "Polygon":
            inner = "".join(f"<innerBoundaryIs><LinearRing><coordinates>{coords(i.coords)}</coordinates>"
                            "</LinearRing></innerBoundaryIs>" for i in p.interiors)
            out.append(f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{coords(p.exterior.coords)}"
                       f"</coordinates></LinearRing></outerBoundaryIs>{inner}</Polygon>")
    return out[0] if len(out) == 1 else f"<MultiGeometry>{''.join(out)}</MultiGeometry>"


def placemark(name, style, geom, desc="", data=None):
    return (f"<Placemark><name>{escape(str(name))}</name>"
            + (f"<description>{escape(desc)}</description>" if desc else "")
            + f"<styleUrl>#{style}</styleUrl>" + (ext(data) if data else "") + geom_kml(geom) + "</Placemark>")


def folder(lname, gdf):
    """Return (folder title, style ids used, placemark xml) for one layer."""
    if lname == "boundary":
        b = gdf.iloc[0]
        data = {k: b[k] for k in ("landscape", "district", "mandal", "area_ha")}
        desc = f"{b.landscape} · {b.mandal}, {b.district} · {b.area_ha:,.2f} ha"
        return "Landscape boundary", ["boundary"], placemark(b.landscape, "boundary", b.geometry, desc, data)
    if lname == "accommodation":
        a = gdf.iloc[0]
        return "Accommodation", ["stay"], placemark("Accommodation", "stay", a.geometry, a.note)
    if lname.endswith("_route"):
        r = gdf.iloc[0]
        d = int(r.day)
        return (f"Day {d} route", [f"route{d}"],
                placemark(f"Day {d} route ({r.length_km} km)", f"route{d}", r.geometry,
                          f"{r.length_km} km", {"day": d, "length_km": r.length_km}))
    d = int(gdf.day.iloc[0])
    pms = []
    for p in gdf.itertuples():
        eta = (p.eta + (f" (+{p.eta_plus_d} day)" if p.eta_plus_d else "")) if p.eta else "not routed"
        stop = p.stop_no if pd.notna(p.stop_no) else "NA"
        desc = f"Day {d} · stop {stop} · ETA {eta}" + ("" if p.in_bound == "Yes" else " · OUTSIDE boundary")
        data = {k: ("" if pd.isna(getattr(p, k)) else getattr(p, k))
                for k in ("plot_id", "day", "stop_no", "eta", "eta_plus_d", "routed", "in_bound", "lat", "lon")}
        pms.append(placemark(p.plot_id, f"day{d}" if p.routed == "Yes" else "notrouted", p.geometry, desc, data))
    return f"Day {d} plots", [f"day{d}", "notrouted"], "".join(pms)


def kml_doc(title, parts):
    style_ids = dict.fromkeys(s for _, ids, _ in parts for s in ids)
    body = "".join(f"<Folder><name>{escape(t)}</name>{x}</Folder>" for t, _, x in parts)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
            f"<name>{escape(title)}</name>{''.join(STYLES[s] for s in style_ids)}{body}</Document></kml>\n")


def main():
    layers = build_layers()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    order = ["boundary", "accommodation", "day1_route", "day1_plots", "day2_route", "day2_plots"]
    parts = {k: folder(k, layers[k]) for k in order}
    (OUT / f"{NAME}_all_layers.kml").write_text(
        kml_doc(f"{NAME} field visit", [parts[k] for k in order]), encoding="utf-8")
    for k in order:
        (OUT / f"{NAME}_{k}.kml").write_text(kml_doc(f"{NAME} – {parts[k][0]}", [parts[k]]), encoding="utf-8")

    with zipfile.ZipFile(HERE / f"{NAME}_KML.zip", "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.iterdir()):
            z.write(f, f"{NAME}_KML/{f.name}")

    for k in order:
        print(f"{k:14s} {layers[k].geom_type.iloc[0]:16s} {len(layers[k]):4d} features")


if __name__ == "__main__":
    main()
