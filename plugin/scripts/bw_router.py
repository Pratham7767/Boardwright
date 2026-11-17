"""A simple grid router for ordinary nets (imported by bw_edit.py; runs in KiCad's Python).

What it does: for each net, joins the pad groups that are not yet connected, one at a time, with an
A* search on a grid over the copper layers. It keeps each net class's track width and clearance from
every other net's copper (pads, tracks, vias), from keep-out areas and from the board edge; it turns
in 45 degree steps and never by more than 90 degrees in one place; and it may change layer with a
via when that is allowed. Copper pours are not obstacles: they are refilled after routing.

What it does not do: length matching, differential pairs, impedance, or custom rules from the
.kicad_dru file (KiCad's DRC, run after every edit, reports anything those catch). The caller refuses
mains, hazardous and fast nets before they reach this module.
"""
from __future__ import annotations

import heapq
import math

import pcbnew

MM = 1e6
DIRS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
MAX_ERR = int(0.005 * MM)


def _poly(item, layer, inflate):
    ps = pcbnew.SHAPE_POLY_SET()
    item.TransformShapeToPolygon(ps, layer, int(inflate), MAX_ERR, pcbnew.ERROR_OUTSIDE)
    return ps


class Grid:
    def __init__(self, board, layers, pitch_mm, edge_clear_mm):
        self.b = board
        self.layers = layers                           # KiCad layer ids, e.g. [F_Cu, B_Cu]
        self.p = pitch_mm * MM
        o = pcbnew.SHAPE_POLY_SET()
        board.GetBoardPolygonOutlines(o, True)
        bb = o.BBox()
        self.x0, self.y0 = bb.GetLeft(), bb.GetTop()
        self.w = int(bb.GetWidth() / self.p) + 2
        self.h = int(bb.GetHeight() / self.p) + 2
        self.outline = o
        self.edge = edge_clear_mm * MM

    def xy(self, ix, iy):
        return self.x0 + ix * self.p, self.y0 + iy * self.p

    def cell(self, x, y):
        return int(round((x - self.x0) / self.p)), int(round((y - self.y0) / self.p))

    def blank(self):
        return [bytearray(self.w * self.h) for _ in self.layers]

    def mark(self, grid, li, ps, value=1):
        """Set every cell whose centre lies inside the polygon set."""
        if ps.OutlineCount() == 0:
            return
        bb = ps.BBox()
        ix0, iy0 = self.cell(bb.GetLeft(), bb.GetTop())
        ix1, iy1 = self.cell(bb.GetRight(), bb.GetBottom())
        g = grid[li]
        for iy in range(max(0, iy0 - 1), min(self.h, iy1 + 2)):
            row = iy * self.w
            y = self.y0 + iy * self.p
            for ix in range(max(0, ix0 - 1), min(self.w, ix1 + 2)):
                if g[row + ix] != value and ps.Contains(pcbnew.VECTOR2I(int(self.x0 + ix * self.p), int(y))):
                    g[row + ix] = value

    def mark_outside(self, grid, inset):
        inner = pcbnew.SHAPE_POLY_SET(self.outline)
        inner.Inflate(-int(inset), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MAX_ERR)
        for iy in range(self.h):
            for ix in range(self.w):
                x, y = self.xy(ix, iy)
                if not inner.Contains(pcbnew.VECTOR2I(int(x), int(y))):
                    for g in grid:
                        g[iy * self.w + ix] = 1


class Router:
    def __init__(self, board, rules, layers=("F.Cu", "B.Cu"), pitch_mm=0.1, vias=True, via_cost=12.0, allowed=None):
        """rules(net) -> {"width", "clearance", "via_d", "via_drill"} in mm.
        allowed(net) -> None, or {layer id: SHAPE_POLY_SET}: the approved corridor the net must stay in
        (cells within 1 mm of the net's own pads stay open, for the fan-out)."""
        self.allowed = allowed
        self.b = board
        self.rules = rules
        self.lnames = list(layers)
        self.lids = [board.GetLayerID(n) for n in layers]
        ds = board.GetDesignSettings()
        self.grid = Grid(board, self.lids, pitch_mm, ds.m_CopperEdgeClearance / MM)
        self.vias = vias and len(self.lids) > 1
        self.via_cost = via_cost
        self.added = []                                  # new items, so the caller can report and undo

    # ----------------------------------------------------------- obstacles
    def _copper(self):
        """Every copper item with its net code: pads, tracks, vias."""
        for fp in self.b.GetFootprints():
            for pad in fp.Pads():
                yield pad, pad.GetNetCode()
        for t in self.b.GetTracks():
            yield t, t.GetNetCode()

    def _blocked(self, net, extra_mm):
        """Grid of cells a track centre (extra = width/2) or via centre (extra = via_d/2) may not use."""
        g = self.grid
        grid = g.blank()
        r = self.rules(net.GetNetname())
        code = net.GetNetCode()
        for item, ncode in self._copper():
            if ncode == code and code != 0:
                continue
            other = self.rules(item.GetNetname()) if ncode else r
            clr = max(r["clearance"], other["clearance"])
            for li, lid in enumerate(self.lids):
                if item.IsOnLayer(lid):
                    g.mark(grid, li, _poly(item, lid, (clr + extra_mm) * MM))
            if item.Type() == pcbnew.PCB_PAD_T and item.GetDrillSize().x > 0:   # a hole cuts every layer
                hole = item.GetEffectiveHoleShape()
                for li in range(len(self.lids)):
                    ps = pcbnew.SHAPE_POLY_SET()
                    hole.TransformToPolygon(ps, MAX_ERR, pcbnew.ERROR_OUTSIDE)
                    ps.Inflate(int((clr + extra_mm) * MM), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MAX_ERR)
                    g.mark(grid, li, ps)
        for z in self.b.Zones():
            if z.GetIsRuleArea() and z.GetDoNotAllowTracks():
                for li, lid in enumerate(self.lids):
                    if z.IsOnLayer(lid):
                        ps = pcbnew.SHAPE_POLY_SET(z.Outline())
                        ps.Inflate(int(extra_mm * MM), pcbnew.CORNER_STRATEGY_ROUND_ALL_CORNERS, MAX_ERR)
                        g.mark(grid, li, ps)
        g.mark_outside(grid, g.edge + extra_mm * MM)
        region = self.allowed(net.GetNetname()) if self.allowed else None
        if region is not None:
            fan = [_poly(p, lid, 1.0 * MM) for p in (q for fp in self.b.GetFootprints() for q in fp.Pads()
                                                      if q.GetNetCode() == code) for lid in self.lids if p.IsOnLayer(lid)]
            for li, lid in enumerate(self.lids):
                ps = region.get(lid)
                row = grid[li]
                for iy in range(g.h):
                    for ix in range(g.w):
                        k = iy * g.w + ix
                        if row[k]:
                            continue
                        pt = pcbnew.VECTOR2I(*map(int, g.xy(ix, iy)))
                        if (ps is None or not ps.Contains(pt)) and not any(f.Contains(pt) for f in fan):
                            row[k] = 1
        return grid

    # ----------------------------------------------------------- groups
    def _groups(self, net):
        """The net's pads, grouped by what copper already joins."""
        self.b.BuildConnectivity()
        conn = self.b.GetConnectivity()
        pads = [p for fp in self.b.GetFootprints() for p in fp.Pads() if p.GetNetCode() == net.GetNetCode()]
        seen, groups = {}, []
        for p in pads:
            u = p.m_Uuid.AsString()
            if u in seen:
                continue
            members = {u}
            for it in conn.GetConnectedItems(p):
                if it.GetClass() == "PAD":
                    members.add(it.m_Uuid.AsString())
            gid = len(groups)
            groups.append([q for q in pads if q.m_Uuid.AsString() in members])
            for m in members:
                seen[m] = gid
        # pads of one footprint with the same number are one node
        merged = []
        for grp in groups:
            keys = {(q.GetParentFootprint().GetReference(), q.GetNumber()) for q in grp}
            for m in merged:
                if keys & m[0]:
                    m[0] |= keys
                    m[1].extend(grp)
                    break
            else:
                merged.append([keys, list(grp)])
        return [m[1] for m in merged]

    def _pad_cells(self, pad):
        """{(layer index, ix, iy)} inside the pad's copper on each routing layer."""
        g = self.grid
        out = set()
        for li, lid in enumerate(self.lids):
            if not pad.IsOnLayer(lid):
                continue
            ps = _poly(pad, lid, 0)
            bb = ps.BBox()
            ix0, iy0 = g.cell(bb.GetLeft(), bb.GetTop())
            ix1, iy1 = g.cell(bb.GetRight(), bb.GetBottom())
            for iy in range(iy0, iy1 + 1):
                for ix in range(ix0, ix1 + 1):
                    x, y = g.xy(ix, iy)
                    if ps.Contains(pcbnew.VECTOR2I(int(x), int(y))):
                        out.add((li, ix, iy))
            if not out:
                ix, iy = g.cell(pad.GetPosition().x, pad.GetPosition().y)
                out.add((li, ix, iy))
        return out

    # ----------------------------------------------------------- search
    def _search(self, srcs, dsts, trk, via, max_states=1_500_000):
        g = self.grid
        W, H = g.w, g.h
        dst_set = set(dsts)
        tx = [d[1] for d in dsts]
        ty = [d[2] for d in dsts]
        cx, cy = sum(tx) / len(tx), sum(ty) / len(ty)
        spread = max(max(abs(x - cx) for x in tx), max(abs(y - cy) for y in ty))

        def h(ix, iy):
            dx, dy = abs(ix - cx), abs(iy - cy)
            return max(0.0, max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy) - spread * 1.5)

        openq, best, came = [], {}, {}
        src_cells = set(srcs)
        for (li, ix, iy) in srcs:
            s = (li, ix, iy, 8)
            best[s] = 0.0
            heapq.heappush(openq, (h(ix, iy), 0.0, s))
        n = 0
        while openq:
            f, cost, s = heapq.heappop(openq)
            if cost > best.get(s, 1e18):
                continue
            li, ix, iy, d = s
            if (li, ix, iy) in dst_set and (li, ix, iy) not in src_cells:
                path = [s]
                while path[-1] in came:
                    path.append(came[path[-1]])
                return path[::-1]
            n += 1
            if n > max_states:
                return None
            for nd, (dx, dy) in enumerate(DIRS):
                if d != 8:
                    turn = min((nd - d) % 8, (d - nd) % 8)
                    if turn > 2:                         # never sharper than a right angle
                        continue
                    tc = 0.0 if turn == 0 else (0.35 if turn == 1 else 0.8)
                else:
                    tc = 0.0
                jx, jy = ix + dx, iy + dy
                if not (0 <= jx < W and 0 <= jy < H):
                    continue
                k = jy * W + jx
                if trk[li][k] and (li, jx, jy) not in dst_set:
                    continue
                if dx and dy and (trk[li][iy * W + jx] or trk[li][jy * W + ix]) and (li, jx, jy) not in dst_set:
                    continue                             # no corner cutting past an obstacle
                ns = (li, jx, jy, nd)
                nc = cost + (1.4142 if dx and dy else 1.0) + tc
                if nc < best.get(ns, 1e18):
                    best[ns] = nc
                    came[ns] = s
                    heapq.heappush(openq, (nc + h(jx, jy), nc, ns))
            if self.vias and d != 8 and not via[0][iy * W + ix] and not via[1][iy * W + ix]:
                for lj in range(len(self.lids)):
                    if lj == li:
                        continue
                    ns = (lj, ix, iy, 8)
                    nc = cost + self.via_cost
                    if nc < best.get(ns, 1e18):
                        best[ns] = nc
                        came[ns] = s
                        heapq.heappush(openq, (nc + h(ix, iy), nc, ns))
        return None

    # ----------------------------------------------------------- output
    def _emit(self, path, net, r, pad_at):
        """Turn a cell path into straight track runs and vias on the board."""
        g = self.grid
        pts = []                                         # (layer index, x, y) in nm, corners only
        for i, (li, ix, iy, d) in enumerate(path):
            x, y = g.xy(ix, iy)
            pts.append((li, x, y, d))
        # snap the two ends to their pad centres
        for end in (0, -1):
            li, x, y, d = pts[end]
            c = pad_at.get((li, path[end][1], path[end][2]))
            if c is not None:
                pts[end] = (li, c[0], c[1], d)
        runs, cur = [], [pts[0]]
        for prev, p in zip(pts, pts[1:]):
            if p[0] != prev[0]:                         # via
                runs.append(cur)
                runs.append(("via", prev[1], prev[2]))
                cur = [p]
                continue
            cur.append(p)
        runs.append(cur)
        made = 0
        for run in runs:
            if isinstance(run, tuple):
                v = pcbnew.PCB_VIA(self.b)
                v.SetPosition(pcbnew.VECTOR2I(int(run[1]), int(run[2])))
                v.SetWidth(int(r["via_d"] * MM))
                v.SetDrill(int(r["via_drill"] * MM))
                v.SetNet(net)
                self.b.Add(v)
                self.added.append(v)
                continue
            corners = [run[0]]
            for a, b_, c in zip(run, run[1:], run[2:]):
                if (b_[1] - a[1]) * (c[2] - b_[2]) != (b_[2] - a[2]) * (c[1] - b_[1]):
                    corners.append(b_)
            if len(run) > 1:
                corners.append(run[-1])
            for a, b_ in zip(corners, corners[1:]):
                if (a[1], a[2]) == (b_[1], b_[2]):
                    continue
                t = pcbnew.PCB_TRACK(self.b)
                t.SetStart(pcbnew.VECTOR2I(int(a[1]), int(a[2])))
                t.SetEnd(pcbnew.VECTOR2I(int(b_[1]), int(b_[2])))
                t.SetWidth(int(r["width"] * MM))
                t.SetLayer(self.lids[a[0]])
                t.SetNet(net)
                self.b.Add(t)
                self.added.append(t)
                made += 1
        return made

    def route_net(self, name, width=None):
        net = self.b.FindNet(name)
        if net is None or net.GetNetCode() == 0:
            return {"net": name, "failed": "no such net"}
        r = dict(self.rules(name))
        if width:
            r["width"] = width
        groups = self._groups(net)
        if len(groups) < 2:
            return {"net": name, "already_connected": True}
        trk = self._blocked(net, r["width"] / 2)
        via = self._blocked(net, r["via_d"] / 2) if self.vias else None
        done = [groups[0]]
        todo = groups[1:]
        tracks = vias = 0
        length = 0.0
        while todo:
            src_pad = {}
            srcs = set()
            for p in [p for grp in done for p in grp]:
                for c in self._pad_cells(p):
                    srcs.add(c)
                    src_pad[c] = (p.GetPosition().x, p.GetPosition().y)
            for t in self.added:                          # copper this net already got from us
                if t.GetNetCode() == net.GetNetCode() and t.Type() == pcbnew.PCB_TRACE_T:
                    li = self.lids.index(t.GetLayer()) if t.GetLayer() in self.lids else None
                    if li is not None:
                        for pt in (t.GetStart(), t.GetEnd()):
                            ix, iy = self.grid.cell(pt.x, pt.y)
                            srcs.add((li, ix, iy))
            # nearest unconnected group first
            todo.sort(key=lambda grp: min(math.hypot(p.GetPosition().x - q.GetPosition().x,
                                                     p.GetPosition().y - q.GetPosition().y)
                                          for p in grp for q in [x for gg in done for x in gg]))
            grp = todo.pop(0)
            dst_pad = {}
            for p in grp:
                for c in self._pad_cells(p):
                    dst_pad[c] = (p.GetPosition().x, p.GetPosition().y)
            path = self._search(sorted(srcs), sorted(dst_pad), trk, via)
            if not path:
                refs = ", ".join(f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}" for p in grp)
                return {"net": name, "failed": f"no path to {refs} that keeps every clearance",
                        "tracks": tracks, "vias": vias}
            pad_at = dict(src_pad)
            pad_at.update(dst_pad)
            before = len(self.added)
            tracks += self._emit(path, net, r, pad_at)
            for it in self.added[before:]:
                if it.Type() == pcbnew.PCB_VIA_T:
                    vias += 1
                else:
                    length += math.hypot(it.GetEnd().x - it.GetStart().x, it.GetEnd().y - it.GetStart().y) / MM
            done.append(grp)
            # the new copper is an obstacle for nothing on this net, but later nets see it
        layers = sorted({self.b.GetLayerName(t.GetLayer()) for t in self.added
                         if t.GetNetCode() == net.GetNetCode() and t.Type() == pcbnew.PCB_TRACE_T})
        return {"net": name, "tracks": tracks, "vias": vias, "length_mm": round(length, 2),
                "width_mm": r["width"], "layers": layers}
