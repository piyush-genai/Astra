"""
ASTRA Risk Plane — deterministic position sizing and drawdown control.

Per AGENTS.md section 6, nothing in this package may be driven by ML output, LLM
reasoning, or research-agent recommendation. Every function here is a pure, total
function of explicit inputs so that a given capital state always yields the same
lot count.
"""
