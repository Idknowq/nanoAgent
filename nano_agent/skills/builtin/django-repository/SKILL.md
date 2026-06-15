---
name: django-repository
description: Investigate and repair failures in the Django framework repository, including its runtests.py test runner, ORM, migrations, forms, templates, admin, URL routing, and framework state. Activate for django/django tasks or when Django's own test infrastructure and internals determine the solution; do not activate for an ordinary application that merely depends on Django.
compatibility: Python and the repository's supported Django test dependencies may be required.
metadata:
  version: "1.0"
---

# Django Framework Repository Repair

Use this skill together with the Python repository workflow. This skill adds Django-specific
test and framework guidance; it does not replace evidence from the target checkout.

## Confirm Scope

- Confirm this is the Django framework repository by inspecting markers such as `django/`,
  `tests/runtests.py`, and the repository's contributor test documentation.
- For a third-party Django application, follow its own test configuration instead. Do not assume
  Django core's test runner or directory conventions apply.
- Read the issue, failing test, and nearest implementation before surveying an entire subsystem.

## Use Django's Test Runner

- Prefer the repository's documented `tests/runtests.py` workflow over a generic full `pytest`
  invocation. Inspect the checked-out runner or test documentation when command details are
  uncertain because supported options vary across Django versions.
- Run the narrowest available test label first. Typical structured invocations are:

  - `python tests/runtests.py <test_label>`
  - `python tests/runtests.py <module.Class.test_method>`
  - `python tests/runtests.py <test_label> --verbosity 2`

- Use the test module's Django label, not only its filesystem path. Derive the label from nearby
  tests or the runner rather than guessing repeatedly.
- Keep the database backend and settings consistent with repository guidance. Do not treat a
  backend-specific failure as backend-independent without evidence.
- Before using diagnostic options such as parallel control, shuffle, reverse, bisect, or pair,
  confirm they exist in the checked-out runner. Use them only when order dependence, state leakage,
  or suite interaction is a plausible cause.

## Trace Framework Behavior

- Map the failing test to the owning Django subsystem and trace through its public entry point
  before editing helpers. Common boundaries include:

  - ORM: model metadata, fields, expressions, query construction, compiler, backend operations,
    converters, and result materialization.
  - Migrations: project state, autodetector, operations, schema editor, optimizer, and serialization.
  - Requests and responses: URL resolving, middleware, handlers, request parsing, and response
    classes.
  - Forms: field cleaning, widgets, form/model form validation, error handling, and rendering.
  - Templates: lexer/parser, nodes, context, loaders, engines, escaping, and localization.
  - Admin: checks, model admin configuration, changelist behavior, forms, and URL integration.
  - Tests: settings overrides, app registry isolation, database setup, caches, signals, timezone,
    translation, and global framework state.

- Compare sibling implementations and backend feature flags before adding a conditional.
- Preserve lazy evaluation, queryset cloning, deferred work, exception types, ordering guarantees,
  and database portability when they are part of the surrounding contract.
- For ORM changes, inspect generated query behavior or existing query-count assertions when
  relevant. Avoid validating only the final Python value if the regression concerns SQL shape,
  joins, aliases, grouping, ordering, or query count.
- For migrations, distinguish runtime model behavior from historical `ProjectState` behavior.
  Avoid importing current application models where migration state objects are required.

## Repair Constraints

- Add the fix at the abstraction layer that owns the violated behavior. Do not add a backend,
  field, model, or test-name special case unless the contract is genuinely specific to it.
- Reuse existing Django utilities, feature flags, test mixins, and assertion helpers.
- Do not regenerate broad documentation, translations, snapshots, or migration fixtures unless
  the task requires them.
- Do not weaken cross-database coverage, query-count assertions, deprecation behavior, or warning
  checks merely to make one test pass.

## Verify

1. Re-run the exact failing Django test label.
2. Run the containing test class or module.
3. Run closely related subsystem tests, including backend-specific variants when the changed
   behavior crosses database boundaries.
4. Use broader Django test labels only when the change has shared framework impact and runtime
   permits it.
5. Report the exact labels, settings/backend assumptions, and outcomes. State explicitly when a
   full Django suite or additional database backend was not run.
