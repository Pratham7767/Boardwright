# Testing Boardwright: a guide for friends

Thanks for trying it. This is early software, and your bug reports are the point of the exercise. About an hour of your time covers the important parts.

**Before you start:**
- It uses **your own Claude plan or API credit**. A small test board can use a noticeable share of a Pro plan's usage limit. If you hit a limit, switch to Sonnet (model menu in the KiCad window, or `/model sonnet` in Claude Code).
- **Do not order a board** made during testing without checking it yourself. The release checklist in `reports/08-release.md` lists what to check.
- Nothing is uploaded or ordered by the tool. Your board files go to Anthropic only as part of your own Claude conversations, like any Claude Code session.

## 1. Install (15-30 min)
Follow [INSTALL.md](INSTALL.md), option A. **Note anything that confused you or failed**, including the exact text of errors. A screenshot is fine.

## 2. Setup check (2 min)
In an empty folder in Claude Code: `/boardwright:pcb-doctor`. Copy its table into your report.

## 3. A small board (30-60 min)
Make an empty folder, open it in Claude Code and start:

```
/boardwright:pcb-new guided A USB-C powered board with an STM32 or RP2040 microcontroller, a temperature and humidity sensor on I2C, a status LED, and a reset button. 2 layers, about 30 x 40 mm, assembled by JLCPCB.
```

Go as far as you can: at least through stage 4 (schematic), ideally through stage 5 (layout) with KiCad open. Things to watch:
- Did it ask sensible questions, and not too many?
- Did it ever claim something as checked that wasn't?
- Did a gate stop the work for a good reason? A bad reason?
- Was anything slow, or did it loop?

## 4. The KiCad button (Windows, 10 min)
Open the board from step 3 in KiCad's PCB Editor and click the speech-bubble button.
- Does the window open, and does the Setup box at the top report correctly?
- Ask: *"What stage is this project at?"* Do you get a streamed answer?
- Ask it to make a small change, such as moving a part's silkscreen text. Do Allow and Deny work?
- Try **Stop** in the middle of an answer, and **New chat**.

## 5. Optional: an existing board
In a folder with one of your own KiCad projects: `/boardwright:pcb-review`. It changes nothing. Is the report useful? Is anything in it wrong?

## How to report
Open an issue on the GitHub repository (the **Bug report** or **Feedback** form), or send the owner a message. Include:
- Windows / macOS / Linux version, KiCad version, `claude --version`
- the `/boardwright:pcb-doctor` table
- what you did, what you expected, what happened, plus screenshots
- KiCad button problems: the file `%TEMP%\boardwright_launcher.log`
- for wrong design decisions: the stage report from `reports/` and the part of the conversation where it happened

Before sharing a log or report, delete anything you don't want to share (names, paths).
