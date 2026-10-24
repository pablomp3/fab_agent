"""Bounded external tools used by the copilot.

The only current tool is an optional Tavily web search. It is never part of
the verdict: the Python gate owns the claim, status, citations, and action.
"""
