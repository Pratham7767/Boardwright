# Layout and circuit rules by block

What manufacturers' application notes say for common circuit blocks (read 2026-11-15; sources at the end). Use the section for each block the board contains: at stage 4 for the circuit, at placement and routing for the layout, at stage 6 for what to measure.

**The part's own datasheet and layout guide always come first.** Numbers below come from the named document and often from one example part; cite the document, not this file, and do not apply a number to a different part without checking. Where a common practice was not found in a document that was opened, it is listed under "Not confirmed" and must be taken from the part's datasheet.

## 1. Decoupling
- One 100 nF capacitor per supply pin, close to the pin; a capacitor shared by two pins is a stated compromise (RP2040 p7).
- Internal-regulator pins get their own capacitors at input and output (RP2040 p7-8: 1 uF each).
- Ground via right at the capacitor's ground pad; IC and capacitor ground pads join the pour directly (ESP-PCB).
- No via between the pin and its capacitor on precision analog parts (ADS8881 layout section).
- Analog supply pins get a filter (ESP-SCH: LC filter on the analog rail).
- Measure: capacitor on every supply pin net (`sch_check.py`), pad-to-pin distance, via position.

## 2. Buck converters
- Place and route in this order: input capacitor, inductor, output capacitor, small-signal parts, ground (SLYT614 p11-13).
- Input capacitor as close to the IC as the fab allows, on wide short copper, without vias in the power path (SLYT614 p11-12).
- Switch-node copper small; unbroken ground under the stage (SLYT614 p12; AN-1229).
- Feedback trace away from the inductor and diode, never under them; cross power traces at right angles only (AN-1229 s8).
- Power ground and quiet ground meet at one point; about one via per amp where vias are unavoidable (SLYT614 p13).
- Measure: hot-loop area, input-capacitor distance, switch-node copper area, feedback length and distance to the inductor (`emc_geometry.py`).

## 3. Linear regulators
- Dissipation is (Vin - Vout) x Iout and must fit the package: check junction temperature with the datasheet's thermal resistance (SLVA079 p11).
- Vin must stay above Vout plus dropout at full load (SLVA079 p2).
- The output capacitor's ESR must sit inside the stability window the datasheet gives; a ceramic is not automatically allowed (SLVA079 p9).

## 4. Crystals
- Load capacitance: CL = (C1 x C2)/(C1 + C2) + stray. Calculate it and write the stray value assumed (RP2040 p9; Nordic gives its own form with pin and board capacitance).
- Shortest possible traces; no vias on the clock traces; nothing fast routed under the crystal; ground copper with stitching vias around it (ESP-PCB; RP2040 p9).
- Measure: crystal-to-pin distance, vias on the crystal nets, foreign tracks under the body.

## 5. USB 2.0 and USB-C
- 90 ohm differential pair over unbroken ground; width and gap from the fab's calculator for the real stackup (RP2040 p11 gives one worked example).
- Series resistors at the chip if its hardware guide asks for them (RP2040: 27 ohm).
- Same via count on both lines, no stubs, no test points on the pair, ground stitching vias near signal vias (SPRAAR7).
- Protection parts as close to the connector as possible (SPRAAR7 s3.14).
- USB-C device (sink): 5.1 k pull-down on each CC pin; confirm in the connector-side controller's or the USB-C documentation.
- Measure: pair length difference, via count, ESD part to connector distance, CC resistor values.

## 6. ESD and TVS at connectors
- TVS next to the connector; the protected IC well beyond it (SLVA680 s2.1).
- The line runs from the connector pad to the TVS pad and then on; no stub to the TVS, no via before it (SLVA680 s2.1-2.3).
- Keep unprotected traces out of the connector-to-TVS area (SLVA680 s2.2).
- TVS ground straight into the plane with a via at the pad (SLVA680 s2.4). Trace inductance decides the result: ROHM's example shows a long thin connection letting a far higher peak through than a short one.
- Measure: TVS to connector distance, vias and length on that segment, ground via distance.

## 7. Reset, boot and debug
- A reset pin never floats; use the pull-up and capacitor the chip's hardware guide gives (ESP-SCH: 10 k and 1 uF for ESP32).
- Boot or strapping pins: read the boot table of the exact chip; the polarity differs between families, and a capacitor on a strapping pin can select the wrong mode (ESP-SCH; RP2040 p8).
- Bring the debug port to a header and give it ground (RP2040 p23).

## 8. I2C, SPI, UART
- I2C pull-ups: Rp(min) = (Vcc - VOL(max))/IOL and Rp(max) = tr/(0.8473 x Cb). Calculate both from the bus capacitance and speed (SLVA689 s2, Table 2-1).
- Series resistors on fast edges where the chip's guide asks for them, placed at the driver (ESP-PCB).
- Buses with a clock: match lengths as the guide requires and avoid layer changes (ESP-PCB for SDIO).

## 9. Analog inputs and references
- Reference capacitor of the value and type the datasheet names, right at the pin; input filter at the input pins with C0G capacitors (ADS8881 layout section).
- One ground plane, partitioned into analog and digital areas, not cut; analog traces stay in the analog area on every layer (SLYT512 p5-6).

## 10. Ground and return paths
- One continuous plane. If a split cannot be avoided, bridge it once and route every crossing signal over the bridge (SLYT512 p5).
- Four layers: layer 2 is ground with no traces. Two layers: unbroken ground under the chip, the crystal and any RF part (ESP-PCB).
- Stitching vias near every signal layer change and regularly across large pours; no copper islands (SPRAAR7; Nordic).

## 11. Thermal
- Exposed pads need the via count and size the package note gives (SLMA002 s2.4; ESP-PCB asks for at least nine on the ESP32).
- Thermal vias help far more than extra back-side copper, and copper area stops helping beyond a point (AN-1229 s6.3).
- Track width from the current, not from habit (AN-1229 s6.1 gives a per-amp rule for 1 oz and 2 oz copper).

## 12. RF and antennas
- 50 ohm feed on an outer layer: constant width, no vias, no branches, gentle bends, ground vias along it (ESP-PCB).
- Keep-out around the antenna as the module's guide gives it, antenna at the board edge, noisy parts away (ESP-PCB; Nordic).
- Matching network footprint next to the chip, values from the vendor or from measurement.

## 13. Input protection
- Reverse-polarity protection: a series diode costs its forward drop; a MOSFET costs rDS(on) x I and must be oriented so its body diode conducts in the normal direction (SLVA139 p1-2).
- Fuse or resettable fuse rating from the load current and the derating curve in its datasheet.

## Not confirmed in an opened document (take from the part's datasheet)
Linear-regulator capacitor placement; USB-C shield connection; generic reset and boot resistor values for ARM microcontrollers; typical series-resistor values; cap-to-pin distance limits in millimetres; mounting-hole and board-edge clearances; fuse sizing. Several notes (AN4488, MT-101, MT-031) could not be opened when this was written. Crystal guard rings and load capacitance, USB ESD and VBUS protection ratings, fiducials and inrush are now in [design-practice.md](design-practice.md).

## Sources
TI: SLYT614 (step-down layout), AN-1229 / SNVA054C (switcher layout), SLVA079 (LDO terms), SLVA689 (I2C pull-ups), SLVA680 (ESD layout), SPRAAR7 (high-speed interface layout), SLYT512 (mixed-signal grounding), SLMA002 (PowerPAD), SLVA139 (reverse-polarity protection), ADS8881 datasheet layout section. Raspberry Pi: "Hardware design with RP2040". Espressif: ESP Hardware Design Guidelines, schematic checklist and PCB layout. Nordic DevZone: general PCB guidelines for nRF52 (marked unmaintained). ROHM AN067E and Vishay 88450 (TVS placement). Read by a helper; some only in the relevant section.
