#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-07

class AttrsProtected(object):
    """
    Class for protecting of attribute definition to only inside of a constructor.
    """
    def __init__(self):
        self.__allow_attr_definition = True

    def set_attr_protection(self):
        """
        Method to be called at the end of child class constructor. It enables attribute
        defition protection - each attempt of creating attribute after this call will
        end up with an error.
        """
        self.__allow_attr_definition = False

    def __setattr__(self, name, value):
        if name == '_AttrsProtected__allow_attr_definition' or self.__allow_attr_definition or hasattr(self, name):
            super().__setattr__(name, value)
        else:
            raise AttributeError('Attribute definition protection for class "%s". Attribute name: "%s"' % (self.__class__.__name__, name))


class CancelException(Exception):
    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args, *kwargs)

