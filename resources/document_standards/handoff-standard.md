<!-- Copyright 2026 gsVAM. SPDX-License-Identifier: Apache-2.0.
Added by the elephant-goldfish-model Astra fork (gsVAM), 2026: the standard
for the handoff gate (Stage 10). Not part of google/elephant-goldfish-model. -->

# Handoff Standard

This standard defines the quality bar for a handoff plan: the build units
derived from an approved design (`handoff_plan.md`) and the issue bodies
rendered from them (`handoff_bodies.md`). It is the standard of the Stage 10
gate that `egm-handoff` runs before any GitHub write. The reviewer reads the
plan, the rendered bodies and the design file; the design is the reference,
the plan is the document under review.

## Core Principle

A handoff passes if a builder who has never seen the conversation, given one
issue body and the design range it names, knows what to build, where, what
counts as done, and what must land first, and if the set of issues together
builds exactly the design and nothing else.

## The Seven Questions

Answer each question for the whole plan. A failure is a finding at the unit
(or the pair of units) where it occurs.

1.  **Coverage, both directions.** Every requirement and every Target File of
    the design's `## Detailed Implementation Plan` maps to a unit's scope
    paths or definition of done. No unit carries scope the design does not
    contain. A design requirement that no unit builds is a Blocker; a unit
    that adds scope the design lacks is a Blocker.
2.  **Contradictions between units.** Two units that touch the same file with
    different intent, or a definition-of-done item that a later unit makes
    false (a test that the later unit deletes, a behaviour the later unit
    changes), are a Blocker.
3.  **Blockers and order.** A unit that uses a file or symbol another unit
    creates or changes names that unit in `Blocked by`. A `Blocked by` that
    the design does not require (document order alone) is spurious. Missing
    blockers are Blockers; spurious ones are Majors.
4.  **Shared-file order.** Every path in two units' scope has a shared-file
    chain, and the chain agrees with the blockers and with the design's phase
    order. A chain that contradicts them, or a shared path without one, is a
    Major.
5.  **Testability.** Every definition-of-done item names a command, a CI check
    or an observable fact (a file, symbol or behaviour in backticks) that can
    be checked on the PR head, and none depends on a later unit landing. An
    item that cannot be checked on this unit's PR is a Major.
6.  **Decisions.** Every `Decide before build` item has an owner and a
    default; every `## Open Questions` entry of the design that touches a
    unit appears as one. A missing owner or default is a Major; a design
    question that no unit records is a Major.
7.  **Rendered bodies.** Each rendered body says what its unit says and
    nothing else: same scope, same definition of done, same blockers and
    order, same decisions, with placeholder numbers (`#<U01>`) for blockers
    and unit ids for forward references. A body that drifts from its unit is
    a Blocker; a body that adds text the plan lacks is a Major.

## Severity

As the Astra lane defines it: high (Blocker) means the plan cannot be filed
as written; medium (Major) means it must change before filing; low (Nit) is
optional. A finding that the design itself must change (not the units) is
reported as `fix-design`: the handoff stops and the design returns to
`egm-review` Stage 9 for that range.

## What Is Not a Finding

*   A file a unit will create does not exist yet.
*   A unit's branch or issue number does not exist yet.
*   Wording that a builder can act on, even if it could be shorter.
