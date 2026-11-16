# Test guide

Thank you for helping test Boardwright. It is still new, so your reports of what goes wrong are the most useful part. Plan on about an hour.

**Before you start**

- Boardwright uses **your own Claude plan**. A small test board can use a good share of a monthly plan. If you hit a limit, switch to the Sonnet model.
- **Don't order a board made during testing** without checking it yourself. The list of things to check is in `reports/08-release.md`.
- Boardwright never orders or uploads anything.

## 1. Install (15-30 minutes)

Follow the [install guide](INSTALL.md). Write down anything that confused you or went wrong, with the exact error message. A screenshot is fine.

## 2. Check the setup (2 minutes)

Open an empty folder in Claude Code and type `/boardwright:pcb-doctor`. Copy its table into your report.

## 3. Design a small board (30-60 minutes)

Make an empty folder, open it in Claude Code and type:

```
/boardwright:pcb-new guided A USB-C powered board with an STM32 or RP2040 microcontroller, a temperature and humidity sensor, a status LED and a reset button. 2 layers, about 30 x 40 mm, assembled by JLCPCB.
```

Try to get at least to stage 4 (the circuit drawing), and stage 5 (the layout) if you can, with KiCad open. While it works, notice:

- Were the questions sensible, and not too many?
- Did it ever say something was checked when it wasn't?
- When a check stopped the work, was the reason good?
- Was anything slow, or did it repeat itself?

## 4. Try the KiCad chat button (10 minutes)

Open your board in KiCad and click the speech-bubble button.

- Does the window open, and does the Setup box show the right things?
- Ask *"What stage is this project at?"*. Does an answer appear?
- Ask for a small change. Do the Allow and Deny buttons work?
- Try **Stop** while it is answering, and **New chat**.

## 5. Optional: check a board you already have

In a folder with one of your own KiCad projects, type `/boardwright:pcb-review`. It changes nothing and writes `reports/review.md`. Is the report useful? Is anything in it wrong?

## How to report

Open an issue on GitHub (use the **Bug report** or **Tester feedback** form), or message the owner. Include:

- your operating system, KiCad version, and the output of `claude --version`;
- the `/boardwright:pcb-doctor` table;
- what you did, what you expected and what happened, with screenshots;
- for chat-button problems, the log file (`%TEMP%\boardwright_launcher.log` on Windows, `/tmp/boardwright_launcher.log` on Linux);
- for wrong design choices, the stage report from `reports/` and what Claude said.

Remove anything private, such as names or folder paths, before you share a file.
