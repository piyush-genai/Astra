# How to use this package in Kiro

## 1. Drop it into your project
Unzip this so the `.kiro/` folder sits directly in your project's root directory (alongside where your `/src` folder will live, or an empty folder if you're starting fresh). Kiro looks for `.kiro/steering/` and `.kiro/specs/` at the workspace root automatically.

## 2. Open the folder in Kiro
The four steering files (`product.md`, `tech.md`, `structure.md`, `trading-risk-rules.md`) are set to `inclusion: always`, so they load into every Kiro interaction automatically from the moment you open the workspace — you don't need to reference them manually.

## 3. Start with the `trading-engine-core` spec
In the Kiro panel, open `.kiro/specs/trading-engine-core/`. Kiro's spec workflow is Requirements → Design → Tasks:
- The requirements.md and design.md are already written here — review them, edit anything that doesn't match what you want, then let Kiro proceed to executing tasks.md.
- Tasks are tracked with checkboxes; Kiro updates them in real time as it implements each one. Work through them roughly in order, since later tasks (Execution Engine, integration test) depend on earlier ones (BaseStrategy, PositionManager).

## 4. Then open `pivot-cpr-strategy`
This spec depends on the interface built in step 3, but its indicator/formula tasks (tasks 1–5) can be built and unit-tested independently, in parallel if you prefer.

**Before task 6 in this spec, you need to fill in two things directly in `requirements.md`:**
- The exact entry trigger condition from your source video (candle close beyond a zone? rejection wick? something else?)
- The session filter (does it trade all day, or only specific windows?)

Kiro is deliberately instructed (via design.md) not to guess at these — it will treat task 6 as blocked until you specify them. This is intentional: an invented trigger would produce backtest numbers that don't mean anything.

## 5. Everyday use after setup
- Use **Vibe sessions** (just chatting in the Kiro pane) for small fixes or questions once the specs are built out — you don't need to go through the full spec workflow for every change.
- Reserve **Spec sessions** for anything that adds a new strategy, changes the engine's risk logic, or changes how positions/orders are handled — exactly the kind of change where getting the design wrong is expensive.
- Consider adding a **hook** later that runs your test suite automatically before any commit touching `src/engine/` — this is optional, added after the core is stable, not a day-one requirement.

## Files in this package
```
.kiro/
  steering/
    product.md              # what this system is and why (always loaded)
    tech.md                 # stack, broker adapter pattern, config-not-constants rule
    structure.md             # folder layout, naming, import rules
    trading-risk-rules.md    # non-negotiable safety rules (naked options, circuit breaker, etc.)
  specs/
    trading-engine-core/     # the shared engine — build this first
      requirements.md
      design.md
      tasks.md
    pivot-cpr-strategy/       # your first strategy plug-in
      requirements.md
      design.md
      tasks.md
```
