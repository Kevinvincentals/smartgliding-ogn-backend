#!/usr/bin/env python3
"""
Models for the FLARM WebSocket Server
"""

import json
from datetime import datetime
from typing import Optional


class DateTimeEncoder(json.JSONEncoder):
    """
    Custom JSON encoder to handle datetime objects
    """
    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super(DateTimeEncoder, self).default(obj)


class DkAirfield:
    """
    Data model for Danish airfields
    """
    def __init__(self, ident: str, type: str, name: str, icao: str, 
                 latitude_deg: float, longitude_deg: float, 
                 municipality: Optional[str] = None):
        self.ident = ident
        self.type = type
        self.name = name
        self.municipality = municipality
        self.icao = icao
        self.latitude_deg = latitude_deg
        self.longitude_deg = longitude_deg
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
    
    def to_dict(self):
        """Convert to dictionary for MongoDB storage"""
        return {
            "ident": self.ident,
            "type": self.type,
            "name": self.name,
            "municipality": self.municipality,
            "icao": self.icao,
            "latitude_deg": self.latitude_deg,
            "longitude_deg": self.longitude_deg,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at
        }
    
    @classmethod
    def from_dict(cls, data: dict):
        """Create instance from dictionary"""
        instance = cls(
            ident=data.get("ident"),
            type=data.get("type"),
            name=data.get("name"),
            icao=data.get("icao"),
            latitude_deg=float(data.get("latitude_deg", 0)),
            longitude_deg=float(data.get("longitude_deg", 0)),
            municipality=data.get("municipality")
        )
        if "createdAt" in data:
            instance.created_at = data["createdAt"]
        if "updatedAt" in data:
            instance.updated_at = data["updatedAt"]
        return instance


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
