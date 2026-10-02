We are now ready to IMPLEMENT the refactor.

Before making any changes, read these three completed analysis documents:

- `prompts/098-refactor_analysis.answer.md`
  Initial audit of the existing Expiry Tracker repository, including the current architecture, reusable components, tests, constraints, and the staged migration/refactor plan.

- `prompts/099-tri_repo_analysis.answer.md`
  Second architectural pass defining the final three-repository architecture, the exact Core / Expiry / Catalog boundaries, dependency graph, test ownership, packaging strategy, privacy boundary, and multi-repository development model.

- `prompts/100-logger_timeit.answer.md`
  Follow-up correction specifically revisiting logging and timing. This document amends the logging/timing conclusions of `099-tri_repo_analysis.answer.md`.

Treat these three `.answer.md` files as the design basis for the implementation.

The corresponding `.md` files without `.answer` are the original prompts that produced the analyses. They may be consulted for context, but the `.answer.md` files contain the conclusions to implement.

Where the documents overlap:

- use `098-refactor_analysis.answer.md` as the source of truth for the audit of the existing code and the staged migration mechanics;
- use `099-tri_repo_analysis.answer.md` as the source of truth for the final tri-repository architecture and ownership boundaries;
- use `100-logger_timeit.answer.md` as the source of truth for logging and timing, overriding the relevant conclusions in `099-tri_repo_analysis.answer.md`.

If you discover a genuine contradiction outside those explicitly described relationships, inspect the current code and choose the smallest implementation consistent with the final tri-repository architecture. Document the decision in the final report.

This is no longer an analysis task.

You may create, move, modify, and delete files, initialize the new local Git repositories, update dependencies, run commands, build packages, and execute tests as necessary.

## Existing workspace

The VS Code workspace already contains exactly these three project roots:

- `my-canal-expiry-tracker`
  - existing Git repository;
  - intended to remain public;
  - contains the current working application.

- `mycanal-hodor-core`
  - existing EMPTY directory;
  - target for the new shared public Core package.

- `my-canal-catalog`
  - existing EMPTY directory;
  - target for the private Catalog application.

These are the final project locations.

Use these existing directories in place.

DO NOT:
- create alternative project directories;
- move these project roots;
- create a parent Git repository;
- create a global uv workspace joining the three projects;
- configure any Git remote;
- push anything;
- publish anything to PyPI or elsewhere.

You may run `git init` inside the two new directories if and only if they are not already Git repositories.

Each repository must remain an independent Python project with its own `pyproject.toml`, environment, dependency resolution, tests, and lock file where appropriate.

## Target architecture

Implement the final architecture defined in `099-tri_repo_analysis.answer.md`:

                    mycanal-hodor-core
                         PUBLIC
                       /        \
                      /          \
                     v            v
          my-canal-expiry-    my-canal-catalog
             tracker              PRIVATE
             PUBLIC

There must be NO dependency between Expiry Tracker and Catalog.

Both applications may depend on Core.

Core must never depend on either application.

## Core boundary

`mycanal-hodor-core` must contain only genuinely shared protocol/domain primitives.

Follow the exact ownership decisions in `099-tri_repo_analysis.answer.md`, with the logging/timing correction from `100-logger_timeit.answer.md`.

This includes, where supported by the existing code and analyses:

- Hodor HTTP transport;
- session handling;
- pacing;
- retries;
- Retry-After handling;
- common URL security validation;
- technical HTTP/parsing errors;
- generic HTTP JSON decoding;
- detailV5 URL transformation / shared detail handling;
- availability representation parsing;
- shared timestamp parsing/validation;
- shared subgenre and duration extraction;
- season and episode models;
- season catalog parsing;
- shared episode-navigation interpretation;
- structured season selectors and existing legacy fallback parsing;
- shared logging primitives;
- shared `timeit()` instrumentation;
- the reusable console renderer if appropriate according to `100-logger_timeit.answer.md`.

Core MUST NOT automatically configure global logging merely because it is imported.

Applications choose and initialize their logging configuration explicitly.

The shared timing implementation should retain its current semantics unless required by the refactor:

- synchronous functions;
- inclusive timing;
- original exception propagation;
- logging failure must not break the wrapped operation.

Core may depend on `requests`, `structlog`, and the standard library as established by the analyses.

Do not introduce application-specific dependencies into Core.

## Expiry Tracker boundary

`my-canal-expiry-tracker` remains responsible for application-specific and personal state, including:

- playlist acquisition;
- cURL parsing / RequestContext;
- playlist validation and pagination policy;
- `PlaylistItem`;
- personal progression/resume state;
- resume fallback;
- backlog calculations;
- completion logic;
- expiration groups;
- report-specific statuses;
- Paris/report date semantics;
- French presentation strings;
- JSON cache and TTL policy;
- cache compatibility;
- `ContentResult`;
- `process_items()`;
- DataFrame/Excel generation;
- formulas and formatting;
- CLI;
- application logging configuration;
- application-specific timing placement;
- raw playlist publication/archive behavior;
- current rate-limit tooling where application-specific.

Preserve current Expiry Tracker behavior as closely as possible.

In particular, do not silently change:

- playlist semantics;
- resume/completion behavior;
- expiration calculations presented to the user;
- cache behavior or compatibility;
- Excel output semantics;
- request counts/caching behavior relied upon by tests.

Temporary compatibility facades are allowed during migration, but they must delegate to Core rather than retain duplicate implementations.

Do not leave permanent duplicated implementations of shared primitives in Expiry.

## Catalog boundary

`my-canal-catalog` is PRIVATE.

It owns all exhaustive catalog knowledge and crawling behavior.

Keep exclusively in Catalog:

- catalog source definitions;
- real catalog IDs/seeds/topology;
- editorial collection parsing;
- `contentGrid`;
- `strateContent`;
- page/strate traversal;
- editorial pagination;
- discovery rules;
- link-following rules;
- exhaustive traversal;
- global deduplication;
- multiple catalog memberships;
- crawl completeness logic;
- crawl resume/state;
- SQLite persistence;
- catalog-specific metadata/storage;
- autonomous `actionLayout` discovery if Expiry does not require it;
- investigation captures/results;
- exhaustive provider/catalog mapping.

Do NOT move this logic into Core merely because it talks to Hodor.

Core should provide the shared protocol primitives Catalog needs, while Catalog owns the private knowledge of what to crawl and how to crawl it.

Never publish or copy real exhaustive catalog mappings into either public repository.

## Migration strategy

Use the staged migration mechanics identified in `098-refactor_analysis.answer.md` together with the final repository ownership decisions from `099-tri_repo_analysis.answer.md`.

Treat migration stages as INTERNAL CHECKPOINTS.

They are NOT separate user interactions.

DO NOT stop and ask me for approval after each stage.

Work autonomously through the complete refactor.

The expected progression is roughly:

1. Isolate the reusable/shared primitives from the existing Expiry Tracker while preserving compatibility and existing behavior.
2. Initialize and populate the existing `mycanal-hodor-core` directory.
3. Move shared transport behavior and the appropriate tests/fixtures to Core.
4. Switch Expiry Tracker to the real Core implementation.
5. Move the shared parsers/models and their appropriate tests/fixtures to Core.
6. Move/refactor logging and timing according to `100-logger_timeit.answer.md`.
7. Remove replaced local implementations while preserving temporary compatibility facades only where they provide useful migration compatibility.
8. Initialize and populate the existing private `my-canal-catalog` directory.
9. Implement the Catalog-side architecture using Core, without importing Expiry.
10. Prepare the Python package layouts and project metadata for future independent distribution.
11. Validate the resulting repositories independently and together.

Do not mechanically follow this list if the code requires a slightly different safe ordering.

The important constraints are:

- preserve behavior continuously;
- maintain test coverage;
- keep ownership boundaries correct;
- avoid long-lived duplicated implementations;
- do not expose private Catalog knowledge.

Do not stop between checkpoints if tests and evidence allow you to continue safely.

## Testing requirements

Run relevant tests continuously during the migration.

Preserve the existing offline-test guarantees.

Tests that exercise shared protocol behavior should move to Core where appropriate.

Tests that exercise personal/report/application behavior remain in Expiry.

Catalog should test its private collection parsing, traversal, deduplication, memberships, SQLite transactions, crawl state, and completeness independently.

Consumers should exercise the REAL local Core implementation rather than mocking every extracted Core parser.

Explicitly preserve/test important boundaries identified by the analyses, including:

- Core error -> Expiry report status mapping;
- detail parsing -> existing cache values;
- cache TTL behavior;
- playlist/resume precedence;
- second cached run causing zero requests where currently expected;
- Excel formulas and numeric duration behavior;
- season parsing/navigation behavior;
- ordinary tests making no real Hodor calls.

Do not weaken tests merely to make the refactor pass.

If a test exposes an actual regression, fix the implementation rather than rewriting the expected behavior unless one of the completed analyses explicitly requires that behavior to change.

Move shared fixtures with their shared tests where appropriate.

Keep personal/acquisition fixtures in Expiry.

Keep Catalog fixtures private and preferably synthetic/minimal where possible.

## Local multi-repository development

Do NOT create a uv workspace spanning all repositories.

The projects remain independently resolvable.

During development, use the local Core checkout when testing consumers.

An invocation such as:

    uv run --with-editable ../mycanal-hodor-core pytest

is appropriate where useful.

A local `[tool.uv.sources]` override may be used if genuinely necessary during extended development, but do not accidentally make a sibling filesystem path a required dependency of a distributable public artifact.

The final project metadata should anticipate a normal versioned dependency on `mycanal-hodor-core` once it is eventually published.

DO NOT publish it now.

Where practical, also validate that distributable artifacts do not accidentally depend on local source overrides.

## Packaging preparation

Prepare sensible package namespaces rather than relying permanently on the current generic `src` import layout.

Target naming from `099-tri_repo_analysis.answer.md`:

- Core package: `mycanal_hodor_core`
- Expiry package: `mycanal_expiry_tracker`

Choose an appropriate private package name for Catalog consistent with the repository name.

Expiry's existing root `main.py` may remain temporarily as a compatibility launcher if useful.

Prepare the structure for a future CLI entry point, but preserve the current invocation behavior during the migration where practical.

Pay special attention to the existing coupling between code location and:

- `input`;
- `cache`;
- `output`.

Installed packages must not assume writable application data lives next to the installed Python package.

Separate code location from application data/work directory in a minimal, explicit way.

Do not package:

- credentials;
- captured authenticated requests;
- personal playlist data;
- cache data;
- generated workbooks;
- private databases;
- private catalog mappings.

Inspect built artifacts if you create them.

## Logging and timing

For this section, `prompts/100-logger_timeit.answer.md` is authoritative.

The previous conclusion that `log.py` and `timeit()` should remain entirely inside Expiry Tracker has been superseded.

The intended design is:

- shared logger access / structured logging primitives in Core;
- shared `timeit()` in Core;
- reusable console rendering may live in Core;
- importing Core MUST NOT configure the global logging process;
- Expiry and Catalog explicitly choose/configure their logging at application startup;
- Core logging must remain usable with a different application-selected processor chain/output;
- application-specific logging policy remains in the application.

Do not simply copy the existing logging implementation unchanged if doing so preserves import-time global configuration.

Separate primitive logging access/rendering from application configuration as described in `100-logger_timeit.answer.md`.

## Licensing / public-private boundary

The existing Expiry Tracker is MIT licensed.

Prepare Core consistently with the technical licensing findings from `099-tri_repo_analysis.answer.md`.

Preserve applicable notices and do not blindly copy code with unclear provenance.

Do not automatically assign a public/open-source license to the private Catalog repository.

Do not treat this task as a legal analysis; follow the technical audit already performed.

## Git

You may initialize Git in the two new project directories if needed.

Do not:

- configure remotes;
- push;
- rewrite remote history;
- publish releases;
- publish packages.

Keep changes reviewable.

You may create local commits if doing so materially helps maintain safe migration checkpoints, but do not push them.

If you create commits, keep them logically scoped and report them at the end.

Do not commit credentials, personal data, generated caches, SQLite catalog data, investigation captures, or other private runtime artifacts into public repositories.

## Autonomy

Do not interrupt me for routine implementation choices.

If a minor decision is not explicitly covered by the completed analyses, choose the smallest solution consistent with their architecture and document that decision in the final report.

Continue autonomously through test failures when they are understandable and safely fixable.

STOP and ask me only if you encounter an ambiguity that could:

- expose private Catalog logic/data in a public repository;
- require credentials I have not provided;
- require a remote/network publication action;
- irreversibly migrate or delete user data;
- break cache/data compatibility in a way that cannot safely be resolved from the existing code/tests;
- require an architectural reversal contradicting the completed analyses.

Otherwise: investigate, implement, test, and continue.

## Scope discipline

This is a refactor and architecture extraction, not an excuse for unrelated redesign.

Prefer the smallest changes that achieve the validated architecture.

Do not invent:

- plugin frameworks;
- generalized Hodor SDK abstractions that have no current consumer;
- asynchronous networking;
- new persistence layers in Core;
- speculative schemas;
- unnecessary compatibility layers.

In particular, Core must remain narrow.

A primitive belongs in Core because both applications genuinely need it, not merely because it might be useful someday.

## Completion criteria

Do not consider the task complete merely because files have been moved.

At completion:

1. The three existing workspace roots are independent projects/repositories.
2. Core contains one authoritative implementation of the shared primitives.
3. Expiry uses Core and retains its existing application behavior.
4. Catalog uses Core but does not depend on Expiry.
5. Expiry does not depend on Catalog.
6. Private crawling/catalog knowledge has not leaked into the public repositories.
7. Logging/timing follow `100-logger_timeit.answer.md`.
8. Tests are appropriately split and passing.
9. Ordinary tests remain offline.
10. Packaging structure is compatible with future independent distribution.
11. No remote has been modified and nothing has been published.

## Final validation

Before declaring success:

- inspect the final state of all three repositories;
- run the appropriate complete test suites;
- inspect dependency declarations;
- inspect Git status;
- verify the public/private boundary;
- verify that Core import does not configure logging globally;
- verify that Expiry is actually executing the Core implementation rather than a duplicated compatibility copy;
- verify that Catalog does not import Expiry;
- verify that no sibling filesystem path is accidentally required by a distributable public artifact.

Do not rely only on intermediate successful test runs.

## Final report

When finished, give me a concise but complete implementation report containing:

- final architecture of the three repositories;
- important files/modules moved or created;
- compatibility facades retained and why;
- dependency graph;
- logging/timing implementation;
- packaging/data-directory decisions;
- tests executed in EACH repository and their results;
- any tests not executed and why;
- any architectural decisions you had to make beyond the completed analyses;
- any remaining TODOs before Core/Expiry could be published to PyPI;
- any remaining TODOs before Catalog crawling can begin;
- `git status` for all three repositories;
- local commits created, if any;
- confirmation that no push/publication/remote modification occurred.

You have the completed analyses, the existing three-root workspace, and permission to perform the local refactor.

Proceed autonomously through the complete implementation.