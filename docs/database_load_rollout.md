# Notification database load fix and staged rollout

This change is prepared in code. Production deployment, worker provisioning, and
live configuration changes are separate operational steps. Do not activate the
dedicated queue until its consumers are running.

## Changes and compatibility

- WA Chat Hub adds a non-unique BTREE index on
  `Chat Message(provider_event_id, direction, modified)`. The migration and fresh
  installation hook reuse an equivalent full-column index. A conflicting name,
  unavailable fields, metadata-lock timeout, or unsupported online DDL fails
  visibly; the code never retries with blocking DDL.
- Patient Notification Hub can route sends to a configured dedicated queue via
  the optional `patient_notification_queue` site setting. Without this setting,
  the existing `short` queue, 90-second timeout, stable job ID, and deduplication
  remain in use. Automatic recovery and manual retries use the same enqueue
  function. Existing jobs remain in their original queue.
- Delivery evidence checks, atomic claims, retry delays, attempt history, and
  the handling of `Outcome Unknown` are preserved.
- Vobiz Desk activity calls allow one outstanding request per tab. Completion,
  failure, and synchronous exceptions release the guard. The 60-second heartbeat,
  75-second presence expiry, and server attendance updates are unchanged. This
  guard is not a site-wide request limit and does not coordinate separate tabs.
- A read-only `notification_load_snapshot` command reports site backlog, lookup
  plans, and server-wide counters. It does not send messages or schedule jobs.
  It does not install a monitoring service or send alerts.

## Stage 1: baseline and access

1. Record the deployed revisions of the three apps. These repositories were
   prepared against WA Chat Hub `e61d586`, Patient Notification Hub `97f21bd`,
   and Vobiz Click to Call `fbf476c` on `develop`.
2. Verify backup availability, restore procedure, disk space (including index
   build temporary space), long transactions, database CPU/I/O, and normal
   request latency. The application API alone cannot verify all host conditions.
3. Capture existing indexes, connection counters, and notification queue age.
   Use the same metrics before and after, at comparable traffic levels. Existing
   slow-query logs are necessary for historical query attribution.
4. Release reviewed changes using the hosting deployment process. Avoid rolling
   out unrelated commits as part of the index fix. No restarts, mass retries,
   purges, or background-job cancellations are part of this procedure.

## Stage 2: index

The existing-site patch is:

```text
wa_chat_hub.patches.v1_1.add_notification_event_index
```

It will run through the normal Frappe migration process. If operators choose to
install the targeted index ahead of the broader migration, after releasing the
helper code they can use a dedicated bench process:

```sh
bench --site SITE execute wa_chat_hub.maintenance.notification_indexes.ensure_notification_event_index
```

Replace `SITE` with the actual hosted Frappe site name, not an assumed hostname.
Run during quieter traffic. This command commits before DDL; do not invoke it
inside a business transaction. It sets session `lock_wait_timeout` to five
seconds, uses `ALGORITHM=INPLACE, LOCK=NONE`, and restores the prior setting.
The five seconds limit metadata-lock waiting, not total index-build duration.
Online DDL still uses CPU, I/O, temporary disk space, and brief metadata locks.

If the lock wait expires, diagnose the blocking transaction and retry later.
Do not kill active business transactions or remove the online-DDL restrictions
as an automatic recovery action. If a client connection drops, inspect the
database process and index state before starting another build.

An already applied equivalent index is a no-op, so the later versioned patch
can complete safely. The non-unique index does not change message content or
business uniqueness constraints.

## Stage 3: verify the primary fix

```sh
bench --site SITE execute patient_notification_hub.diagnostics.notification_load_snapshot
```

- Confirm the event lookup uses the new index with selective access rather
  than the former scan of `modified`. The command runs EXPLAIN, not the data
  lookup itself. Test a small set of actual matching and missing event IDs
  separately after the plan is correct.
- Compare query latency, active queries, connections, request latency, and host
  CPU. Do not interpret an optimizer row estimate as measured rows examined.
- `Slow_queries`, connection-error totals, and maximum used connections are
  server-wide values since startup. Compare counter deltas and uptime; a restart
  resets them. They may include other sites sharing the database server.
- Backlog values are site-specific. Failed and uncertain records require
  different handling from eligible queued work; never bulk reset them to Queued.
- Snapshot warnings identify a scan or connection usage at 80% of capacity.
  They are operator signals, not evidence of a measured CPU cause. Add CPU,
  backlog-age, and query-duration alerts in the hosting monitoring system after
  establishing normal operating levels. Sample at a modest interval such as
  five minutes rather than polling full-table backlog aggregates per browser.

## Stage 4: optional dedicated notification workers

Proceed only if post-index measurements still show excessive send concurrency
or competition with interactive work.

1. Register a custom queue, for example `patient_notifications`, in the bench's
   Frappe worker configuration using the hosting platform's supported process.
2. Provision a small worker allocation for that queue; 2–4 workers is a test
   starting point, not a validated production sizing. Verify actual consumer
   count and a harmless test job before enabling routing. A registered queue
   name alone does not prove that a worker is listening.
3. Audit all consumers: generic workers must not also consume the custom queue
   if its worker allocation is intended to cap notification concurrency. Queues
   are bench-scoped; account for other sites using the same queue.
4. Set the site's `patient_notification_queue` to `patient_notifications` through
   the managed configuration process. The code rejects unregistered names.
5. Let existing `short`-queue jobs finish. During the transition, old send jobs
   and dedicated workers can overlap. The intended concurrency limit applies
   after the old send backlog drains.
6. Keep the existing recovery switches and attempt history. Tune recovery batch
   size against oldest pending age and throughput; reducing 50 to 5 arbitrarily
   can make notifications late. Recovery batch size is not a worker limit.

No new dispatch table, recovery scheduler, semaphore lease, or forced worker
termination is introduced by this code change.

## Stage 5: Vobiz and capacity review

Release the small activity-request guard using the normal asset build process.
Already open browsers need the new asset before the guard takes effect. Test
route changes and success/failure completion, and confirm visibility, Away,
unmapped-user and attendance behaviour.

Do not lengthen the heartbeat interval beyond the presence lifetime. Mapping
cache changes and heartbeat backoff are intentionally deferred until profiling
demonstrates a need and invalidation/attendance tests are specified.

Size database connections and total web/background concurrency together after
the index fix. Include headroom for interactive traffic, administration, and
other sites. This change does not increase `max_connections` or CPU limits.

## Acceptance and rollback

Observe two representative peak business periods after deployment. Require:
fast event lookups, no recurring connection-limit failures, bounded notification
backlog, no duplicate deliveries, and unchanged call/attendance behaviour. Review
historical slow-query data for remaining assignment or other expensive queries.

- If a UI regression occurs, revert the Vobiz guard and rebuild its asset.
- If queue isolation causes excessive delays, restore new-job routing to `short`
  while keeping dedicated consumers alive until their queue drains. Do not
  delete/re-enqueue every job: stable IDs intentionally prevent duplicates.
- The index is additive and compatible with prior application versions. Retain
  it during application rollback. Dropping it is a separate reviewed database
  action, not an automatic rollback step.

## Local validation

The targeted migration tests cover repeat execution, equivalent indexes,
prefix/ignored indexes, conflicting definitions, missing schema, timeout cleanup,
and failure without blocking fallback. Existing notification worker/recovery
tests verify evidence reconciliation and uncertain-delivery handling. Additional
tests cover optional queue selection, preserved job identity, diagnostics and
Vobiz request concurrency.

A local MariaDB integration check changed EXPLAIN from `type=index,key=modified`
to `type=ref,key=idx_chat_message_event_direction_modified`. A second execution
returned `already_present`; the session lock timeout was restored. This verifies
the migration and query plan on the local fixture, not production CPU improvement.
