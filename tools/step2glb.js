// STEP → GLB for Officina's viewer (OpenCascade via occt-import-js). One node per solid, name in node.name.
// Usage: node step2glb.js <in.stp> <out.glb>      Units: mm Z-up → m Y-up.
const fs = require("fs"), occtimportjs = require("occt-import-js");
const [src, dst] = process.argv.slice(2);
occtimportjs().then(occt => {
  const res = occt.ReadStepFile(new Uint8Array(fs.readFileSync(src)), { linearUnit: "meter", linearDeflectionType: "bounding_box_ratio", linearDeflection: 0.001, angularDeflection: 0.5 });
  if (!res.success) { console.error("could not read step"); process.exit(1); }
  const chunks = [], views = [], accs = [], meshes = [], nodes = [], mats = [], matIdx = {};
  let off = 0;
  const add = (typed, target, type, ctype, mm) => {
    const b = Buffer.from(typed.buffer, typed.byteOffset, typed.byteLength); chunks.push(b);
    const pad = (4 - (b.length % 4)) % 4; if (pad) chunks.push(Buffer.alloc(pad));
    views.push({ buffer: 0, byteOffset: off, byteLength: b.length, target }); off += b.length + pad;
    const a = { bufferView: views.length - 1, componentType: ctype, count: typed.length / (type === "VEC3" ? 3 : 1), type };
    if (mm) Object.assign(a, mm); accs.push(a); return accs.length - 1;
  };
  const mat = c => {
    const k = c.map(v => v.toFixed(3)).join();
    if (!(k in matIdx)) { mats.push({ pbrMetallicRoughness: { baseColorFactor: [...c, 1], metallicFactor: 0, roughnessFactor: 0.85 }, doubleSided: true }); matIdx[k] = mats.length - 1; }
    return matIdx[k];
  };
  res.meshes.forEach((m, i) => {
    const p = m.attributes.position.array, pos = new Float32Array(p.length);
    for (let j = 0; j < p.length; j += 3) { pos[j] = p[j]; pos[j + 1] = p[j + 2]; pos[j + 2] = -p[j + 1]; }   // Z-up → Y-up
    const min = [Infinity, Infinity, Infinity], max = [-Infinity, -Infinity, -Infinity];
    for (let j = 0; j < pos.length; j++) { const a = j % 3; if (pos[j] < min[a]) min[a] = pos[j]; if (pos[j] > max[a]) max[a] = pos[j]; }
    const pa = add(pos, 34962, "VEC3", 5126, { min, max });
    const ia = add(Uint32Array.from(m.index.array), 34963, "SCALAR", 5125);
    meshes.push({ primitives: [{ attributes: { POSITION: pa }, indices: ia, material: mat(m.color || [0.85, 0.75, 0.58]) }] });
    nodes.push({ mesh: meshes.length - 1, name: m.name || `solid ${i + 1}`, extras: { cls: "STEP solid", tag: "", type: "", guid: "" } });
  });
  const bin = Buffer.concat(chunks);
  const gltf = { asset: { version: "2.0", generator: "Officina step2glb" }, scene: 0, scenes: [{ nodes: nodes.map((_, i) => i) }], nodes, meshes,
                 materials: mats, accessors: accs, bufferViews: views, buffers: [{ byteLength: bin.length }] };
  let js = Buffer.from(JSON.stringify(gltf)); const jp = (4 - (js.length % 4)) % 4; if (jp) js = Buffer.concat([js, Buffer.alloc(jp, 0x20)]);
  const head = Buffer.alloc(12); head.writeUInt32LE(0x46546C67, 0); head.writeUInt32LE(2, 4); head.writeUInt32LE(12 + 8 + js.length + 8 + bin.length, 8);
  const jh = Buffer.alloc(8); jh.writeUInt32LE(js.length, 0); jh.writeUInt32LE(0x4E4F534A, 4);
  const bh = Buffer.alloc(8); bh.writeUInt32LE(bin.length, 0); bh.writeUInt32LE(0x004E4942, 4);
  fs.writeFileSync(dst, Buffer.concat([head, jh, js, bh, bin]));
  console.log(`${nodes.length} solids → ${dst} (${Math.round(bin.length / 1024)} KB)`);
});
