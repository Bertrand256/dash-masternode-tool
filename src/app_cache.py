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
import tempfile
import threading
import time
import logging
from typing import Optional

from PyQt5.QtWidgets import QSplitter, QDialog
from PyQt5.QtCore import Qt
from wnd_utils import WndUtils


log = logging.getLogger('dmt.app_cache')


class AppCache(object):
    def __init__(self, app_version: str):
        self.cache_file_name = ''
        self.app_version = app_version
        self.finishing = False
        self.last_data_change_time = 0
        self.save_event = threading.Event()
        self.__data = {}
        self.thread = None
        self.changes_pending = False
        self.data_revision = 0
        self.data_lock = threading.RLock()
        self.save_lock = threading.RLock()

    def set_file_name(self, cache_file_name: str):
        with self.save_lock:
            with self.data_lock:
                if cache_file_name != self.cache_file_name:
                    # Keep setters out until pending data is flushed to the old
                    # file and the state for the new file has been loaded.
                    if self.changes_pending:
                        self.save_data()
                    self.cache_file_name = cache_file_name
                    self.load_data()

    def start(self):
        """ Run saving thread after GUI initializes. """
        if not self.thread:
            self.finishing = False
            self.thread = WndUtils.run_thread(None, self.save_data_thread, ())

    def finish(self):
        self.finishing = True
        self.save_data()
        self.save_event.set()

    def save_data(self):
        tmp_file_name = None
        try:
            # Only one thread can write the cache file at a time. The state lock is
            # deliberately released during disk I/O, so GUI updates are not blocked.
            with self.save_lock:
                with self.data_lock:
                    if not self.changes_pending or not self.cache_file_name:
                        return
                    revision = self.data_revision
                    cache_file_name = self.cache_file_name
                    data = copy.deepcopy(self.__data)
                    data['app_version'] = self.app_version

                cache_dir = os.path.dirname(cache_file_name) or '.'
                fd, tmp_file_name = tempfile.mkstemp(prefix='.dmt_cache_', suffix='.tmp', dir=cache_dir)
                with os.fdopen(fd, 'w') as file_ptr:
                    json.dump(data, file_ptr)
                    file_ptr.flush()
                    os.fsync(file_ptr.fileno())
                os.replace(tmp_file_name, cache_file_name)
                tmp_file_name = None

                with self.data_lock:
                    # A setter may have modified the cache while the snapshot was
                    # being written. In that case leave it pending for the next save.
                    if self.cache_file_name == cache_file_name and self.data_revision == revision:
                        self.__data['app_version'] = self.app_version
                        self.last_data_change_time = 0
                        self.changes_pending = False
        except Exception as e:
            log.error('Error writing cache: ' + str(e))
        finally:
            if tmp_file_name:
                try:
                    os.unlink(tmp_file_name)
                except OSError:
                    pass

    def load_data(self):
        try:
            with self.data_lock:
                cache_file_name = self.cache_file_name
            with open(cache_file_name) as file_ptr:
                j = json.load(file_ptr)
            if isinstance(j, dict):
                with self.data_lock:
                    self.__data = j
                    self.last_data_change_time = 0
                    self.changes_pending = False
                    self.data_revision = 0
        except:
            pass

    def data_changed(self):
        with self.data_lock:
            self.last_data_change_time = time.time()
            self.changes_pending = True
            self.data_revision += 1

    def set_value(self, symbol, value):
        if isinstance(value, (int, float, str, list, tuple, dict)):
            with self.data_lock:
                modified = self.__data.get(symbol, None) != value
                if modified:
                    self.__data[symbol] = copy.deepcopy(value)
                    self.data_changed()
        elif value is not None:
            raise ValueError('Invalid type of value for cache item ' + symbol)

    def get_value(self, symbol, default_value, type):
        with self.data_lock:
            v = self.__data.get(symbol, default_value)
            if isinstance(v, type):
                return copy.deepcopy(v)
            else:
                return default_value

    def save_data_thread(self, ctrl):
        while not self.finishing and not ctrl.finish:
            self.save_event.wait(2)
            if self.save_event.is_set():
                self.save_event.clear()
            with self.data_lock:
                changes_pending = self.changes_pending
            if changes_pending:
                self.save_data()
        self.save_data()
        self.thread = None


cache: Optional[AppCache] = None


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
        log.warning('AppCache not initialized')


def get_value(symbol, default_value, type):
    global cache
    if cache:
        return cache.get_value(symbol, default_value, type)
    else:
        log.warning('AppCache not initialized')

    return None


def save_data(force: bool = False):
    global cache
    if cache:
        if force:
            cache.save_data()
        else:
            cache.data_changed()  # it forces saving data inside a thread
    else:
        log.warning('AppCache not initialized')


def save_window_size(window):
    global cache
    if cache:
        symbol = window.__class__.__name__ + '_'
        cache.set_value(symbol + '_Width', window.size().width())
        cache.set_value(symbol + '_Height', window.size().height())
    else:
        log.warning('AppCache not initialized')


def restore_window_size(window, default_width:Optional[int] = None, default_height:Optional[int] = None):
    global cache
    if cache:
        symbol = window.__class__.__name__ + '_'
        w = cache.get_value(symbol + '_Width', default_width, int)
        h = cache.get_value(symbol + '_Height', default_height, int)
        if w and h:
            window.resize(w, h)
    else:
        log.warning('AppCache not initialized')


def restore_splitter_sizes(window: QDialog, splitter: QSplitter):
    global cache
    if cache:
        symbol = window.__class__.__name__ + '_' + splitter.objectName()
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
        symbol = window.__class__.__name__ + '_' + splitter.objectName()
        cache.set_value(symbol, splitter.sizes())
