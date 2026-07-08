"""Content engine: topic backlog + research-gated script generation.

Pipeline: seed_topics.yaml + LLM suggestions -> topics(backlog) -> research_gate
(>=3 sources, reject Low depth) -> script_generator (Claude, pattern-rotated) ->
output/<video_id>/script.json + script.txt, videos.state=scripted.
"""
