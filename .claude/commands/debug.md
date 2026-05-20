---
description: Test-driven debugging loop — environment probe, failing test, capped iteration, regression guard, post-mortem
argument-hint: <description of the bug>
---

# Test-Driven Debugging Loop

A bug has been reported:

> $ARGUMENTS

Follow these steps **in order**. Do not skip. Do not edit any source file before Step 2 has produced a failing test.

---

## Step 0 — Environment probe (ALWAYS run first)

Before touching anything, probe the capabilities this fix is likely to need. Run a single batched shell command that checks:

- **TTY**: `test -t 0 && echo "tty=yes" || echo "tty=no"`
- **Passwordless sudo**: `sudo -n true 2>/dev/null && echo "sudo=yes" || echo "sudo=no"`
- **Node / npx**: `command -v node npx || echo "node=missing"`
- **npm cache writable** (the chown incident — npm EACCES on a root-owned cache): `npm config get cache` then probe writability of that dir, e.g. `touch "$(npm config get cache)/.probe" 2>/dev/null && echo "npmcache=writable" || echo "npmcache=readonly"`
- **Python / venv**: `command -v python3` and whether the project venv exists and has the project deps
- **Network egress**: `curl -sI -m 5 https://pypi.org >/dev/null 2>&1 && echo "net=yes" || echo "net=no"`
- Any other capability specific to *this* bug (DB reachable, env vars present, a service running, etc.)

**Decision rule:** if a capability the fix genuinely requires is missing, **STOP**. Do not attempt the fix and do not fail silently. Instead write/append `MANUAL_STEPS.md` at the repo root containing:

1. What capability is missing and how the probe detected it
2. The exact command(s) the user must run to fix it (e.g. `sudo chown -R $(id -u):$(id -g) ~/.npm`)
3. What to do after — re-run `/debug` with the same bug description

Then report to the user that you've emitted `MANUAL_STEPS.md` and are blocked. Do not proceed.

If all required capabilities are present, state "environment probe: clear" and continue.

---

## Step 1 — Reproduce with a failing test

Write a test that **fails because of the bug** — before editing any source file.

- Backend (Python): add to `backend/tests/` — pytest, mirror the style in `test_agents.py` / `test_api.py`.
- Frontend (TS/React): co-locate or use the project's test runner; if none exists, set one up minimally rather than skipping.
- The test must assert the *correct* behavior, so it fails now and passes once fixed.
- Run it and **paste the failure output**. If it does not fail, you have not reproduced the bug — keep going until it does. A fix without a reproducing test is not allowed.

Name the test so its intent is obvious, e.g. `test_<area>_<symptom>_regression`.

---

## Step 2 — Iteration loop (hard cap: 10 iterations)

Loop: **edit → run the failing test → read the actual output → adjust.**

- Change the smallest thing that could plausibly move the test.
- Re-run *only* the failing test each iteration (fast feedback).
- Read the real output every time — never assume.
- Count iterations out loud ("iteration 3/10").
- **If you hit 10 iterations without green: STOP and escalate.** Write a short note in your reply: what you tried, what each attempt's output was, your current best hypothesis, and what you need from the user. Do not silently keep going.

---

## Step 3 — Lock it in (regression guard)

Once the reproducing test passes:

- Keep the test **permanently** in the suite (`backend/tests/` etc.) — it is now the guard for this bug.
- Run the **full suite** (`cd backend && python -m pytest tests/ -v`, plus `python -m benchmarks` if backend logic changed, plus `npx tsc --noEmit` for frontend changes).
- If anything else broke, that is collateral damage from your fix — fix it before continuing. Green-everywhere or you are not done.

---

## Step 4 — Post-mortem

Finish with a short post-mortem (5–8 lines):

- **Root cause:** the actual underlying reason, not the symptom.
- **Fix:** what changed and why that addresses the root cause.
- **Guard:** which test now fails if this regresses, by name.
- **Blast radius:** anything else touched or worth watching.

Then, if the user asks for a commit, commit with a message that references the root cause and the guarding test.
