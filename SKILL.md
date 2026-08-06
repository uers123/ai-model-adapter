---
name: ai-model-adapter
description: "Plan and, only after explicit authorization, adapt, evaluate, re-test, monitor, pause, resume, clean up, and export open-source AI models using a local-first database. Use only when the user message begins with the explicit /ai-model-adapter command; support specified-model-first selection, automatic measurable acceptance criteria, multimodal workflows, Windows-first execution, isolated campaigns, and dry-run analysis."
---

# AI Model Adapter

Do not invoke this skill implicitly. Require the exact `/ai-model-adapter` prefix.

## Operating contract

- Treat `AI_MODEL_ADAPTER_DB` as the knowledge database override.
- Treat `AI_MODEL_ADAPTER_TASKS` as the isolated campaign-root override.
- Treat `AI_MODEL_ADAPTER_CACHE` as the read-only resource-cache override.
- When an override is absent, use the Windows defaults implemented by `scripts/common.py`.
- Allow overrides only with `AI_MODEL_ADAPTER_DB`, `AI_MODEL_ADAPTER_TASKS`, and `AI_MODEL_ADAPTER_CACHE`, or explicit CLI flags.
- Never download a model, weight, dataset, or repository unless the user explicitly authorizes that campaign operation.
- Never write credentials, tokens, passwords, signed URLs, or private data to a campaign, database, log, report, or chat.
- Keep training, validation, and final blind-test manifests separate. Do not tune on the final blind-test set.
- Preserve the original model and source materials. Export an adapter or manifest; do not overwrite a base model.

## Fixed command interface

Use `scripts/cli.py` for:

```text
/ai-model-adapter plan
/ai-model-adapter authorize <campaign_id>
/ai-model-adapter start <campaign_id>
/ai-model-adapter status <campaign_id>
/ai-model-adapter watch <campaign_id>
/ai-model-adapter unwatch <campaign_id>
/ai-model-adapter pause <campaign_id>
/ai-model-adapter resume <campaign_id>
/ai-model-adapter stop <campaign_id>
/ai-model-adapter evaluate <campaign_id>
/ai-model-adapter export <campaign_id>
/ai-model-adapter update-db
```

The runner must:

1. Convert the natural-language goal to task type, modalities, metrics, baseline, limits, and acceptance criteria before training.
2. Prefer the specified model. If none is specified, recommend candidates from the database and stop for approval.
3. Reject an unqualified model, missing license, missing evaluation method, missing budget, non-compliant data, or an impossible target before starting.
4. Use the lowest-risk strategy first: inference/prompting, RAG, data repair, LoRA/Adapter, partial unfreeze, full fine-tune, modality projection, architecture change, then model replacement.
5. Require separate approval for architecture changes, base-model replacement, cloud execution, data upload, budget expansion, publication, or full-weight merge.
6. Run each campaign in its own workspace with persistent local state, event history, heartbeat reports, checkpoints, failure memory, and safe cleanup plans.
7. Stop on acceptance, budget limits, no-improvement patience, blocking errors, pause, or stop.
8. Run automatic evaluation and require blind human review for open-ended or multimodal quality claims. Never invent human scores.

## Workflow and safety

- `plan` is analysis-only and creates an `awaiting_authorization` campaign.
- `authorize` requires every budget and allowed-method field on every campaign.
- `start` creates isolated directories. The first-version NExT-GPT adapter is dry-run-only and must block every real-training request, even when resource paths are present.
- `status` reads `status/current.json`; the local file is authoritative.
- `watch` and `unwatch` create or remove a monitor registration; `monitor_campaign.py` reports heartbeats.
- `pause` requests a safe-point pause; `resume` verifies hashes and state before continuing.
- `stop` stops without deleting evidence.
- `evaluate` writes an evaluation record. `export` is allowed only for an accepted campaign with no pending human review.
- `update-db` writes an audited proposal under `pending-updates`; it never mutates the formal catalog automatically.

Read only the references needed for the request:

- `references/database-layout.md`: database paths and field conventions.
- `references/model-qualification.md`: execution qualification gate.
- `references/adaptation-strategies.md`: staged adaptation and approval boundaries.
- `references/acceptance-criteria.md`: task-type metric mapping and blind review.
- `references/data-governance.md`: source, license, privacy, hash, and split rules.
- `references/windows-compatibility.md`: Windows-native and WSL2 boundary.
- `references/campaign-lifecycle.md`: state machine, budget, heartbeat, pause, resume, and recovery.
- `references/security-policy.md`: secret handling and no-upload defaults.
- `references/next-gpt.md`: legacy/current NExT-GPT records and dry-run rules.

Before delivery, run:

```powershell
python scripts/self_test.py
python scripts/validate_database.py
python scripts/validate_campaign.py <campaign_id>
python scripts/cli.py --help
```

For a full database build, also run `scripts/build_verification.py` with explicit database, task, cache, Skill, old-source, expected old-source state, required campaign, and output arguments.
