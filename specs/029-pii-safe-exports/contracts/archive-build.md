# Contract: Archive Build

## Command

```text
python app.py zip_exports [output_dir]     # default data/exports
```

Runs `zip_exports_flow`. In the weekly list: right after `people_relationship_graph`, critical, 900 s.

`export_canonical_data_flow(output_dir, campus, zip_exports=True)`: the default keeps in-process callers as they are. `app.py export_canonical` passes `False`.

## Gate in `run_weekly`

The phase is not run, and is recorded as a non-critical failure "skipped", when any earlier critical phase failed or any of these failed: `export_canonical`, `knowledge_areas_mart`, `initiatives_analytics_mart`, `people_relationship_graph`.

| Situation | Archive on disk | Exit code | Published |
|---|---|---|---|
| All fine | New | 0 | Yes |
| Mart or graph failed | Previous, untouched | 0 | No: no diff |
| `export_canonical` failed | Previous, untouched | 1 | No |
| Critical phase after the build failed | New | 1 | No: commit is `if: success()` |
| Non-critical phase after the build failed | New | 0 | Yes |
| Portal early stop | New | 0 | Yes |
| Scan error, over 100 MiB | Previous, temp removed | 1 | No |
| A match in the scan | New, with tokens | 0 | Yes |

## Member handling

| Member | Action |
|---|---|
| Text, unchanged by scan | `zf.write`, date kept |
| Text, changed by scan | `zf.writestr`, date from the file, deflate |
| Project documents | As today: scrubbed copy; also goes through the scan |
| Skip folders, nested zips | As today, left out |
| Other extensions | Left out, logged |
| `export_manifest.json` | Added last |

Written to `.tmp`, replaced atomically.

## `scan_text(text) -> (text, counts)`

Lives in `pii_anonymizer.py`.

- Emails, phones, formatted CPFs, through the existing scrub functions.
- JSON pairs of known fields, string or number values, not tokens, not null: tokenized by field type. Fields: `OrientadoEmail`, `OrientadorEmail`, `email`, `contact_email`; `OrientadoCpf`, `OrientadorCpf`, `identification_id`; the `_PAYLOAD_PHONE_FIELDS`.
- Idempotent: `scan_text(scan_text(t)[0])` changes nothing and counts 0.
- Hash values are never altered.

Logs and reports hold the file name and counts only.

## Keys

No HMAC key: `RuntimeError`, the phase fails, the previous archive stays. The workflow already requires the key.
