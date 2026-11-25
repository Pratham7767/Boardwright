"""Per-net, per-layer track sizes as KiCad's DRC resolves them: the net class, then the project's .kicad_dru rules
(last matching rule wins, layer clauses honoured), through KiCadRoutingTools' rules reader (py_router/design_rules.py,
which follows pcbnew/drc/drc_engine.cpp). KiCad's own Python has no rule evaluation. jetson keeps its pair sizes in
its .kicad_dru (0.125-0.19 mm by layer) and its classes fall back to Default placeholders (5 mm).

Run with KiCadRoutingTools' Python:
    python engine_rules.py <krt py_router dir> <board.kicad_pcb> <request.json> <out.json>
request: {"nets": [...], "pairs": {net: pair name}}  (pair members are sized by the pair width)
out:     {"layers": [...], "sizes": {net: {layer: [track mm, via mm, drill mm, pair gap mm or None]}}}
"""
import json
import sys


def main(argv):
    sys.path.insert(0, argv[0])
    from design_rules import DesignRules
    from kicad_parser import parse_kicad_pcb
    req = json.loads(open(argv[2], encoding="utf-8").read())
    pd = parse_kicad_pcb(argv[1])
    dr = DesignRules.from_project(pd, argv[1])
    ids = {n.name: i for i, n in pd.nets.items()}
    layers = [l for l in (pd.board_info.copper_layers or []) if l.endswith(".Cu")]
    pairs = req.get("pairs") or {}
    out = {}
    for n in req.get("nets", []):
        i = ids.get(n)
        if i is None:
            continue
        out[n] = {l: [dr.draw_size("track_width", i, layer=l, diff_pair=pairs.get(n)),
                      dr.draw_size("via_diameter", i, layer=l), dr.draw_size("hole_size", i, layer=l),
                      dr.draw_size("diff_pair_gap", i, layer=l, diff_pair=pairs.get(n)) if n in pairs else None]
                  for l in layers}
    with open(argv[3], "w", encoding="utf-8") as f:
        json.dump({"layers": layers, "sizes": out}, f)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
