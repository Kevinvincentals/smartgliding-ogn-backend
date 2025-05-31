#!/usr/bin/env python3
"""
Models for the FLARM WebSocket Server
"""

import json
from datetime import datetime


class DateTimeEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle datetime objects
    """
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(DateTimeEncoder, self).default(obj)


def serialize_for_json(obj):
    """
    Convert any non-serializable objects to JSON-compatible format
    """
    if isinstance(obj, datetime):
        return obj.isoformat()
    elif hasattr(obj, '_id') and hasattr(obj['_id'], '__str__'):
        obj_copy = obj.copy()
        obj_copy['_id'] = str(obj_copy['_id'])
        return obj_copy
    return obj
