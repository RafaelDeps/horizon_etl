# Contract: the Lattes download functions

All in `src/flows/lattes/download.py`. Signatures only gain optional
parameters, so every current caller and test keeps working.

## `AccessCheckPage(ScriptLattesRuntimeError)`

It is raised by:
- `_download_lattes_to_cache`, for a new curriculum;
- `refresh_one`, inside `refresh_lattes_cache`, for a refresh.

In both cases the file the portal wrote is not a curriculum page. The
message stays the same: `The portal served no curriculum for Lattes ID <id>
(access check page)`.

Before raising:
- `_download_lattes_to_cache` deletes the file, as today;
- `refresh_one` leaves the cached copy untouched, as today.

## `prefetch_lattes_cache(lattes_ids, cache_dir, max_workers=3, downloader=None, stop=None, not_tried=None, access_checked=None) -> List[str]`

- **New:** `access_checked`, an optional list. Every id whose request raised
  `AccessCheckPage` is appended to it, once.
- **Return value, logs and the other output list:** unchanged.

## `refresh_lattes_cache(lattes_ids, cache_dir, max_workers=3, downloader=None, stop=None, access_checked=None) -> Tuple[refreshed, failed, not_tried]`

- **New:** `access_checked`, as above. An id in it is also in `failed`, as
  today.

## `rotate_lattes_downloads(lattes_ids, cache_dir, manifest, share, full, max_workers=3, downloader=None, retry=None, sleep=time.sleep) -> Dict[str, object]`

- **`retry`:** an `AccessCheckRetrySettings`. `None` reads
  `access_check_retry_settings()` from the environment.
- **`sleep`:** used for the pause when there is no `PortalStop`, that is
  with `HORIZON_PORTAL_EARLY_STOP=0`. With a stop, the pause is
  `stop.wait(pause_s)`.

**Rules**:
1. **The first pass is unchanged:** the new curricula, then the refresh
   share, with `max_workers` and the run's stop.
2. **Second pass condition:** it happens if and only if
   - `retry.workers > 0`, and
   - at least one id is in `access_checked`, and
   - the stop is absent or not stopped.

   Otherwise nothing more happens, and the result is identical to today's.
3. **Its items:** the access-checked new ids, then the access-checked
   refresh ids. Each list is deduplicated and kept in plan order, and each id
   gets at most one request.
4. **Pause, then the two calls:**
   - `prefetch_lattes_cache(new_ids, max_workers=retry.workers, stop=stop,
     not_tried=...)`;
   - `refresh_lattes_cache(refresh_ids, max_workers=retry.workers,
     stop=stop)`.

   The same `PortalStop` object is used; its count of failures in a row is
   not reset.
5. **Recovered:**
   - a new id whose file now exists in `cache/` and is a curriculum page;
   - a refresh id in the second call's refreshed list.

   A recovered id gets its manifest date (this run's timestamp, the same as
   the first pass) and leaves `failed`.
6. **Not tried in the second pass:** an id whose request was not sent
   because the stop triggered. It leaves `failed` and joins `not_tried`.
7. **Counts and report:** the manifest is saved once, after both passes.
   Then the code computes `counts = download_counts(plan, failed,
   not_tried)` and, if a second pass ran, adds `retried`, `recovered` and
   `retried_ids`. It then:
   - logs `counts_line("lattes", counts)`;
   - calls `record_access_check_retry` when a second pass ran;
   - calls `record_portal_stop` when the stop triggered in either pass.
8. **Logs:**
   - before the pause: `Retrying N Lattes curricula that got the access
     check page, after M min, with W worker(s): [ids]`;
   - after the second pass: `Second try for the access check page: R of N
     recovered`.

## `download_lattes_flow`

Unchanged. It builds the scriptLattes list from the files in `cache/` after
`rotate_lattes_downloads`, so a recovered curriculum is processed in the
same run.
