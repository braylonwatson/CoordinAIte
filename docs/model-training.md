# Model refresh: October 8, 2026

## Data included

The four bundled XGBoost models now use **2022, 2023, 2024, 2025, and the
available completed 2026 games**. The 2021 season is excluded.

The source remains nflverse's nflfastR play-by-play dataset. The trainer
downloads its published Parquet files directly from the
[official nflverse release](https://github.com/nflverse/nflverse-data/releases/tag/pbp).
It no longer relies on `nfl_data_py.import_pbp_data` to retrieve them.

| Season | Completed games | Eligible run/pass plays |
| --- | ---: | ---: |
| 2022 | 284 | 35,304 |
| 2023 | 285 | 35,474 |
| 2024 | 285 | 34,902 |
| 2025 | 285 | 34,502 |
| 2026, Weeks 1–4 | 64 | 7,789 |
| **Total** | **1,203** | **147,971** |

The download's most recent completed game is dated **October 5, 2026**.
Regular-season and postseason games are included; preseason, incomplete
games, future game dates, special teams plays, kneels, spikes, and plays
missing required situational inputs are excluded. Completion requires an
`END GAME` marker anywhere in the game, including games with later stat
corrections. An NFL season includes its postseason in the following calendar
year (for example, the 2025 season through February 8, 2026).

The 2026 snapshot is preliminary. nflverse can publish stat corrections;
[its update schedule](https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html)
describes when refreshed data becomes available. This refresh is a snapshot,
not an automatic weekly retraining service.

## Validation

The validation candidate was trained on 962 earlier games and tested on
241 entire games starting October 23, 2025. No game or game date appears on
both sides of the split; all available 2026 games are in this holdout. The
same split is used for all four models. No hyperparameter search was done
against the holdout.

| Model | Held-out plays | Previous model accuracy | Refreshed candidate accuracy |
| --- | ---: | ---: | ---: |
| Run/pass | 29,287 | 69.78% | 70.49% |
| Direction | 28,095 | 39.73% | 39.67% |
| Run concept | 9,302 | 38.44% | 37.95% |
| Pass concept | 15,443 | 35.36% | 35.68% |

On the 7,789 plays from 2026 specifically, run/pass accuracy was 70.20%
versus 69.78% for the previous model. On the combined holdout, run/pass log
loss improved from 0.56406 to 0.56047 and Brier score from 0.19196 to 0.19038.
These are modest observed differences; no statistical significance is claimed.
Tier 2 results are mixed, including a lower run-concept score.

After evaluation, separate **release models were refit on all eligible games**,
including 2026. The held-out accuracy above describes the validation
candidate, not an independent test of the final refit. Further unseen games
are required to evaluate those final artifacts.

Tier 2 direction is evaluated with the actual run/pass type, and concept
models are evaluated within their actual play type. These are conditional
scores, not end-to-end Tier 2 accuracy. Concept labels retain the existing
heuristics from run location/gap and air yards. They are not verified
playbook concepts or film-charted ground truth. Metrics measure the model
alone; live heuristic probability adjustments are outside this evaluation.

The previous-model comparison here uses the prior bundled 2021–2024 models
and the same live-compatible features. For later retraining runs, compare a
baseline only on games it has never trained on. A model already fitted on
the holdout is not an independent baseline, even if the script can score it.

## Feature and weighting corrections

- History uses only prior plays from the selected offense within its game;
  it resets at game boundaries, and drive history resets by drive.
- Plays are ordered by quarter and remaining game clock, then play ID, so
  later stat corrections do not become future information in past features.
- Game/drive pass rates match `GameTracker`: 0.5 before 8/4 prior plays,
  then `(prior_passes + 1) / (prior_plays + 2)`.
- The 32-team schema is fixed, with nflverse `LA` normalized to the app's
  `LAR`. The feature encoder used by the live API is unchanged.
- Per-play season weights are 1.0, 1.1, 1.3, 1.5, and 1.7 for 2022–2026.
  These recency weights are applied to all four models. Previously the
  encoded Tier 2 wrapper did not forward sample weights. They are fixed
  configuration values, not weights selected by optimizing holdout results.

## Reproduce or refresh

Use Python 3.11 from the repository root. PowerShell example:

```powershell
python -m pip install -r requirements-training.txt
python train_model.py --as-of 2026-10-08 --output-dir training_runs/refresh-20261008
```

Omit `--as-of` to use today's UTC date and omit `--output-dir` for a fresh
timestamped directory. Each run must use a new output directory. The trainer
downloads the requested seasons again so later published games/corrections
can be included. Only an absent, empty, or not-yet-completed 2026 season may
be skipped, and the reason is recorded. Missing required seasons, unexpected
schema/season content, or network failures stop the run.

For exact reproduction, retain the five source snapshots with their recorded
SHA-256 checksums and reuse them:

```powershell
python train_model.py --data-dir path/to/snapshots --as-of 2026-10-08 --output-dir training_runs/reproduction
```

The source filenames are `play_by_play_2022.parquet` through
`play_by_play_2026.parquet`. Re-downloading mutable release files later may
not produce the same checksums. Runtime/training dependency versions,
training-code checksums, every source checksum, game IDs, and artifact
checksums are recorded in `training_report.json` and the release bundle's
`training_metadata.json`. Raw data and intermediate runs are git-ignored.

Run validation before adopting a new bundle:

```powershell
python -m pip install -r backend/requirements-dev.txt
python -m pytest -q training_tests
Copy-Item training_runs/refresh-20261008/models/*.pkl backend/
Copy-Item training_runs/refresh-20261008/models/training_metadata.json backend/
python -m pytest -q training_tests
Push-Location backend
python -m pytest -q
Pop-Location
```

Inspect the report before copying. Copy all four model pickles, all four
feature-column pickles, and the metadata together. Training does not
overwrite `backend/` automatically. `--baseline-dir` can select an older
model bundle for comparison; the default is `backend/`.

CI checks filtering, causal feature history, matching training/live encoding,
sample-weight forwarding, artifact checksums, and loading/inference with the
actual pickles. CI does not download seasonal datasets or retrain the models.

## Release

The Docker image includes the model files and `training_metadata.json`.
The API loads them into memory on startup. A new backend image must be built,
pushed to ECR, and rolled out to ECS using the existing
[AWS release process](aws-deployment.md) before the running app uses this
refresh. No frontend or database migration is needed for this change.

Keep the prior image digest for rollback. Building models, committing them,
or opening a pull request does not change the production model version.
