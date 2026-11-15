# {{PROJECT_NAME}}

Claude reads this file at the start of every session. Fill in what you know; `/boardwright:pcb-new` asks for the rest.

## Idea
(One paragraph: what the board does, what powers it, what it connects to.)

## Mode
guided | express

## Entry point
from an idea | from an existing schematic | review only

## Must-haves
| Item | Value | Source |
|---|---|---|
| Input power | | user |
| Outputs / loads | | user |
| Connectors | | user |
| Board size limit | | ASSUMPTION - confirm |
| Ambient and enclosure | | ASSUMPTION - confirm |
| Assembly | hand / machine | user |
| Build quantity | | user |
| Fab | JLCPCB | default |
| Country and currency | | user |
| Suppliers to check | LCSC automatically; others by hand (list the ones you buy from) | user |
| Fast interfaces (USB, Ethernet, DDR, RF ...) | none | ASSUMPTION - confirm |
| Layers | 2 | ASSUMPTION - confirm |
| Target standard | none | ASSUMPTION - confirm |

## Voltage class
Highest voltage on the board: 
Mains-connected: yes / no
Isolation barrier: yes / no
(If hazardous voltage is present, the high-voltage rules of the pipeline apply and cannot be switched off.)

## Decisions (newest first, with date)
- 

## Approved waivers (with date)
- none
