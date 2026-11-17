# Multilayer and high-speed boards

Applies when the board has any of: USB 2.0 high-speed or faster, Ethernet, HDMI, MIPI, LVDS, DDR memory, PCIe, RF, clocks above about 50 MHz, or edge rates under about 1 ns. Also applies to any board with four or more layers.

**Status: written from general practice, not yet exercised by this plugin on a real board.** Treat every number as a starting point and take the real values from the interface standard and the chip's datasheet or layout guide, with page cites.

## Stage 1 and 2
- List every fast interface with its standard, data rate, impedance target (single-ended and differential) and length-matching limits. Source each from the standard or the chip's layout guide; if you cannot read it, write "unverified".
- Save the layout guide or reference design for each fast chip in `datasheets/`.

## Stage 5: stackup first
- Choose the layer count and stackup before placement. Every signal layer needs an adjacent, unbroken reference plane.
- Use a stackup the fab actually offers. Read the fab's stackup table and its impedance calculator for the trace width and spacing of each impedance target, and record the stackup name, dielectric thickness, the calculated widths and the date in `05-layout.md`. Do not calculate impedance from memory of a typical stackup.
- Put each impedance target in its own net class with the calculated width and differential gap. The rule guard then protects those classes like any other.
- Typical four-layer order: signal, ground, power, signal. Keep fast signals on the layer next to the ground plane.

## Stage 5: routing
- Fast nets are routed by you, by hand, like switch nodes. No autorouter.
- A fast trace must not cross a gap in its reference plane or change reference plane without a nearby return via (ground) or a stitching capacitor (power).
- Differential pairs: routed together, same layer, same via count, length matched within the limit from the standard. Match close to where the mismatch arises.
- Keep stubs off fast nets; place series termination at the driver and parallel termination at the receiver, as the chip's guide says.
- Decoupling: one capacitor per power pin as close as the package allows, each with its own via to the plane.
- Connector and ESD parts first on the path from the connector; then common-mode chokes if used; then the chip.

## Pair rules and the independent pair check
Declare every differential pair and its limits in `boardwright.json`, each limit with its source (the chip's layout guide and page):
```json
"high_speed": {"er_eff": 3.3, "er_source": "fab stackup JLC04161H-7628, calculator 2026-11-16",
  "ground_nets": ["/GND"], "max_return_via_mm": 1.5,
  "pairs": [{"name": "USB", "p": "/USB_DP", "n": "/USB_DM", "max_skew_mm": 0.15, "max_length_mm": 50,
             "max_vias_each": 2, "source": "RP2350 hardware design guide, section 5.1"}]}
```
- `python scripts/hs_rules.py . --write` (stage 5, with the other rules) writes KiCad `skew` and `length` rules, and `diff_pair_gap` / `diff_pair_uncoupled` when the net names follow KiCad's pair convention (`_P`/`_N`, `+`/`-`).
- `python scripts/hs_rules.py .` (gate `layout.hs`) measures each pair itself: lengths including via barrels, skew in mm and ps, equal via counts, and a ground via within `max_return_via_mm` of every signal via. It does not depend on KiCad grouping the pair correctly.
- A limit without a source is reported as "assumption". `max_return_via_mm` 1.5 is a working default, not a value from a standard.

## Impedance estimate
List each controlled-impedance net class with its target and the target's source:
```json
"high_speed": {"stackup": {"h_mm": 0.2, "er": 4.1, "t_mm": 0.035, "source": "JLC04161H-7628 stackup page, 2026-11-16"},
  "impedance": [{"netclass": "USB", "target_diff_ohm": 90, "tolerance_pct": 10, "source": "USB 2.0 7.1.2"}]}
```
`python scripts/impedance_check.py .` estimates each class's impedance from its width and gap (Hammerstad-Jensen microstrip, IPC-2141A stripline and coupled pairs) and fails outside the tolerance. Without a stackup it uses KiCad's default and says so. The fab's calculator sets the final width.

## Stage 6: what to measure
Add these to `boardwright.json` and the report. Where the script has no check for an item, measure it another way and say how:
- Length and skew of every matched group (`track_length` entries, compared by you).
- Each fast net's reference plane, and any place where it crosses a plane gap. A crossing is at least HIGH.
- Via count per fast net and distance from each layer change to the nearest return via.
- Stitching via spacing around the board edge and between ground planes.
- Simulation: if the user has a field solver or the fab's calculator output, record it. If not, say plainly that impedance is calculated, not simulated or measured.

## Reviewer
`gate-reviewer` runs at stages 5 and 6 on every board this file applies to, whatever model the main session uses.

## Limits
- Impedance depends on the fab's real materials and tolerances. Order impedance control from the fab if the interface needs it, and state that in the release checklist.
- This plugin estimates impedance and the decoupling bank's impedance with closed-form models; it does not run field-solver or time-domain simulation. `sim_export.py` writes IPC-2581, ODB++ and STEP for a person to run HyperLynx, CST or SIwave.
