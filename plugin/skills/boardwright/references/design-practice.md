# Design practice: choices that make a board right the first time

Read before stage 4 (schematic) and again before stage 5 (layout). These are defaults, not gates: when a part's datasheet says otherwise, the datasheet wins, and you cite it. Every rule names its source (list at the end). Rules already in `block-guides.md` are not repeated here.

## 1. Choose the stackup before placing anything
- Every signal and power layer needs a solid ground reference right next to it. The return current of any AC signal flows in the reference plane directly under the trace, so the plane under a trace must be unbroken. [PL-stack]
- **2 layers:** top for parts and signals, bottom as one solid ground pour. Route on the bottom only in short jumps, and never cut the bottom pour into islands with long traces. [PL-mistakes, PL-EMI]
- **4 layers:** default `SIG – GND – GND – SIG` (or `SIG – GND – PWR – SIG` only when a rail needs a plane). Route power as wide pours on the signal layers. [PL-stack]
- **6 layers:** `SIG – GND – SIG – PWR – GND – SIG`. [PL-stack]
- For controlled impedance, ask the fab for its stackup and use its numbers instead of designing one yourself. [RF-workshop]

## 2. Return paths and layer changes
- Do not route a trace across a split, slot or void in its reference plane. Check that rows of vias or holes don't merge into a slot in the plane. [PL-EMI, PL-mistakes]
- When a signal changes layers, put a ground via next to the signal via, so the return current can change layers too. If the reference changes from GND to a power plane, place a small capacitor between the two planes near the change. [PL-EMI, RF-workshop]
- No stubs on fast nets. Route the nets of one bus with the same topology. [RF-workshop]

## 3. Widths, spacing, vias
- Do not pack traces at the fab's minimum spacing. Aim for at least 3 x the height of the trace above its reference plane (0.11 mm dielectric → at least 0.33 mm, more if there is room). [PL-mistakes]
- Size each trace for its job: current, sensitivity, impedance. As a rough guide, 0.2 mm carries about 1 A for a 20 °C rise on an outer layer; get the real number from an IPC-2152 calculator for the copper weight. [PL-mistakes]
- Default via: 0.3 mm drill, 0.7 mm diameter, unless the fab profile or a BGA needs smaller. [PL-mistakes]

## 4. Decoupling, in practice
- Capacitor next to the pin it serves. Short, wide connections. The capacitor's power and ground vias sit next to each other, so the loop is small. [PL-mistakes]
  (Values, count and which cap goes nearest: `block-guides.md` §1 and the part's datasheet.)

## 5. Crystals (STM32 and similar MCUs)
- Crystal as close to the MCU as possible, with short traces. [AN2867 §7.1]
- A grounded guard ring around the crystal and its load capacitors, and a ground area under them; no high-frequency signal routed near or under the oscillator. [AN2867 §7.1]
- Load capacitors: `CL = (CL1 x CL2) / (CL1 + CL2) + Cs`, where CL is the crystal's datasheet load capacitance and Cs is pin plus board stray capacitance. Cs is board-dependent; AN2867's worked example uses 5 pF. Write the arithmetic into `04-schematic.md`. [AN2867 §3.3]
- Check the oscillator gain margin: gain margin > 5, from the MCU's gm and the crystal's ESR and C0. [AN2867 §3.4]

## 6. USB connectors: ESD and VBUS
- D+ and D-: ESD diodes with VRWM ≥ 3.3 V, capacitance < 4 pF, rated at least IEC 61000-4-2 8 kV contact and 15 kV air. [SLVAF82 p5-6, p14-15]
- VBUS: ESD or TVS diode with VRWM ≥ 5 V. With USB-PD, choose the surge diode for the highest negotiated voltage (TI's examples cover 5, 9, 15, 20 and 28 V). [SLVAF82 p5-6, p16]
- Type-C CC pins: VRWM ≥ 5 V. SBU pins: VRWM ≥ 3.6 V and very low capacitance. [SLVAF82 p14]
- Place the diodes between the connector and everything else, as close to the connector as the rules allow. [SLVAF82 p6, p15]
- VBUS capacitance on a USB device: the USB 2.0 specification limits it to 10 µF (as quoted by a USB test site; confirm against the spec before you rely on it). [USB-inrush]

## 7. Inrush when a capacitive load is switched on
- `I_inrush = C_load x dV/dt`. For a maximum acceptable inrush current, the minimum rise time is `dt = C_load x dV / I_inrush`. [SLVA670 p1-3]
- Use a load switch with controlled rise time (or a regulator with soft start) when the inrush would exceed the connector's or source's rating, could collapse the rail and reset other blocks, or when several capacitive loads switch on separately. [SLVA670]

## 8. Ready for assembly (DFM)
- Fiducials for machine assembly: 1 to 3 mm copper dot, a clear area (no mask, no copper) about as wide as the dot, three global fiducials near the board corners (at least one if space is short), and two local fiducials diagonally around fine-pitch parts. Keep global fiducials about 7.6 mm (0.3 in) from the board edge, measured outside their clear area. Check the assembler's own rule; JLCPCB, for example, places panel fiducials itself. [Altium-DFM]
- Before release: designators don't overlap, no silkscreen on pads or holes, mounting holes placed, and the 3D bodies don't collide (KiCad: the 3D viewer and the courtyard DRC). [Altium-cleanup]

## 9. KiCad workflow
- Set up the board first: **File → Board Setup**: stackup, the fab's constraints, and net classes with their widths and clearances. Then **Update PCB from Schematic (F8)**. [KiCad-GS]
- Footprints come from the symbol fields or the footprint assignment tool, and every one is checked against the datasheet land pattern (stage 2). [KiCad-GS]
- Refill zones (B) before DRC and before plotting. DRC runs with schematic parity. The release plots copper, outline, mask, silkscreen and paste layers, plus drill files. `run_gates.py` does all of this on a refilled copy. [KiCad-GS]

## Sources
- [PL-stack] Phil Salmony (Phil's Lab), "PCB Stackup Basics", Altium Resources, 2022.
- [PL-EMI] Phil Salmony, "PCB Design Tips for EMI and SI Part 2", Altium Resources, 2022.
- [PL-mistakes] Phil Salmony, "Beginner PCB Design Mistakes and How To Avoid Them", Altium Resources, 2022.
- [RF-workshop] Sierra Circuits, recap of Robert Feranec's PCB layout workshop, 2018.
- [Altium-DFM] Altium, "Navigating PCB Manufacturing: Part 2" (e-book), 2022. [Altium-cleanup] Zach Peterson, "PCB Layout Cleanup Before Manufacturing", Altium Resources, 2022.
- [AN2867] ST AN2867, "Guidelines for oscillator design on STM8AF/AL/S and STM32 MCUs/MPUs".
- [SLVAF82] TI SLVAF82B, "ESD and Surge Protection for USB Interfaces". [SLVA670] TI SLVA670A, "Managing Inrush Current".
- [KiCad-GS] KiCad 10.0 documentation, "Getting Started in KiCad".
- [USB-inrush] testusb "USB Inrush Current" page, quoting the USB 2.0 specification (secondary source).

Read on 2026-11-16 through text extraction; videos by Phil's Lab, Robert Feranec and Altium Academy were not watched. Their written articles were used instead.
