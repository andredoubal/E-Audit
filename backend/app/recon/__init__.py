"""Stage 1 — what the numbers say, and nothing beyond that.

A reconciliation in this package answers one question: **do these two sources agree, and if
not, by how much and why.** It does not decide whether a difference is a mistake, and it may
not use the words that would imply it had. That separation is the specification's central
demand and it is enforced here rather than asked for in a prompt: the status vocabulary is
closed (`status.py`), and "violation", "non-compliant" and "invalid" are not in it.

Which comparisons run on a case is derived from the evidence profiles rather than listed
(`registry.py` + `planner.py`), so a case with a general ledger gets ledger comparisons and a
case without one is told which document would unlock them. A test that silently does not run
looks identical to a test that ran and found nothing, which is why "not possible, and here is
what is missing" is a published result.
"""
