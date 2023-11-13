#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-10

import logging
import threading
import time
import traceback
from typing import Dict, Tuple, Optional, List

SAVE_CALL_STACK = True


class LockCaller:
    def __init__(self, thread, calling_filename, calling_line_number, call_stack):
        self.thread = thread
        self.file_name = calling_filename
        self.line_number = calling_line_number
        self.call_stack: List[traceback.FrameSummary] = call_stack
        self.time = time.time()


def clean_call_stack(stack):
    """ Clean traceback call stack from entries related to the debugger used in the development. """
    call_stack = []
    for s in stack:
        if s.filename.find('PyCharm') < 0:
            call_stack.append(s)
    return call_stack


class EnhRLock:
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

    def __enter__(self):
        self.acquire()

    def __exit__(self, type, value, traceback):
        self.release()

    def acquire(self):
        stack = traceback.extract_stack()
        if len(stack) >= 2 + self.stackinfo_skip_lines:
            calling_filename, calling_line_number, _, _ = stack[-2 - self.stackinfo_skip_lines]
        else:
            calling_filename, calling_line_number = '', ''

        thread = threading.currentThread()

        if SAVE_CALL_STACK:  # used in diagnostics
            call_stack = clean_call_stack(stack)
        else:
            call_stack = []

        waiter = LockCaller(thread, calling_filename, calling_line_number, call_stack)
        self.waiters.append(waiter)
        self.__lock.acquire()

        self.depth += 1
        self.waiters.remove(waiter)
        del waiter

        self.blocker = LockCaller(thread, calling_filename, calling_line_number, call_stack)

    def release(self):
        if self.blocker is not None and self.blocker.thread != threading.currentThread():
            raise Exception('Cannot release not owned lock')
        self.depth -= 1
        if self.depth == 0:
            self.blocker = None
        self.__lock.release()

    def is_thread_waiting_for_me(self, checked_thread):
        my_thread = threading.currentThread()
        threading.main_thread()

    @staticmethod
    def detect_deadlock(checked_thread) -> Optional[Tuple[LockCaller, LockCaller]]:
        """
        :param checked_thread:
        :return: Tuple[LockCaller (waiter), LockCaller (locker)]
        """
        EnhRLock.int_lock.acquire()
        try:
            for lock in EnhRLock.lock_list:
                for waiter in lock.waiters:
                    if waiter.thread == checked_thread and \
                       lock.blocker is not None and lock.blocker.thread == threading.currentThread():
                        return waiter, lock.blocker
            return None
        finally:
            EnhRLock.int_lock.release()
