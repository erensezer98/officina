"""Rhino .3dm -> GLB for Officina's viewer (run with the Officina venv python: rhino3dm + mapbox_earcut + numpy).

One glTF node per Rhino object. extras: name, cls (= layer full path, used as the class toggle), layer, type, guid, user (user text).
Colour: object colour if set, else layer colour. Units -> metres, Rhino Z-up -> glTF Y-up.
Breps / Extrusions: use the cached render mesh when the file has it; else tessellate here
(planar faces: trim loops -> earcut; curved faces: loops inverted to surface uv -> earcut -> adaptive split).
Blocks (instance references) are expanded with their transform.
usage: 3dm2glb.py in.3dm out.glb
"""
import sys, json, struct, math
import numpy as np
import rhino3dm as r
import mapbox_earcut as earcut

UNIT_M = {"Millimeters": 0.001, "Centimeters": 0.01, "Meters": 1.0, "Inches": 0.0254, "Feet": 0.3048, "None": 0.001}


def mesh_arrays(m):
    """rhino3dm Mesh -> (V Nx3, F Mx3)."""
    n = len(m.Vertices)
    V = np.array([[p.X, p.Y, p.Z] for p in (m.Vertices[i] for i in range(n))], dtype=np.float64) if n else np.zeros((0, 3))
    F = []
    for i in range(len(m.Faces)):
        f = m.Faces[i]
        if len(f) == 4 and f[2] != f[3]:
            F += [(f[0], f[1], f[2]), (f[0], f[2], f[3])]
        else:
            F.append((f[0], f[1], f[2]))
    return V, np.array(F, dtype=np.int64).reshape(-1, 3)


def sample_curve(c, n_min=2):
    d = c.Domain; t0, t1 = d.T0, d.T1
    if c.IsLinear():
        n = 1
    else:
        ln = 0.0; prev = c.PointAt(t0)
        for k in range(1, 9):
            p = c.PointAt(t0 + (t1 - t0) * k / 8); ln += prev.DistanceTo(p); prev = p
        n = max(8, min(64, int(ln / 3.0)))            # ~3 model units per segment (mm), 8..64
        if c.IsArc() or c.IsCircle():
            n = max(n, 24)
    return [c.PointAt(t0 + (t1 - t0) * k / n) for k in range(n + 1)]


def loop_points(brep, loop):
    pts = []
    for ti in range(loop.TrimCount):
        tr = loop.Trims[ti]
        if tr.EdgeIndex < 0:
            continue                                   # singular trim (pole)
        e = brep.Edges[tr.EdgeIndex]
        ps = sample_curve(e)
        if tr.IsReversed:
            ps = ps[::-1]
        pts += ps[1:] if pts else ps
    if len(pts) > 1 and pts[0].DistanceTo(pts[-1]) < 1e-9:
        pts = pts[:-1]
    return [(p.X, p.Y, p.Z) for p in pts]


def newell(P):
    n = np.zeros(3)
    for i in range(len(P)):
        a, b = P[i], P[(i + 1) % len(P)]
        n += [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]
    L = np.linalg.norm(n)
    return n / L if L > 1e-12 else None


def tri_2d(rings2d):
    verts = np.concatenate(rings2d).astype(np.float64)
    ends = np.cumsum([len(x) for x in rings2d]).astype(np.uint32)
    idx = earcut.triangulate_float64(verts, ends)
    return np.asarray(idx, dtype=np.int64).reshape(-1, 3)


def planar_face(rings3d):
    P = np.array(rings3d[0]); n = newell(rings3d[0])
    if n is None:
        return None
    u = np.cross(n, [0, 0, 1] if abs(n[2]) < 0.9 else [1, 0, 0]); u /= np.linalg.norm(u); v = np.cross(n, u)
    o = P[0]
    rings2d = [np.stack([(np.array(R) - o) @ u, (np.array(R) - o) @ v], 1) for R in rings3d]
    F = tri_2d(rings2d)
    V = np.concatenate([np.array(R) for R in rings3d])
    return V, F, np.tile(n, (len(V), 1))


class SrfInv:
    """3D point -> (u,v) on a surface: coarse grid seed + Newton (finite differences)."""
    def __init__(self, s):
        self.s = s; du, dv = s.Domain(0), s.Domain(1)
        self.u0, self.u1, self.v0, self.v1 = du.T0, du.T1, dv.T0, dv.T1
        def seeds(d, a, b):                              # 8 samples per knot span (creases + curvature sit on spans)
            k = sorted(set(list(s.GetSpanVector(d)) or [a, b]))
            out = [a] if not k else []
            for x0, x1 in zip(k, k[1:]):
                out += [x0 + (x1 - x0) * j / 8 for j in range(8)]
            out.append(b); return np.array(sorted(set(out)))
        self.gu = seeds(0, self.u0, self.u1); self.gv = seeds(1, self.v0, self.v1)
        if len(self.gu) * len(self.gv) > 20000:
            self.gu = np.linspace(self.u0, self.u1, 101); self.gv = np.linspace(self.v0, self.v1, 101)
        self.grid = np.array([[self.P(u, v) for v in self.gv] for u in self.gu])
        self.cu = s.IsClosed(0); self.cv = s.IsClosed(1)

    def P(self, u, v):
        p = self.s.PointAt(u, v); return (p.X, p.Y, p.Z)

    def inv(self, q):
        q = np.array(q); d = ((self.grid - q) ** 2).sum(2); i, j = np.unravel_index(np.argmin(d), d.shape)
        u, v = self.gu[i], self.gv[j]; hu = (self.u1 - self.u0) * 1e-5; hv = (self.v1 - self.v0) * 1e-5
        cl = lambda u, v: (min(self.u1, max(self.u0, u)), min(self.v1, max(self.v0, v)))
        p = np.array(self.P(u, v)); err = np.linalg.norm(q - p)
        for _ in range(12):                             # Newton; forward and backward differences (kinks at knots), keep the better step
            best = None
            for su, sv in ((1, 1), (-1, -1), (1, -1), (-1, 1)):
                pu = (np.array(self.P(u + su * hu, v)) - p) / (su * hu); pv = (np.array(self.P(u, v + sv * hv)) - p) / (sv * hv)
                try:
                    st = np.linalg.lstsq(np.stack([pu, pv], 1), q - p, rcond=None)[0]
                except Exception:
                    continue
                un, vn = cl(u + st[0], v + st[1]); pn = np.array(self.P(un, vn)); en = np.linalg.norm(q - pn)
                if best is None or en < best[0]:
                    best = (en, un, vn, pn)
            if best is None or best[0] >= err - 1e-9:
                break
            err, u, v, p = best
            if err < 1e-6:
                break
        if np.linalg.norm(np.array(self.P(u, v)) - q) > math.sqrt(d[i, j]):   # Newton went astray: keep the grid seed
            u, v = self.gu[i], self.gv[j]
        return u, v


def curved_face(face, rings3d, tol):
    s = face.UnderlyingSurface(); inv = SrfInv(s)
    pu, pv = inv.u1 - inv.u0, inv.v1 - inv.v0
    rings = []
    raw0 = np.array([inv.inv(q) for q in rings3d[0]])
    full = (inv.cu and inv.cv and np.ptp(raw0[:, 0]) >= 0.97 * pu and np.ptp(raw0[:, 1]) >= 0.97 * pv)
    for ri, R in enumerate(rings3d):
        if ri == 0 and full:                       # torus-like face (e.g. revolved closed profile): outer loop = whole domain
            rings.append(np.array([(inv.u0, inv.v0), (inv.u1, inv.v0), (inv.u1, inv.v1), (inv.u0, inv.v1)])); continue
        uv = raw0.tolist() if ri == 0 else [inv.inv(q) for q in R]
        out = [uv[0]]
        for (u, v) in uv[1:]:                     # unwrap periodic directions along the loop
            pu_, pv_ = out[-1]
            if inv.cu:
                u = min((u, u - pu, u + pu), key=lambda x: abs(x - pu_))
            if inv.cv:
                v = min((v, v - pv, v + pv), key=lambda x: abs(x - pv_))
            out.append((u, v))
        out = np.array(out)
        if rings:                                  # inner loop: shift by whole periods into the outer loop's range
            O = rings[0]
            if inv.cu:
                out[:, 0] += pu * round((O[:, 0].mean() - out[:, 0].mean()) / pu) if (out[:, 0].mean() < O[:, 0].min() or out[:, 0].mean() > O[:, 0].max()) else 0
            if inv.cv:
                out[:, 1] += pv * round((O[:, 1].mean() - out[:, 1].mean()) / pv) if (out[:, 1].mean() < O[:, 1].min() or out[:, 1].mean() > O[:, 1].max()) else 0
        rings.append(out)
    # grid on the surface knot spans (creases sit on knots), refined per span until the chord error is below tol,
    # each grid cell clipped to the trimmed region (shapely) and triangulated -> boundaries follow the trims exactly.
    from shapely.geometry import Polygon, box as sbox
    from shapely.validation import make_valid

    def wrapP(u, v):
        if inv.cu and not (inv.u0 <= u <= inv.u1): u = inv.u0 + (u - inv.u0) % pu
        if inv.cv and not (inv.v0 <= v <= inv.v1): v = inv.v0 + (v - inv.v0) % pv
        return min(inv.u1, max(inv.u0, u)), min(inv.v1, max(inv.v0, v))

    def P(u, v):
        uu, vv = wrapP(u, v); p = s.PointAt(uu, vv); return np.array((p.X, p.Y, p.Z))
    allp = np.concatenate(rings); lo, hi = allp.min(0), allp.max(0)

    def lines(d, a, b, per, closed):
        k = list(s.GetSpanVector(d)) or [inv.u0 if d == 0 else inv.v0, inv.u1 if d == 0 else inv.v1]
        ks = set()
        shifts = range(int(math.floor((a - k[0]) / per)) - 1, int(math.ceil((b - k[-1]) / per)) + 2) if closed and per > 0 else [0]
        for m_ in shifts:
            ks.update(x + m_ * per for x in k)
        ks = sorted(x for x in ks if a - 1e-12 <= x <= b + 1e-12); ks = sorted(set([a] + ks + [b]))
        out = [ks[0]]
        for x0, x1 in zip(ks, ks[1:]):
            if x1 - x0 < 1e-12: continue
            n = 1
            while n < 48:                              # refine this span until midpoints are within tol
                ok = True
                for j in range(n):
                    t0, t1 = x0 + (x1 - x0) * j / n, x0 + (x1 - x0) * (j + 1) / n; tm = (t0 + t1) / 2
                    for w in (0.0, 0.5, 1.0):
                        o = (lo[1 - d] + (hi[1 - d] - lo[1 - d]) * w)
                        A, B_, M_ = (P(t0, o), P(t1, o), P(tm, o)) if d == 0 else (P(o, t0), P(o, t1), P(o, tm))
                        if np.linalg.norm(M_ - (A + B_) / 2) > tol: ok = False; break
                    if not ok: break
                if ok: break
                n *= 2
            out += [x0 + (x1 - x0) * j / n for j in range(1, n + 1)]
        return out
    us = lines(0, lo[0], hi[0], pu, inv.cu); vs = lines(1, lo[1], hi[1], pv, inv.cv)
    region = Polygon(rings[0], [r_ for r_ in rings[1:]])
    if not region.is_valid:
        region = make_valid(region)
    Vs, Fs, Ns = [], [], []
    for a, b in zip(us, us[1:]):
        for c, d in zip(vs, vs[1:]):
            cell = sbox(a, c, b, d)
            g = region.intersection(cell) if not region.contains(cell) else cell
            if g.is_empty: continue
            polys = [g] if g.geom_type == "Polygon" else [x for x in getattr(g, "geoms", []) if x.geom_type == "Polygon"]
            for pg in polys:
                if pg.area <= 0: continue
                rs = [np.array(pg.exterior.coords)[:-1]] + [np.array(h.coords)[:-1] for h in pg.interiors]
                if len(rs[0]) < 3: continue
                # metric scale for good triangles
                F = tri_2d([np.stack([R[:, 0] - a, R[:, 1] - c], 1) for R in rs])
                UV = np.concatenate(rs); base = len(Vs)
                for (u, v) in UV:
                    uu, vv = wrapP(u, v); p = s.PointAt(uu, vv); nn = s.NormalAt(uu, vv)
                    Vs.append((p.X, p.Y, p.Z)); Ns.append((nn.X, nn.Y, nn.Z))
                Fs += (F + base).tolist()
    return np.array(Vs), np.array(Fs, dtype=np.int64).reshape(-1, 3), np.array(Ns)


def brep_mesh(b, stats):
    Vs, Fs, Ns, off = [], [], [], 0
    bb = b.GetBoundingBox(); diag = bb.Min.DistanceTo(bb.Max)
    tol = max(0.05, diag * 0.0008)
    for fi in range(len(b.Faces)):
        f = b.Faces[fi]; got = None
        rm = f.GetMesh(r.MeshType.Any)
        try:
            if rm is not None:
                V, F = mesh_arrays(rm); got = (V, F, None)
            else:
                rings = [loop_points(b, f.Loops[li]) for li in range(len(f.Loops))]
                rings = [x for x in rings if len(x) >= 3]
                outer = [k for k in range(len(f.Loops)) if str(f.Loops[k].LoopType).endswith("Outer")]
                if outer and outer[0] < len(rings) and outer[0] != 0:
                    rings.insert(0, rings.pop(outer[0]))
                if not rings:
                    continue
                got = planar_face(rings) if f.IsPlanar() else curved_face(f, rings, tol)
                stats["tess"] += 1
        except Exception as e:
            stats["fail"] += 1; got = None
        if got is None or len(got[1]) == 0:
            continue
        V, F, N = got
        Vs.append(V); Fs.append(F + off); Ns.append(N if N is not None else np.full((len(V), 3), np.nan)); off += len(V)
    if not Vs:
        return None
    return np.concatenate(Vs), np.concatenate(Fs), np.concatenate(Ns)


def geom_mesh(g, stats):
    t = type(g).__name__
    if t == "Mesh":
        V, F = mesh_arrays(g); return V, F, None
    if t == "Brep":
        return brep_mesh(g, stats)
    if t == "Extrusion":
        m = g.GetMesh(r.MeshType.Any)
        if m is not None:
            V, F = mesh_arrays(m); return V, F, None
        b = g.ToBrep(True); return brep_mesh(b, stats) if b else None
    if t in ("Surface", "NurbsSurface", "PlaneSurface", "RevSurface", "SumSurface"):
        b = r.Brep.CreateFromSurface(g); return brep_mesh(b, stats) if b else None
    if t == "SubD":
        try:
            m = r.Mesh.CreateFromSubDControlNet(g); V, F = mesh_arrays(m); return V, F, None
        except Exception:
            return None
    return None


def xf_np(x):
    return np.array([[x.M00, x.M01, x.M02, x.M03], [x.M10, x.M11, x.M12, x.M13], [x.M20, x.M21, x.M22, x.M23], [x.M30, x.M31, x.M32, x.M33]])


def main(src, out):
    f = r.File3dm.Read(src)
    if f is None:
        sys.exit("cannot read")
    scale = UNIT_M.get(str(f.Settings.ModelUnitSystem).split(".")[-1], 0.001)
    layers = {f.Layers[i].Index: f.Layers[i] for i in range(len(f.Layers))}
    objs = {str(o.Attributes.Id): o for o in f.Objects}
    stats = {"tess": 0, "fail": 0, "objects": 0, "skipped": 0}
    cache = {}

    def mesh_of(o):
        k = str(o.Attributes.Id)
        if k not in cache:
            cache[k] = geom_mesh(o.Geometry, stats)
        return cache[k]

    def colour(o, parent=None):
        a = o.Attributes; src_ = str(a.ColorSource).split(".")[-1]
        if src_ == "ColorFromParent" and parent is not None:
            return colour(parent)
        if src_ == "ColorFromObject":
            c = a.ObjectColor
        else:
            L = layers.get(a.LayerIndex); c = L.Color if L else (200, 190, 170, 255)
        return tuple(int(x) for x in c[:3])

    nodes = []                                   # (name, extras, V, F, N, rgb)

    def emit(o, M, parent=None, depth=0):
        g = o.Geometry; t = type(g).__name__
        if t == "InstanceReference":
            if depth > 8:
                return
            idef = f.InstanceDefinitions.FindId(g.ParentIdefId)
            if idef is None:
                return
            M2 = M @ xf_np(g.Xform)
            for oid in idef.GetObjectIds():
                c = objs.get(str(oid))
                if c is not None:
                    emit(c, M2, parent or o, depth + 1)
            return
        res = mesh_of(o)
        if res is None:
            stats["skipped"] += 1; return
        V, F, N = res
        if len(F) == 0:
            return
        Vh = np.c_[V, np.ones(len(V))] @ M.T; V2 = Vh[:, :3]
        if N is not None:
            N2 = N @ M[:3, :3].T
        else:
            N2 = None
        top = parent or o; a = top.Attributes; L = layers.get(a.LayerIndex)
        user = dict(a.GetUserStrings() or ())
        if parent is not None:
            user.update({k: v for k, v in (o.Attributes.GetUserStrings() or ())})
        name = a.Name or (f.InstanceDefinitions.FindId(top.Geometry.ParentIdefId).Name if parent is not None else "") or user.get("part") or user.get("mark") or t
        lpath = L.FullPath if L else "Default"
        bname = f.InstanceDefinitions.FindId(top.Geometry.ParentIdefId).Name if parent is not None else ""
        ex = {"cls": lpath, "layer": lpath, "type": f"block {bname} · {t}" if parent is not None else t,
              "guid": str(a.Id), "tag": user.get("part", "") or user.get("mark", ""), "user": user, "src": "3dm"}
        if L is not None and not L.Visible:
            ex["hidden"] = True
        nodes.append((name, ex, V2, F, N2, colour(o, parent)))
        stats["objects"] += 1

    for o in f.Objects:
        a = o.Attributes
        if a.IsInstanceDefinitionObject:
            continue
        if str(a.Mode).endswith("Hidden") or not a.Visible:
            continue
        emit(o, np.eye(4))

    # ---- write GLB: Rhino Z-up mm -> glTF Y-up m ----
    R = np.array([[1, 0, 0], [0, 0, 1], [0, -1, 0]], dtype=np.float64)
    allV = np.concatenate([n[2] for n in nodes]) if nodes else np.zeros((1, 3))
    centre = np.zeros(3)
    if np.abs(allV).max() > 1e5:                 # far from origin: recentre (keep the shift in extras)
        centre = (allV.min(0) + allV.max(0)) / 2
    buf = bytearray(); views, accs, meshes, gnodes, mats, matidx = [], [], [], [], [], {}

    def add_view(b, target):
        while len(buf) % 4: buf.append(0)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": len(b), "target": target}); buf.extend(b); return len(views) - 1
    for name, ex, V, F, N, rgb in nodes:
        P = ((V - centre) * scale) @ R.T
        if N is None or np.isnan(N).any():
            # flat-ish: unweld per triangle so normals are crisp
            P = P[F.reshape(-1)]; F = np.arange(len(P)).reshape(-1, 3)
            a, b_, c = P[F[:, 0]], P[F[:, 1]], P[F[:, 2]]; n = np.cross(b_ - a, c - a); L = np.linalg.norm(n, axis=1, keepdims=True); L[L == 0] = 1
            Nn = np.repeat(n / L, 3, axis=0)
        else:
            Nn = N @ R.T; L = np.linalg.norm(Nn, axis=1, keepdims=True); L[L == 0] = 1; Nn = Nn / L
        P = P.astype(np.float32); Nn = Nn.astype(np.float32); I = F.astype(np.uint32).reshape(-1)
        if rgb not in matidx:
            matidx[rgb] = len(mats)
            mats.append({"pbrMetallicRoughness": {"baseColorFactor": [rgb[0] / 255, rgb[1] / 255, rgb[2] / 255, 1], "metallicFactor": 0, "roughnessFactor": 0.85}, "doubleSided": True})
        vp = add_view(P.tobytes(), 34962); vn = add_view(Nn.tobytes(), 34962); vi = add_view(I.tobytes(), 34963)
        accs += [{"bufferView": vp, "componentType": 5126, "count": len(P), "type": "VEC3", "min": P.min(0).tolist(), "max": P.max(0).tolist()},
                 {"bufferView": vn, "componentType": 5126, "count": len(Nn), "type": "VEC3"},
                 {"bufferView": vi, "componentType": 5125, "count": len(I), "type": "SCALAR"}]
        k = len(accs)
        meshes.append({"primitives": [{"attributes": {"POSITION": k - 3, "NORMAL": k - 2}, "indices": k - 1, "material": matidx[rgb]}]})
        gnodes.append({"name": name, "mesh": len(meshes) - 1, "extras": ex})
    while len(buf) % 4: buf.append(0)
    gltf = {"asset": {"version": "2.0", "generator": "officina 3dm2glb"}, "scene": 0,
            "scenes": [{"nodes": list(range(len(gnodes))), "extras": {"source": src, "units": "m", "from": "3dm", "unitScale": scale, "shift": centre.tolist(), "stats": stats}}],
            "nodes": gnodes, "meshes": meshes, "materials": mats or [{}], "accessors": accs, "bufferViews": views, "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gltf, separators=(",", ":")).encode()
    while len(js) % 4: js += b" "
    with open(out, "wb") as fh:
        fh.write(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf)))
        fh.write(struct.pack("<II", len(js), 0x4E4F534A)); fh.write(js)
        fh.write(struct.pack("<II", len(buf), 0x004E4942)); fh.write(bytes(buf))
    print(json.dumps(stats))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
