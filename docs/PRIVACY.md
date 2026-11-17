# Privacy and diagnostics

Boardwright sends nothing anywhere by itself. It has no server and no usage counting.

There is one optional feature that keeps a record of how your work goes, so you can send a report back if you want to help improve Boardwright. It is **off** until you turn it on.

## Turning it on and off

Type one of these in Claude Code, in your project folder:

| You type | What happens |
|---|---|
| `/boardwright:pcb-diagnostics on` | Recording starts now, prompts included |
| `/boardwright:pcb-diagnostics on without prompts` | Recording starts now; your prompts are counted, but their words are not kept |
| `/boardwright:pcb-diagnostics off` | Recording stops. What was recorded stays until you delete it |
| `/boardwright:pcb-diagnostics delete` | Removes everything recorded (asks first) |
| `/boardwright:pcb-diagnostics status` | Shows what is recorded and how much |

Only you can turn it on. The plugin records your decision from the words you typed; Claude has no command for it, and the plugin refuses if Claude tries to change the setting.

## What is recorded

From Claude Code's own session files on your computer, starting from the moment you turned it on:

- your prompts (or only how many there were, and how long, if you chose "without prompts");
- which Claude models ran, how many tokens each used, and what that would cost at Anthropic's list prices (on a Pro or Max plan you are not billed per token, so this is an estimate);
- how many times each tool was used, and the tools' error messages, refusals and API errors (shortened to 300 characters);
- the checks that failed and the stage the project reached.

Not recorded: file contents, tool outputs, your board or schematic, or the requests Claude Code sends to Anthropic.

Before anything is written, these are removed: API keys and tokens (Anthropic, OpenAI-style, GitHub, AWS), `Bearer` headers, passwords written as `password=...`, private keys, e-mail addresses, your home folder (replaced by `~`) and your user name.

## Where it is kept

In your project folder, in `.boardwright/diagnostics/`. That folder has a `.gitignore` of `*`, so it never goes into your git commits. Nothing else on your computer is changed.

## Sending a report

1. `/boardwright:pcb-diagnostics report`: Claude writes a short summary in plain words at the top of `report.md`, from the numbers in it.
2. `/boardwright:pcb-diagnostics export`: makes `boardwright-diagnostics-<date>.zip` in the same folder.
3. **Open `report.md` and read it.** It can contain your prompts and part names. Remove anything you do not want to share.
4. Send the zip yourself, one of two ways:
   - the GitHub issue form **Diagnostics report** (drag the zip into it). GitHub issues and attachments on this repository are **public**;
   - by e-mail, if the maintainer has set an address in `plugin/scripts/diagnostics.json` (the export command prints it). Attach the zip yourself.

Claude never sends, uploads or attaches the report for you.

## What we do with it

Reports are read to find where the pipeline wastes time or money and where it goes wrong, for example a check that fails often or a step that costs more than it should. If you want a report removed from the GitHub issues, open an issue or close yours and ask.
