"""Local web control panel + JSON API for the operator pipeline.

The panel is a thin adapter over existing logic: it reads the DB to render state and
enqueues jobs for the scheduler to run (heavy work), or calls the transport-agnostic
decision core directly (light review actions). No business logic lives here.
"""
