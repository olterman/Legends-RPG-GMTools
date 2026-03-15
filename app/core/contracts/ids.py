from __future__ import annotations

import uuid


def new_record_id() -> str:
    return f"rec_{uuid.uuid4().hex}"
