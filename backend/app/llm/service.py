"""The single model boundary for E-AUDIT Phase 2.

Four features, one class:
  1. narrate            -> prose  (streamed internally, returned whole + verdict)
  2. next_best_action   -> structured (schema-validated)
  3. summarise_history  -> structured (schema-validated, figure-free)
  4. stream_report      -> prose  (STREAMED as SSE)

Division of labour (NON-NEGOTIABLE): recon_engine.reconcile_case computes EVERY
number. The model writes LANGUAGE ONLY and emits figures ONLY as placeholder tokens
({{difference}}, {{step.OUT-07}}, ...). verify_claims/verify_conclusion validate the
output against the recon dict BEFORE anything is shown; render_placeholders then
substitutes the engine's exact values.

PDPL: the DEMO calls a hosted model on SYNTHETIC data only, and only when
settings.data_is_synthetic is True. PRODUCTION swaps the model behind THIS interface
by changing settings.llm_model (an EAUDIT_LLM_MODEL env var) and, for an in-tenant
deployment, settings.llm_base_url — zero call-site change either way. Nothing outside
`provider.py` imports `litellm`; this module never sees a provider name or an SDK object.

Every `"source": "claude"` literal below is intentionally left as-is regardless of which
provider is actually configured — the frontend (VerifyBadge.tsx, Casework.tsx,
TaxpayerResponsePanel.tsx, ai.ts) hardcodes `source === "claude"` to key its "verified by AI"
badge, and renaming this string would silently break that badge without any frontend code
changing. It is a legacy success-tag label, not a provider identifier.
"""
from __future__ import annotations

import os

from typing import Iterator

from ..config import settings
from . import provider
from .schemas import NextBestAction, TaxpayerSummary, LetterExtraction, CalcQuerySpec
from .prompts import (
    FROZEN_PREAMBLE, build_context, build_history_context,
    NARRATE_INSTR, NBA_INSTR, SUMMARY_INSTR, REPORT_INSTR,
    LETTER_SYSTEM, LETTER_INSTR, build_letter_context, fence_letter,
    DRAFT_LETTER_SYSTEM, DRAFT_REQUEST_INSTR, DRAFT_FOLLOWUP_INSTR,
    DRAFT_VERDICT_INSTR, fence_facts,
    CALC_SYSTEM, CALC_INSTR, build_calc_context, fence_calc,
)
from .verify import (
    verify_claims, verify_conclusion, verify_correspondence, render_placeholders, StreamGuard,
    fb_narration, fb_nba, fb_summary, fb_report,
)

_ALIAS = "Taxpayer A"          # PDPL pseudonym sent to a hosted model (F7)


# ---------------------------------------------------------------- availability
def availability() -> tuple[bool, str]:
    """Returns (enabled, reason). reason is machine-readable for the UI badge (F11)."""
    if settings.llm_disabled or os.getenv("EAUDIT_LLM_DISABLED") == "1":
        return False, "disabled"
    if not provider.has_credentials():
        return False, "no-credentials"
    if not settings.data_is_synthetic and provider.is_public_endpoint() and not settings.allow_hosted_egress:
        return False, "pdpl-blocked"
    return True, "claude"


# ------------------------------------------------------------- message assembly
def _system_blocks() -> list:
    return [{"type": "text", "text": FROZEN_PREAMBLE, "cache_control": {"type": "ephemeral"}}]


def _user_blocks(context: str, instr: str, ask: str) -> list:
    # F6: ALL untrusted case data lives here, in the user turn — never system.
    return [
        {"type": "text", "text": context, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": instr},
        {"type": "text", "text": ask},
    ]


def _src(reason: str) -> str:
    return {"no-credentials": "deterministic-fallback", "disabled": "deterministic-fallback",
            "pdpl-blocked": "pdpl-fallback"}.get(reason, reason)


def _guard(text: str, recon: dict) -> dict:
    """verify_claims AND verify_conclusion — a wrong verdict is as fatal as a wrong figure (F1)."""
    v = verify_claims(text, recon)
    concl = verify_conclusion(text, recon)
    if concl:
        return {"ok": False, "violations": v["violations"] + concl}
    return v


def _render_nba(nba: NextBestAction, recon: dict) -> dict:
    d = nba.model_dump()
    for k in ("expected_yield", "document_requested", "rationale"):
        d[k] = render_placeholders(d[k], recon)
    return d


def _sse_token(text: str) -> str:
    return "event: token\ndata: " + text.replace("\n", "\ndata: ") + "\n\n"


def _sse(name: str, payload: str) -> str:
    return f"event: {name}\ndata: {payload}\n\n"


# =============================================================================
class LLMService:

    # ------------------------------------------------- FEATURE 1: BRIDGE NARRATION
    def _prose(self, ctx: str, instr: str, ask: str, max_tokens: int) -> tuple[str, str | None]:
        return provider.stream_text(
            system_blocks=_system_blocks(),
            user_content=_user_blocks(ctx, instr, ask),
            max_tokens=max_tokens,
        )

    def narrate(self, recon: dict, rules: list) -> dict:
        enabled, reason = availability()
        if not enabled:
            return {"text": fb_narration(recon), "source": _src(reason), "verified": True,
                    "mode": "fallback", "violations": []}
        ctx, unmask = build_context(recon, rules, alias=_ALIAS)
        raw, err = self._prose(ctx, NARRATE_INSTR, "Produce the narration now.", 700)
        if err:
            return {"text": fb_narration(recon), "source": err, "verified": False,
                    "mode": "fallback", "violations": [err]}
        v = _guard(raw, recon)
        if not v["ok"]:
            corr = ("Produce the narration now. Your earlier draft was REJECTED for: "
                    + "; ".join(v["violations"])
                    + ". Rewrite with NO digit and NO scale/comparison word (never 'twice', 'half', "
                    "'double', 'quarter', 'a third', 'thousand', 'million'); reference every figure "
                    "ONLY as an allowed placeholder token.")
            raw2, err2 = self._prose(ctx, NARRATE_INSTR, corr, 700)
            if not err2 and _guard(raw2, recon)["ok"]:
                return {"text": unmask(render_placeholders(raw2, recon)),
                        "source": "claude", "verified": True, "mode": "live", "violations": []}
            return {"text": fb_narration(recon), "source": "blocked-unverified",
                    "verified": False, "mode": "fallback", "violations": v["violations"]}
        return {"text": unmask(render_placeholders(raw, recon)),
                "source": "claude", "verified": True, "mode": "live", "violations": []}

    # ------------------------------------------------- FEATURE 2: NEXT-BEST-ACTION
    def next_best_action(self, recon: dict, rules: list) -> dict:
        immaterial = recon["state"] == "supported" or abs(recon["unexplained"]) <= recon["materiality"]

        enabled, reason = availability()
        if not enabled:
            return {**_render_nba(fb_nba(recon), recon), "source": _src(reason),
                    "verified": True, "violations": []}
        ctx, _unmask = build_context(recon, rules, alias=_ALIAS)
        nba, err = provider.parse_structured(
            system_blocks=_system_blocks(),
            user_content=_user_blocks(ctx, NBA_INSTR, "Decide the next best action now."),
            max_tokens=800, output_model=NextBestAction,
        )
        if err:
            return {**_render_nba(fb_nba(recon), recon), "source": err,
                    "verified": False, "violations": [err]}

        if immaterial and nba.action_type != "no-action":       # engine override (F2)
            out = _render_nba(fb_nba(recon), recon)
            out.update(source="engine-override", verified=True, violations=[])
            return out

        probe = " ".join([nba.document_requested, nba.rationale, nba.expected_yield])
        v = _guard(probe, recon)
        if not v["ok"]:
            return {**_render_nba(fb_nba(recon), recon), "source": "blocked-unverified",
                    "verified": False, "violations": v["violations"]}
        return {**_render_nba(nba, recon), "source": "claude", "verified": True, "violations": []}

    # ---------------------------------------------- FEATURE 3: TAXPAYER-HISTORY SUMMARY
    def summarise_history(self, profile: dict, prior_returns: list, prior_cases: list) -> dict:
        enabled, reason = availability()
        if not enabled:
            return {**fb_summary(profile, prior_returns, prior_cases), "source": _src(reason),
                    "verified": True, "violations": []}
        ctx = build_history_context(profile, prior_returns, prior_cases, alias=_ALIAS)
        s, err = provider.parse_structured(
            system_blocks=_system_blocks(),
            user_content=[{"type": "text", "text": ctx, "cache_control": {"type": "ephemeral"}},
                          {"type": "text", "text": SUMMARY_INSTR},
                          {"type": "text", "text": "Write the taxpayer brief now."}],
            max_tokens=900, output_model=TaxpayerSummary,
        )
        if err:
            return {**fb_summary(profile, prior_returns, prior_cases), "source": err,
                    "verified": False, "violations": [err]}

        probe = " ".join([s.headline, s.prior_pattern, *s.points, *s.risk_flags])
        v = verify_claims(probe, recon=None, figure_free=True)   # reject ANY numeric literal
        if not v["ok"]:
            return {**fb_summary(profile, prior_returns, prior_cases), "source": "blocked-unverified",
                    "verified": False, "violations": v["violations"]}
        out = s.model_dump()
        real = profile.get("name") or ""
        if real:                                                 # restore the real name for display
            out["headline"] = out["headline"].replace(_ALIAS, real)
            out["prior_pattern"] = out["prior_pattern"].replace(_ALIAS, real)
            out["points"] = [p.replace(_ALIAS, real) for p in out["points"]]
            out["risk_flags"] = [f.replace(_ALIAS, real) for f in out["risk_flags"]]
        return {**out, "source": "claude", "verified": True, "violations": []}

    # ------------------------------------------------- FEATURE 4: AI-DRAFTED REPORT
    def stream_report(self, recon: dict, rules: list) -> Iterator[str]:
        """Yields SSE frames. Verified + placeholder-substituted per segment BEFORE it
        leaves the server (StreamGuard). Every terminal branch emits `fallback` then `done`."""
        enabled, reason = availability()
        if not enabled:
            yield _sse_token(fb_report(recon))
            yield _sse("done", _src(reason))
            return

        ctx, unmask = build_context(recon, rules, alias=_ALIAS)
        raw, err = self._prose(ctx, REPORT_INSTR, "Draft the report now.", 2200)
        if not err:
            v = _guard(raw, recon)
            if not v["ok"]:
                corr = ("Draft the report now. Your earlier draft was REJECTED for: "
                        + "; ".join(v["violations"][:6])
                        + ". Rewrite keeping EXACTLY the four sections, with NO digit and NO scale/"
                        "comparison word (never 'twice', 'half', 'double', 'a third', 'thousand', "
                        "'million'); reference every figure ONLY as an allowed placeholder token.")
                raw2, err2 = self._prose(ctx, REPORT_INSTR, corr, 2200)
                if not err2 and _guard(raw2, recon)["ok"]:
                    raw = raw2
                else:
                    err = "blocked-unverified"
        if err:
            yield _sse("fallback", "")
            yield _sse_token(fb_report(recon))
            yield _sse("done", err if err in ("blocked-refusal", "api-error") else "blocked-unverified")
            return
        # verified — substitute the engine's figures, then stream line-by-line for the typing effect
        text = unmask(render_placeholders(raw, recon))
        for line in text.split("\n"):
            yield _sse_token(line + "\n")
        yield _sse("done", "claude")

    # ------------------------------------------------- FEATURE 5: TAXPAYER-LETTER READER
    def read_letter(self, recon: dict, letter_text: str) -> dict:
        """Read a taxpayer letter / case note and extract its claimed explanation as a DRAFT.

        Unlike the other features, this returns the SAR figure the letter itself states — it is a
        suggestion the auditor confirms (and may edit) before it is committed as a response.
        """
        fallback = {
            "explains_gap": False, "category": "none",
            "summary": "Automated reading is unavailable — review the letter and enter the amount by hand.",
            "quote": "", "proposed_amount": 0.0, "confidence": "low",
            "caveat": "Enter and confirm the amount manually from the letter.",
        }
        text = (letter_text or "").strip()
        if not text:
            return {**fallback, "summary": "Paste a taxpayer letter or case note to analyse.",
                    "source": "deterministic-fallback"}
        enabled, reason = availability()
        if not enabled:
            return {**fallback, "source": _src(reason)}
        ext, err = provider.parse_structured(
            system_blocks=[{"type": "text", "text": LETTER_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            user_content=[
                {"type": "text", "text": build_letter_context(recon)},
                {"type": "text", "text": LETTER_INSTR},
                {"type": "text", "text": fence_letter(text[:6000])},
            ],
            max_tokens=900, output_model=LetterExtraction,
        )
        if err:
            return {**fallback, "source": err}
        out = ext.model_dump()
        out["proposed_amount"] = round(abs(float(out.get("proposed_amount") or 0.0)), 2)  # auditor confirms
        return {**out, "source": "claude"}

    # ------------------------------------------------- FEATURE 6: OUTBOUND CORRESPONDENCE
    def draft_letter(self, *, kind: str, facts: str, fallback) -> dict:
        """Draft an information request or a follow-up from engine-established facts.

        The placeholder model does not fit a letter that quotes documents rather than
        reconciliation scalars, so the guard is `verify_correspondence`: every numeric literal
        in the draft must already appear in the facts block. Same rule, stated for prose —
        Claude may repeat a figure it was handed, and may not introduce one.

        `fallback` is a callable producing the deterministic letter, which is complete and
        sendable English. Degrading to it costs polish, never correctness.
        """
        instr = {"follow-up": DRAFT_FOLLOWUP_INSTR,
                 "verdict": DRAFT_VERDICT_INSTR}.get(kind, DRAFT_REQUEST_INSTR)
        enabled, reason = availability()
        if not enabled:
            return {"text": fallback(), "source": _src(reason), "verified": True,
                    "mode": "fallback", "violations": []}

        def _write(ask: str) -> tuple[str, str | None]:
            return provider.stream_text(
                system_blocks=[{"type": "text", "text": DRAFT_LETTER_SYSTEM,
                                "cache_control": {"type": "ephemeral"}}],
                user_content=[
                    {"type": "text", "text": fence_facts(facts)},
                    {"type": "text", "text": instr},
                    {"type": "text", "text": ask},
                ],
                max_tokens=1400,
            )

        raw, err = _write("Draft the letter now.")
        if err:
            return {"text": fallback(), "source": err, "verified": False,
                    "mode": "fallback", "violations": [err]}
        v = verify_correspondence(raw, facts)
        if not v["ok"]:
            corr = ("Draft the letter now. Your earlier draft was REJECTED for: "
                    + "; ".join(v["violations"])
                    + ". Rewrite using ONLY figures that appear verbatim in the FACTS block, and "
                      "no scale or comparison words.")
            raw2, err2 = _write(corr)
            if not err2 and verify_correspondence(raw2, facts)["ok"]:
                return {"text": raw2.strip(), "source": "claude", "verified": True,
                        "mode": "live", "violations": []}
            return {"text": fallback(), "source": "blocked-unverified", "verified": False,
                    "mode": "fallback", "violations": v["violations"]}
        return {"text": raw.strip(), "source": "claude", "verified": True,
                "mode": "live", "violations": []}

    # ------------------------------------------------------- FEATURE 7: CALCULATION PARSER
    def parse_calculation(self, description: str, docs: list[dict]) -> dict:
        """Translate the auditor's stated method into an executable query. No arithmetic.

        Returns the query as a plain dict for `agents.calculation.query_from_dict`, which
        re-validates it against the closed algebra — so a model that strays outside the schema
        is caught twice: once by the structured output, once by the executor.

        With no credentials this returns `checkable: False`, and the caller falls back to the
        auditor picking the operation and column by hand. That path is not a degraded guess —
        it is the same query, specified by a person instead of parsed from a sentence.
        """
        fallback = {"op": "", "column": "", "filters": [], "document": "",
                    "understood": "Automated reading is unavailable — choose the operation and "
                                  "column to check against.",
                    "checkable": False}
        text = (description or "").strip()
        if not text:
            return {**fallback, "understood": "Describe how the figure was calculated.",
                    "source": "deterministic-fallback"}
        enabled, reason = availability()
        if not enabled:
            return {**fallback, "source": _src(reason)}
        spec, err = provider.parse_structured(
            system_blocks=[{"type": "text", "text": CALC_SYSTEM, "cache_control": {"type": "ephemeral"}}],
            user_content=[
                {"type": "text", "text": build_calc_context(docs)},
                {"type": "text", "text": CALC_INSTR},
                {"type": "text", "text": fence_calc(text[:2000])},
            ],
            max_tokens=800, output_model=CalcQuerySpec,
        )
        if err:
            return {**fallback, "source": err}

        out = spec.model_dump()
        # The parser is a translator. Any digit in `understood` means it started answering the
        # question instead of restating the method, so the sentence is not shown.
        if any(ch.isdigit() for ch in out.get("understood", "")):
            out["understood"] = "Method parsed — check the query below before relying on it."
        return {**out, "source": "claude"}


llm = LLMService()  # module singleton
