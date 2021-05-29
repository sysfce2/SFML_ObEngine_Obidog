from dataclasses import dataclass, field
from typing import List

from obidog.models.base import BaseModel


@dataclass
class ObidogFlagsModel(BaseModel):
    bind_to: str = ""
    helpers: List[str] = field(default_factory=lambda: [])
    template_hints: List[str] = field(default_factory=lambda: [])
    abstract: bool = False
    nobind: bool = False
    additional_includes: List[str] = field(default_factory=lambda: [])
    as_property: bool = False
    copy_parent_items: bool = False
    proxy: bool = False
    noconstructor: bool = False

    def combine(self, flags: "ObidogFlagsModel"):
        self.bind_to = self.bind_to or flags.bind_to
        self.helpers += flags.helpers
        self.template_hints += flags.template_hints
        self.abstract = self.abstract or flags.abstract
        self.nobind = self.nobind or flags.nobind
        self.additional_includes += flags.additional_includes
        self.as_property = self.as_property or flags.as_property
        self.copy_parent_items = self.copy_parent_items or flags.copy_parent_items
        self.proxy = self.proxy or flags.proxy
        self.noconstructor = self.noconstructor or flags.noconstructor
