#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04

"""
Handles caching different data from application forms.   
"""
import copy
import json
import threading
import time
from PyQt5.QtWidgets import QSplitter, QDialog
from PyQt5.QtCore import Qt
from wnd_utils import WndUtils


class AppCache(object):
    def __init__(self, app_version: str):
        self.cache_file_name = ''
        self.app_version = app_version
        self.finishing = False
        self.last_data_change_time = 0
        self.save_event = threading.Event()
        self.__data = {}
        self.thread = None

    def set_file_name(self, cache_file_name: str):
        if cache_file_name != self.cache_file_name:
            if self.last_data_change_time > 0:
                self.save_data()
            self.cache_file_name = cache_file_name
            self.load_data()

    def start(self):
        """ Run saving thread after GUI initializes. """
        if not self.thread:
            self.thread = WndUtils.run_thread(None, self.save_data_thread, ())

    def finish(self):
        self.finishing = True
        self.save_event.set()

    def save_data(self):
        try:
            self.__data['app_version'] = self.app_version
            json.dump(self.__data, open(self.cache_file_name, 'w'))
            self.last_data_change_time = 0
        except Exception as e:
            log('Error writing cache: ' + str(e))

    def load_data(self):
        try:
            j = json.load(open(self.cache_file_name))
            if j:
                self.__data = j
        except:
            pass

    def data_changed(self):
        self.last_data_change_time = time.time()

    def set_value(self, symbol, value):
        if isinstance(value, (int, float, str, list, tuple)):
            modified = self.__data.get(symbol, None) != value
            if modified:
                self.__data[symbol] = copy.deepcopy(value)
                self.data_changed()
        else:
            raise ValueError('Invalid type of value for cache item ' + symbol)

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
        self.thread = None


cache = None


def log(info):
    print(info)


def init(cache_file_name, app_version):
    global cache
    if not cache:
        cache = AppCache(app_version)
    cache.set_file_name(cache_file_name)
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


def save_window_size(window):
    global cache
    if cache:
        symbol = window.__class__.__name__ + '_'
        cache.set_value(symbol + '_Width', window.size().width())
        cache.set_value(symbol + '_Height', window.size().height())
    else:
        log('AppCache not initialized')


def restore_window_size(window):
    global cache
    if cache:
        symbol = window.__class__.__name__ + '_'
        w = cache.get_value(symbol + '_Width', None, int)
        h = cache.get_value(symbol + '_Height', None, int)
        if w and h:
            window.resize(w, h)
    else:
        log('AppCache not initialized')

def restore_splitter_sizes(window: QDialog, splitter: QSplitter):
    global cache
    if cache:
        symbol = window.__class__.__name__  + '_' + splitter.objectName()
        sizes = cache.get_value(symbol, None, list)
        if not isinstance(sizes, list) or len(sizes) != 2:
            sizes = [100, 100]
            if splitter.parent():
                if splitter.orientation() == Qt.Vertical:
                    sizes[0], sizes[1] = round(splitter.parent().height() / 2), round(splitter.parent().height() / 2)
                else:
                    sizes[0], sizes[1] = round(splitter.parent().width() / 2), round(splitter.parent().width() / 2)
        splitter.setSizes(sizes)

def save_splitter_sizes(window: QDialog, splitter: QSplitter):
    global cache
    if cache:
        symbol = window.__class__.__name__  + '_' + splitter.objectName()
        cache.set_value(symbol, splitter.sizes())

