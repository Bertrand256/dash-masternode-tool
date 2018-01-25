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

import time

from wnd_utils import WndUtils


class AppCache(object):
    def __init__(self, cache_dir, app_version):
        self.cache_file = os.path.join(cache_dir, 'dmt_cache.json')
        self.app_version = app_version
        self.finishing = False
        self.last_data_change_time = 0
        self.save_event = threading.Event()
        self.__data = {}
        self.load_data()

    def start(self):
        """ Run saving thread after GUI initializes. """
        WndUtils.runInThread(self.save_data_thread, ())

    def finish(self):
        self.finishing = True
        self.save_event.set()

    def save_data(self):
        try:
            self.__data['app_version'] = self.app_version
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
        self.last_data_change_time = time.time()

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

    def save_data_thread(self, ctrl):
        last_save_date = 0
        while not self.finishing:
            self.save_event.wait(2)
            if self.save_event.is_set():
                self.save_event.clear()
            if self.last_data_change_time > 0 and last_save_date < self.last_data_change_time:
                self.save_data()
                last_save_date = time.time()


cache = None


def log(info):
    print(info)


def init(cache_dir, app_version):
    global cache
    if not cache:
        cache = AppCache(cache_dir, app_version)


def start():
    global cache
    if cache:
        cache.start()


def finish():
    global cache
    if cache:
        cache.finish()


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


def save_data():
    global cache
    if cache:
        cache.data_changed()  # it forces saving data inside a thread
    else:
        log('AppCache not initialized')


