# Example: USB temperature and humidity sensor

A small board designed with Boardwright, kept here so you can see what each stage produces.

- **The board:** 30 x 40 mm, 2 layers, powered from USB-C. A microcontroller (STM32F042K6T6) reads a temperature and humidity sensor (AHT20) and shows up on the computer as a USB serial port. Built and assembled by JLCPCB. Details in `PROJECT.md`.
- **Stage reports:** `reports/01-spec.md` to `reports/08-release.md`, plus the check results.
- **Factory files:** in `fab/`.

**It is not ready to order.** Known open items:

- Stage 2: three part details are unconfirmed.
- Stage 7: one resistor was out of stock.
- A review with `/boardwright:pcb-review` (0.5.0) found that the regulator U2 uses a symbol for a different part (AP2204K-1.5 instead of AP2112K-3.3), and that its USB pair changes layer without nearby ground vias.

Boardwright reports these open items rather than hiding them.

The datasheets are not included, because they belong to their manufacturers (see `datasheets/README.md`). To run the checks yourself, copy this folder, open it in Claude Code and type `/boardwright:pcb-gates`.
