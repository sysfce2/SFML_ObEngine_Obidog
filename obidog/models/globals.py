from dataclasses import dataclass

from obidog.models.base import BaseModel
from obidog.models.bindings import Export
from obidog.models.urls import URLs


@dataclass
class GlobalModel(BaseModel):
    name: str
    definition: str
    type: str
    namespace: str = ""
    initializer: str = ""
    location: str = ""
    description: str = ""
    export: Export = Export()
    urls: URLs = URLs()
