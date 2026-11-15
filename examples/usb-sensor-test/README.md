# Example: USB-C temperature and humidity sensor

A real board taken through the Boardwright pipeline in guided mode, kept here so you can see what each stage produces before you start your own.

- **The board:** 30 x 40 mm, 2 layers, USB-C powered, an STM32F042K6T6 reading an AHT20 sensor over I2C and showing up as a USB serial port. Machine-assembled by JLCPCB (`PROJECT.md`).
- **Stage reports:** `reports/01-spec.md` to `reports/08-release.md`, plus the gate results (`gates.md`, `erc.json`, `drc.json`), the EMC geometry check and the retro.
- **Release files:** `fab/` (Gerbers, drill, placement, BOM, schematic PDF, JLCPCB assembly files).

**It is not ready to order.** Two gates were left open by the designer's decision and are listed at the top of `reports/08-release.md`:
- stage 2: three part details are unconfirmed;
- stage 7: one resistor was out of stock.

That's the pipeline behaving as designed: it reports open gates rather than hiding them.

Datasheets are not included (see `datasheets/README.md`). The gate scripts are not included either. To rerun the checks, copy this folder somewhere, open it in Claude Code and run `/boardwright:pcb-gates`. If `scripts/` is missing, Claude first restores it from the plugin.
