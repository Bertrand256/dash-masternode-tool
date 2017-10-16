#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-10

import logging
import threading
import traceback


class EnhRLock():
    lock_list = []
    int_lock = threading.Lock()

    def __init__(self, stackinfo_skip_lines=0):
        self.__lock = threading.RLock()
        self.waiters = []
        self.blocker = None
        self.depth = 0
        self.stackinfo_skip_lines = stackinfo_skip_lines
        try:
            self.int_lock.acquire()
            self.lock_list.append(self)
        finally:
            self.int_lock.release()

    def __del__(self):
        try:
            self.int_lock.acquire()
            self.lock_list.remove(self)
        finally:
            self.int_lock.release()

    def acquire(self):
        stack = traceback.extract_stack()
        if len(stack) >= 2 + self.stackinfo_skip_lines:
            calling_filename, calling_line_number, _, _ = stack[-2 - self.stackinfo_skip_lines]
        else:
            calling_filename, calling_line_number = '', ''

        thread = threading.currentThread()
        waiter = {
            'thread': thread,
            'file_name': calling_filename,
            'line_number': calling_line_number
        }
        self.waiters.append(waiter)
        self.__lock.acquire()
        self.depth += 1
        self.waiters.remove(waiter)
        self.blocker = {
            'thread': thread,
            'file_name': calling_filename,
            'line_number': calling_line_number
        }

    def release(self):
        if self.blocker is not None and self.blocker['thread'] != threading.currentThread():
            raise Exception('Cannot release not owned lock')
        self.depth -= 1
        if self.depth == 0:
            self.blocker = None
        self.__lock.release()

    def is_thread_waiting_for_me(self, checked_thread):
        my_thread = threading.currentThread()
        threading.main_thread()

    @staticmethod
    def detect_deadlock(checked_thread):
        EnhRLock.int_lock.acquire()
        try:
            for lock in EnhRLock.lock_list:
                for waiter in lock.waiters:
                    if waiter['thread'] == checked_thread and \
                       lock.blocker is not None and lock.blocker['thread'] == threading.currentThread():
                        return waiter['file_name'], waiter['line_number'], \
                               lock.blocker['file_name'], lock.blocker['line_number']
            return None
        finally:
            EnhRLock.int_lock.release()
