#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-07

from typing import List, Optional
from common import AttrsProtected


class TableModelColumn(AttrsProtected):
    def __init__(self, name, caption, visible, additional_attrs: Optional[List[str]] = None):
        AttrsProtected.__init__(self)
        self.name = name
        self.caption = caption
        self.visible = visible
        if additional_attrs:
            for attr in additional_attrs:
                self.add_attribute(attr)
        self.def_width = None
        self.set_attr_protection()

