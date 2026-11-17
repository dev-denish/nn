"""Build an SW Maps-ready package for the Rekalakunta micro-landscape field visit.

Input  : source/Rekalakunta_boundary.zip  (landscape polygon, EPSG:4326)
         source/Rekalakunta_all_shps.zip  (Day 1/2 plot points + routes + stay, EPSG:32644)
Output : output/  (KMZ, GeoPackage, WGS84 shapefiles, GPX, CSV, and one zip of everything)

Run    : pip install pyogrio geopandas
         python build_swmaps.py
"""
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import geopandas as gpd
import pandas as pd
import pyogrio
from shapely import force_2d

HERE = Path(__file__).resolve().parent
SRC = HERE / "source"
OUT = HERE / "output"
NAME = "Rekalakunta"


# ---------------------------------------------------------------- read + clean
def read_zip(zpath, member):
    return pyogrio.read_dataframe(f"/vsizip/{zpath}/{member}")


def clean_points(gdf, day):
    gdf = gdf.to_crs(4326)
    gdf["geometry"] = force_2d(gdf.geometry)
    seq_plot = gdf["Name"].str.split(" - ", n=1, expand=True)
    out = gpd.GeoDataFrame(geometry=gdf.geometry, crs=4326)
    out["plot_id"] = seq_plot[1].str.strip()
    out["day"] = day
    out["stop_no"] = pd.to_numeric(seq_plot[0], errors="coerce").astype("Int64")
    desc = gdf["descriptio"].fillna("")
    m = desc.str.extract(r"ETA\s+(\d{1,2}:\d{2})(\s*\(\+(\d+) day\))?")
    out["eta"] = m[0].fillna("")
    out["eta_plus_d"] = pd.to_numeric(m[2], errors="coerce").fillna(0).astype(int)
    out["routed"] = out["eta"].ne("").map({True: "Yes", False: "No"})
    out["lat"] = out.geometry.y.round(7)
    out["lon"] = out.geometry.x.round(7)
    out["status"] = "Pending"  # for field use: Pending / Visited / Not accessible
    out["remarks"] = ""
    return out


def clean_line(gdf, day):
    gdf = gdf.to_crs(4326)
    out = gpd.GeoDataFrame(geometry=force_2d(gdf.geometry), crs=4326)
    out["name"] = f"Day {day} route"
    out["day"] = day
    out["length_km"] = round(gdf.to_crs(32644).length.sum() / 1000, 2)
    return out


def build_layers():
    shps = SRC / "Rekalakunta_all_shps.zip"
    bnd = read_zip(SRC / "Rekalakunta_boundary.zip", "Rekalakunta.shp").to_crs(4326)
    bnd["geometry"] = force_2d(bnd.geometry)
    boundary = gpd.GeoDataFrame(
        {
            "landscape": bnd["Landscape"],
            "district": bnd["dstrctnam"],
            "mandal": bnd["mandalnam"],
            "area_ha": bnd["Area"].round(2),
        },
        geometry=bnd.geometry,
        crs=4326,
    )
    poly = boundary.geometry.iloc[0].buffer(0)

    layers = {"boundary": boundary}
    for d in (1, 2):
        pts = clean_points(read_zip(shps, f"Day {d} Rekalakunta points.shp"), d)
        pts["in_bound"] = pts.within(poly).map({True: "Yes", False: "No"})
        layers[f"plots_day{d}"] = pts
        layers[f"route_day{d}"] = clean_line(read_zip(shps, f"Day {d} Rekalakunta route.shp"), d)

    acc = read_zip(shps, "Rekalakunta Accomodation.shp").to_crs(4326)
    layers["accommodation"] = gpd.GeoDataFrame(
        {"name": ["Accommodation"], "note": acc["descriptio"].fillna("").tolist()},
        geometry=force_2d(acc.geometry),
        crs=4326,
    )
    # stable column order for points
    cols = ["plot_id", "day", "stop_no", "eta", "eta_plus_d", "routed", "in_bound",
            "lat", "lon", "status", "remarks", "geometry"]
    for d in (1, 2):
        layers[f"plots_day{d}"] = layers[f"plots_day{d}"][cols]
    return layers


# ---------------------------------------------------------------- writers
def write_gpkg(layers, path):
    path.unlink(missing_ok=True)
    for lname, gdf in layers.items():
        pyogrio.write_dataframe(gdf, path, layer=lname, driver="GPKG", append=path.exists())


def write_shapefiles(layers, folder):
    folder.mkdir(parents=True, exist_ok=True)
    for lname, gdf in layers.items():
        pyogrio.write_dataframe(gdf, folder / f"{NAME}_{lname}.shp", driver="ESRI Shapefile",
                                encoding="UTF-8")


def write_csv(layers, path):
    df = pd.concat([layers["plots_day1"], layers["plots_day2"]]).drop(columns="geometry")
    df.to_csv(path, index=False)


def write_gpx(layers, path):
    def wpt(lat, lon, name, desc, sym="Flag, Blue"):
        return (f'  <wpt lat="{lat:.7f}" lon="{lon:.7f}"><name>{escape(name)}</name>'
                f"<desc>{escape(desc)}</desc><sym>{sym}</sym></wpt>\n")

    parts = ['<?xml version="1.0" encoding="UTF-8"?>\n',
             '<gpx version="1.1" creator="build_swmaps.py" xmlns="http://www.topografix.com/GPX/1/1">\n']
    a = layers["accommodation"].geometry.iloc[0]
    parts.append(wpt(a.y, a.x, "Accommodation", "Start / end of the day", "Lodging"))
    for d in (1, 2):
        for r in layers[f"plots_day{d}"].itertuples():
            desc = f"Day {d} stop {r.stop_no if pd.notna(r.stop_no) else 'NA'} ETA {r.eta or 'not routed'}"
            parts.append(wpt(r.lat, r.lon, r.plot_id, desc))
    for d in (1, 2):
        parts.append(f"  <trk><name>Day {d} route</name><trkseg>\n")
        for geom in layers[f"route_day{d}"].geometry:
            for x, y in geom.coords:
                parts.append(f'    <trkpt lat="{y:.7f}" lon="{x:.7f}"/>\n')
        parts.append("  </trkseg></trk>\n")
    parts.append("</gpx>\n")
    path.write_text("".join(parts), encoding="utf-8")


# KML colours are aabbggrr
STYLE = {
    "day1": "ffff8c1a",     # blue
    "day2": "ff1a8cff",     # orange
    "notrouted": "ff2020e0",  # red
    "route1": "ffff8c1a",
    "route2": "ff1a8cff",
    "boundary": "ff00ffff",  # yellow
}


def kml_coords(coords):
    return " ".join(f"{x:.7f},{y:.7f}" for x, y in coords)


def write_kmz(layers, path):
    icon = "http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png"
    styles = []
    for sid, col in (("day1", STYLE["day1"]), ("day2", STYLE["day2"]), ("notrouted", STYLE["notrouted"])):
        styles.append(f'<Style id="{sid}"><IconStyle><color>{col}</color><scale>0.9</scale>'
                      f"<Icon><href>{icon}</href></Icon></IconStyle>"
                      f"<LabelStyle><scale>0.7</scale></LabelStyle></Style>")
    styles.append('<Style id="stay"><IconStyle><scale>1.3</scale><Icon>'
                  "<href>http://maps.google.com/mapfiles/kml/shapes/lodging.png</href></Icon></IconStyle></Style>")
    for d in (1, 2):
        styles.append(f'<Style id="route{d}"><LineStyle><color>{STYLE[f"route{d}"]}</color>'
                      "<width>3</width></LineStyle></Style>")
    styles.append(f'<Style id="boundary"><LineStyle><color>{STYLE["boundary"]}</color><width>3</width>'
                  "</LineStyle><PolyStyle><color>2000ffff</color></PolyStyle></Style>")

    def ext(data):
        return "<ExtendedData>" + "".join(
            f'<Data name="{k}"><value>{escape(str(v))}</value></Data>' for k, v in data.items()
        ) + "</ExtendedData>"

    body = []
    b = layers["boundary"].iloc[0]
    rings = []
    geom = b.geometry
    polys = getattr(geom, "geoms", [geom])
    for p in polys:
        inner = "".join(f"<innerBoundaryIs><LinearRing><coordinates>{kml_coords(i.coords)}"
                        "</coordinates></LinearRing></innerBoundaryIs>" for i in p.interiors)
        rings.append(f"<Polygon><outerBoundaryIs><LinearRing><coordinates>{kml_coords(p.exterior.coords)}"
                     f"</coordinates></LinearRing></outerBoundaryIs>{inner}</Polygon>")
    body.append(f"<Folder><name>Landscape boundary</name><Placemark><name>{escape(b.landscape)}</name>"
                f"<styleUrl>#boundary</styleUrl>"
                + ext({k: b[k] for k in ("landscape", "district", "mandal", "area_ha")})
                + (f"<MultiGeometry>{''.join(rings)}</MultiGeometry>" if len(rings) > 1 else rings[0])
                + "</Placemark></Folder>")

    a = layers["accommodation"].iloc[0]
    body.append(f"<Folder><name>Accommodation</name><Placemark><name>Accommodation</name>"
                f"<description>{escape(a.note)}</description><styleUrl>#stay</styleUrl>"
                f"<Point><coordinates>{a.geometry.x:.7f},{a.geometry.y:.7f}</coordinates></Point>"
                "</Placemark></Folder>")

    for d in (1, 2):
        r = layers[f"route_day{d}"].iloc[0]
        lines = getattr(r.geometry, "geoms", [r.geometry])
        geo = "".join(f"<LineString><tessellate>1</tessellate><coordinates>{kml_coords(l.coords)}"
                      "</coordinates></LineString>" for l in lines)
        if len(lines) > 1:
            geo = f"<MultiGeometry>{geo}</MultiGeometry>"
        body.append(f"<Folder><name>Day {d} route</name><Placemark><name>Day {d} route ({r.length_km} km)</name>"
                    f"<styleUrl>#route{d}</styleUrl>{geo}</Placemark></Folder>")

        pms = []
        for p in layers[f"plots_day{d}"].sort_values("stop_no", na_position="last").itertuples():
            style = f"day{d}" if p.routed == "Yes" else "notrouted"
            eta = p.eta + (f" (+{p.eta_plus_d} day)" if p.eta_plus_d else "") if p.eta else "not routed"
            stop = p.stop_no if pd.notna(p.stop_no) else "NA"
            desc = f"Day {d} · stop {stop} · ETA {eta}" + ("" if p.in_bound == "Yes" else " · OUTSIDE boundary")
            data = {k: getattr(p, k) for k in ("plot_id", "day", "stop_no", "eta", "eta_plus_d",
                                                 "routed", "in_bound", "lat", "lon", "status")}
            pms.append(f"<Placemark><name>{escape(p.plot_id)}</name><description>{escape(desc)}</description>"
                       f"<styleUrl>#{style}</styleUrl>{ext(data)}"
                       f"<Point><coordinates>{p.lon:.7f},{p.lat:.7f}</coordinates></Point></Placemark>")
        body.append(f"<Folder><name>Day {d} plots</name>{''.join(pms)}</Folder>")

    kml = ('<?xml version="1.0" encoding="UTF-8"?>\n<kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
           f"<name>{NAME} field visit</name>{''.join(styles)}{''.join(body)}</Document></kml>\n")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("doc.kml", kml)


def zip_dir(folder, zpath, arc_prefix=""):
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(folder.rglob("*")):
            if f.is_file():
                z.write(f, arc_prefix + str(f.relative_to(folder)))


def main():
    layers = build_layers()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    write_kmz(layers, OUT / f"{NAME}_SWMaps.kmz")
    write_gpkg(layers, OUT / f"{NAME}_SWMaps.gpkg")
    write_gpx(layers, OUT / f"{NAME}_plots_routes.gpx")
    write_csv(layers, OUT / f"{NAME}_plot_list.csv")
    with tempfile.TemporaryDirectory() as td:
        write_shapefiles(layers, Path(td))
        zip_dir(Path(td), OUT / f"{NAME}_shapefiles_WGS84.zip")

    # one bundle to copy to the phone
    bundle = HERE / f"{NAME}_SWMaps_package.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.iterdir()):
            z.write(f, f"{NAME}_SWMaps/{f.name}")
        z.write(HERE / "README.md", f"{NAME}_SWMaps/README.md")

    for lname, gdf in layers.items():
        print(f"{lname:15s} {gdf.geom_type.iloc[0]:12s} {len(gdf):4d} features")
    for d in (1, 2):
        p = layers[f"plots_day{d}"]
        print(f"Day {d}: routed {int((p.routed == 'Yes').sum())}, not routed {int((p.routed == 'No').sum())}, "
              f"outside boundary {int((p.in_bound == 'No').sum())}, ETA after midnight {int((p.eta_plus_d > 0).sum())}, "
              f"last ETA {p.sort_values('stop_no').eta.replace('', pd.NA).dropna().iloc[-1]}, "
              f"route {layers[f'route_day{d}'].length_km.iloc[0]} km")


if __name__ == "__main__":
    main()
