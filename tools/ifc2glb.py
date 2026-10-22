"""IFC → GLB for Officina's viewer. One node per IFC element (name, tag, class, guid in extras), colours from IFC styles.

Usage:  venv/bin/python ifc2glb.py <file.ifc> <out.glb>
Axes: IFC Z-up → glTF Y-up. Units: metres (IfcOpenShell world coords).
"""
import sys, json, struct, multiprocessing, collections
import numpy as np
import ifcopenshell, ifcopenshell.geom

src, dst = sys.argv[1], sys.argv[2]
f = ifcopenshell.open(src)
s = ifcopenshell.geom.settings(); s.set("use-world-coords", True)
it = ifcopenshell.geom.iterator(s, f, multiprocessing.cpu_count(),
                                exclude=f.by_type("IfcOpeningElement") + f.by_type("IfcSpace"))

PAL = [(0.71, 0.40, 0.23), (0.31, 0.47, 0.59), (0.42, 0.49, 0.25), (0.69, 0.29, 0.25), (0.66, 0.48, 0.18),
       (0.49, 0.41, 0.64), (0.31, 0.54, 0.52), (0.55, 0.52, 0.47)]
cls_col = {}
bin_ = bytearray(); views, accs, meshes, nodes, mats, matidx = [], [], [], [], [], {}


def add(arr, target, comp, ctype, minmax=False):
    off = len(bin_); b = arr.tobytes(); bin_.extend(b)
    while len(bin_) % 4: bin_.append(0)
    views.append({"buffer": 0, "byteOffset": off, "byteLength": len(b), "target": target})
    a = {"bufferView": len(views) - 1, "componentType": ctype, "count": len(arr), "type": comp}
    if minmax:
        a["min"] = arr.min(0).tolist(); a["max"] = arr.max(0).tolist()
    accs.append(a); return len(accs) - 1


def material(rgb, alpha):
    k = (round(rgb[0], 3), round(rgb[1], 3), round(rgb[2], 3), round(alpha, 2))
    if k not in matidx:
        m = {"pbrMetallicRoughness": {"baseColorFactor": [*k[:3], k[3]], "metallicFactor": 0.0, "roughnessFactor": 0.85}, "doubleSided": True}
        if k[3] < 0.99:
            m["alphaMode"] = "BLEND"
        mats.append(m); matidx[k] = len(mats) - 1
    return matidx[k]


counts = collections.Counter()
if it.initialize():
    while True:
        sh = it.get(); el = f.by_id(sh.id); g = sh.geometry
        v = np.array(g.verts, dtype=np.float32).reshape(-1, 3)
        fa = np.array(g.faces, dtype=np.uint32).reshape(-1, 3)
        if len(v) and len(fa):
            v = v[:, [0, 2, 1]] * np.array([1, 1, -1], dtype=np.float32)      # Z-up → Y-up
            mids = np.array(g.material_ids, dtype=np.int64) if len(g.material_ids) else np.full(len(fa), -1)
            prims = []
            pos = add(v, 34962, "VEC3", 5126, True)
            for mid in np.unique(mids):
                tri = fa[mids == mid]
                rgb, alpha = None, 1.0
                if mid >= 0 and mid < len(g.materials):
                    m = g.materials[mid]
                    try:
                        d = m.diffuse; rgb = (d.r(), d.g(), d.b()); t = m.transparency
                        alpha = 1.0 - t if t == t and t is not None and 0 <= t <= 1 else 1.0
                    except Exception:
                        rgb = None
                if rgb is None:
                    c = el.is_a(); cls_col.setdefault(c, PAL[len(cls_col) % len(PAL)]); rgb = cls_col[c]
                prims.append({"attributes": {"POSITION": pos}, "indices": add(tri.reshape(-1), 34963, "SCALAR", 5125), "material": material(rgb, alpha)})
            meshes.append({"primitives": prims})
            nodes.append({"mesh": len(meshes) - 1, "name": el.Name or el.is_a(),
                          "extras": {"cls": el.is_a(), "tag": getattr(el, "Tag", None) or "", "guid": el.GlobalId,
                                     "type": getattr(el, "ObjectType", None) or ""}})
            counts[el.is_a()] += 1
        if not it.next():
            break

gltf = {"asset": {"version": "2.0", "generator": "Officina ifc2glb"}, "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}], "nodes": nodes, "meshes": meshes, "materials": mats,
        "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(bin_)}],
        "extras": {"source": src, "schema": f.schema, "counts": dict(counts)}}
js = json.dumps(gltf, separators=(",", ":")).encode()
while len(js) % 4: js += b" "
with open(dst, "wb") as o:
    o.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(bin_)))
    o.write(struct.pack("<II", len(js), 0x4E4F534A)); o.write(js)
    o.write(struct.pack("<II", len(bin_), 0x004E4942)); o.write(bin_)
print(f"{len(nodes)} elements → {dst} ({len(bin_) // 1024} KB)")
