"""Receiver service: our own API that ingests carrier webhooks and stores them safely.

Layers (each one only talks to the one below it):

    api.py         HTTP routes (FastAPI), nothing but request/response plumbing
    service.py     the ingestion use case: decode -> translate status -> store
    repository.py  every SQL statement lives here
    db.py          connections, transactions and schema migrations
"""
