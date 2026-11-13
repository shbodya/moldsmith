# SPDX-License-Identifier: GPL-3.0-or-later
"""Moldsmith: two-part silicone mold generator."""

from . import operators, panels, properties

_modules = (properties, operators, panels)


def register():
    for module in _modules:
        module.register()


def unregister():
    for module in reversed(_modules):
        module.unregister()
