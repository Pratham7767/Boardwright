# Glossary

The circuit-board words used in Boardwright, explained simply.

**BOM (bill of materials).** The shopping list of every part on the board.

**Clearance.** The shortest distance through the air between two pieces of copper. Too little, and electricity can jump across.

**Corridor.** In the optional routing plan, an area of the board where Claude may run tracks for a group of nets. Only the designer approves it.

**Courtyard.** The outline around a part that no other part should enter. It leaves room to place and solder the part.

**Creepage.** The shortest distance between two pieces of copper along the board's surface. Dirt and moisture on the surface can let current creep across, so this distance must be long enough too.

**Datasheet.** The manufacturer's document for a part: its pins, limits and how to use it.

**Decoupling capacitor.** A small capacitor placed next to a chip's power pin. It supplies quick bursts of current and keeps the power steady.

**DRC (design rule check).** KiCad's check of the board layout: tracks too close together, missing connections, and so on.

**EMC (electromagnetic compatibility).** Whether a board gives off too much radio interference, or is upset by interference from outside. It is tested in a lab.

**ERC (electrical rule check).** KiCad's check of the circuit drawing: unconnected pins, outputs wired together, and so on.

**Fab files (Gerbers).** The files a factory uses to make the bare board. Boardwright also makes the drill file, the parts list and the part positions.

**Gate.** A check that must pass before the next stage starts.

**Ground pour.** A large area of copper connected to ground. It gives signals a clean return path and reduces interference.

**Impedance.** For fast signals, the resistance a track presents to a changing signal. USB, for example, expects about 90 ohms between its two wires.

**Isolation barrier.** The gap on a mains board between the dangerous side (connected to the wall socket) and the safe side (the part you can touch).

**KiCad.** The free, open-source program used to design the board.

**Mains.** The power from the wall socket: 230 V in India and Europe, 120 V in the US.

**Lifecycle.** Whether a part is still being made and sold, or is being phased out (discontinued).

**Net.** One electrical connection: everything that is wired together.

**Net class.** A group of nets that share rules, such as track width and spacing.

**Schematic.** The circuit drawing: which parts there are and how they are wired.

**Skew.** The difference in length between the two wires of a fast pair. Too much, and the signal arrives out of step.

**Stackup.** The layers of the board: copper, insulating material, and their thicknesses.

**Via.** A small plated hole that carries a track from one copper layer to another.

**X and Y capacitors.** Special capacitors that are safe to use on mains. X capacitors sit between the mains wires; Y capacitors sit across the isolation barrier.
