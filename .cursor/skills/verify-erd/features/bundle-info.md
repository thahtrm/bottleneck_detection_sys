# Bundle info

Bundle info lets a user read a model bundle's kind, config, and test metrics, and refuses a bundle whose files were edited after it was sealed.

## Sub-features

- `info-delay` prints the delay bundle manifest.
- `info-criticality` prints the criticality bundle manifest.
- `info-rejects-tamper` exits non-zero on a copy whose sealed file bytes changed.

## How to get to it (user POV)

- Run `erd bundle info bundles/delay`.
- Run `erd bundle info bundles/criticality`.
- Run `erd bundle info <copy>` after changing a file inside a copy of a bundle.

## Driving it with erd

Preconditions:

- Doctor passed.
- `bundles/delay/manifest.json` and `bundles/criticality/manifest.json` exist.
- Scratch directory `/tmp/verify-erd-$RUN_ID` exists and is empty.

- **Read delay.** Run `.venv/bin/erd bundle info bundles/delay`. Exit code 0. Stdout is JSON whose `kind` is `delay` and whose `config.model` is `delay_official_t0`.
- **Read criticality.** Run `.venv/bin/erd bundle info bundles/criticality`. Exit code 0. Stdout is JSON whose `kind` is `criticality` and whose `config.model` is `tgn_hybrid`.
- **Reject a tampered copy.** Copy the delay bundle, flip the first byte of `xgb_fold0.ubj` in the copy only, then run `.venv/bin/erd bundle info /tmp/verify-erd-$RUN_ID/delay`. Exit code is non-zero. Stderr contains `bundle file corrupted or modified`.
- **Confirm the original.** Run `.venv/bin/erd bundle info bundles/delay` again. Exit code 0 and `config.model` is still `delay_official_t0`.
- **Proof.** Save both successful JSON documents and the tamper stderr under `.cursor/skills/verify-erd/proof/bundle-info/`.

## Gotchas

- `--no-verify` makes a tampered bundle look valid. Verification runs must not pass it.
- Flip a byte only in the scratch copy. `bundles/delay` is the shipped model.
- A missing `manifest.json` fails with `not a model bundle` before any hash check. That is a different failure from tamper.
