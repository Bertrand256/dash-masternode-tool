#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

"""
Handles caching different data from application forms.   
"""
import copy
import json
import os
import threading


class AppCache(object):
    def __init__(self, cache_dir):
        self.cache_file = os.path.join(cache_dir, 'dmt_cache.json')
        self.__data = {}
        self.load_data()

    def save_data(self):
        try:
            json.dump(self.__data, open(self.cache_file, 'w'))
        except Exception as e:
            log('Error writing cache: ' + str(e))

    def load_data(self):
        try:
            j = json.load(open(self.cache_file))
            if j:
                self.__data = j
        except:
            pass

    def data_changed(self):
        # TODO: save asynchronously
        self.save_data()

    def set_value(self, symbol, value):
        modified = self.__data.get(symbol, None) != value
        if modified:
            self.__data[symbol] = copy.deepcopy(value)
            self.data_changed()

    def get_value(self, symbol, default_value, type):
        v = self.__data.get(symbol, default_value)
        if isinstance(v, type):
            return v
        else:
            return default_value


cache = None


def log(info):
    print(info)


def init(cache_dir):
    global cache
    if not cache:
        cache = AppCache(cache_dir)


def set_value(symbol, value):
    global cache
    if cache:
        cache.set_value(symbol, value)
    else:
        log('AppCache not initialized')


def get_value(symbol, default_value, type):
    global cache
    if cache:
        return cache.get_value(symbol, default_value, type)
    else:
        log('AppCache not initialized')

    return None
