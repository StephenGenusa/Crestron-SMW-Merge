# SMW Merge #

A three-way merge for Crestron SIMPL Windows programs (`.smw` files), so that several programmers can work on the same program and combine their changes.

Written and maintained by Stephen Genusa.

It grew out of an unfinished Python 2 utility of the same name that Ian Epperson published on Google Code. This version runs on Python 3, and the merge itself has been rewritten: how conflicts are settled, how handles are renumbered, and how subsystems, signals and hardware are merged. See [Credits and license](#credits-and-license).


## Why is it needed? ##

SIMPL Windows files are plain text, but an ordinary text merge breaks them. Every symbol, signal and device is identified by a handle number, and objects refer to each other by those numbers. Two people who each add a symbol will both be given the same new handle, and a text merge cannot tell the two apart or repair the references.

This utility unwraps the cross references, merges the objects, and writes the references back with handle numbers that do not collide.


## Requirements ##

Python 3. There is nothing else to install.


## Usage ##

    python3 smwmerge.py [options] your-file their-file original-file

| File | What it is |
|---|---|
| `your-file` | The program with your changes. |
| `their-file` | The program with the other programmer's changes. |
| `original-file` | The program both of you started from. |

The merged program is written to standard output, or to a file with `-o`:

    python3 smwmerge.py mine.smw theirs.smw original.smw -o merged.smw

| Option | Meaning |
|---|---|
| `-o FILE`, `--output-file=FILE` | Write the result to FILE instead of standard output. |
| `-p SIDE`, `--primary=SIDE` | The file that wins a conflict: `mine` or `theirs`. The default is `theirs`. |
| `-l LEVEL`, `--logging-level=LEVEL` | How much to report: `critical`, `error`, `warning` (the default), `info` or `debug`. |
| `-f FILE`, `--log-file=FILE` | Write the report to FILE instead of standard error. |
| `-h`, `--help` | Show the options. |

A merge with nothing to report prints nothing but the merged program.


## What gets merged ##

Changes from both files are kept wherever they can be:

- **New objects.** Symbols, signals, devices and their settings added on either side are all kept. Where both sides used the same handle number, one is renumbered and everything that refers to it follows.
- **The same object changed on both sides.** It is merged key by key. If you change a symbol's parameter and the other programmer changes its comment, the result has both changes.
- **Subsystems.** When both sides add symbols to the same subsystem, it lists all of them. A symbol deleted on one side is taken out of its subsystem even if the other side also changed that subsystem.
- **Signals.** Signals are matched by name. A signal renamed on one side keeps its connections to symbols the other side added.
- **Hardware.** Devices added on both sides in different slots are both kept, each with its own symbol and settings.
- **Deletions.** An object deleted on one side and left alone on the other is deleted.


## Conflicts and the primary file ##

One file is the primary. By default it is `their-file`; choose yours with `--primary mine`.

The primary wins only where the two sides cannot both be kept:

- **The same key of the same object was changed to different values.** For example, both of you changed the same parameter of the same symbol. The primary's value is kept.
- **Both sides put a device in the same slot,** such as two Cresnet devices at the same ID. The primary's device is kept. The other device is removed, along with its symbol and settings.

Each time this happens, a warning names the object, what each file had, and which was kept:

    WARNING: Conflict in Sm 21 (One Shot): P1 is '.75s' in your file and '.25s' in their file.  Kept theirs.

Nothing is discarded without a warning. With the default, it is your change that is discarded, so read the warnings and make that change again if it is still wanted.

The primary also keeps its handle numbers where the two sides collide. The other side's new objects are the ones renumbered.


## Limits ##

- It cannot stop and ask you to settle a conflict. The primary always wins.
- The exit status is 0 even when there were conflicts. Check the warnings.
- If both sides add an identical new symbol, the result has two of them.
- Signals that nothing is connected to are not written to the merged program.
- Open symbol windows are not merged.


## Tests ##

    python3 -m pytest

The tests need `pytest`. Most of them run the program on two real SIMPL Windows programs, with edits made to copies of them. Those two programs are not included in the repository, and the tests that need them are skipped when they are absent. To run them, put the programs named at the top of `test_smwmerge.py` in this folder, or set `SMW_TEST_PROGRAMS` to the folder that holds them.


## Current state ##

Not yet proven in real use. The merges are tested against edits made by the test suite to two real programs. No merged program has yet been opened and compiled in SIMPL Windows. Until that has been done on your own programs, keep the three input files and check the result before relying on it.


## Credits and license ##

Copyright © 2026 Stephen Genusa.

Earlier work that this program builds on:

- The original `smwmerge.py`, copyright Ian Epperson.
- `mymerge.py` by Marcos Chaves, which parts of the original were based on.

This software may be used and distributed according to the terms of the GNU General Public License, incorporated herein by reference.
