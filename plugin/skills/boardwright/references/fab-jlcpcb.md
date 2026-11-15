# Fab and suppliers

## Board rules
Fab capabilities change. At stage 5, open the fab's capability page (JLCPCB: https://jlcpcb.com/capabilities/pcb-capabilities), and record the values and the date you read them in `05-layout.md`. If the page cannot be read, use the conservative defaults below and mark them unverified.

| Item | Conservative default |
|---|---|
| Track width and spacing | 0.2 mm |
| Via | 0.3 mm drill, 0.6 mm pad |
| Copper to board edge | 0.3 mm (more for hazardous nets) |
| Board | 2 layers, 1.6 mm, 1 oz, unless the design needs more |
| Silkscreen | 0.15 mm line, 1.0 mm text height |

Use wider tracks wherever current, voltage or hand soldering asks for it; these are minimums for fabrication, not design targets.

## Suppliers
See `suppliers.md`.

## Release files
`run_gates.py` writes into `fab/`: zipped Gerbers and drill, placement CSV, BOM CSV with MPN and supplier number, schematic PDF, and the BOM and placement list again with JLCPCB's assembly column names (`-jlc-bom.csv`, `-jlc-cpl.csv`). The JLCPCB files copy KiCad's rotations unchanged; JLCPCB's library can use another zero angle for some packages, so the release checklist must tell the user to check every polarised and multi-pin part in JLCPCB's placement preview. The user uploads them. You do not.
