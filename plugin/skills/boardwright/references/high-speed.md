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
- This plugin does not run signal-integrity or power-integrity simulation.
