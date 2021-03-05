#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2021-03

from __future__ import annotations

import functools
import logging
import threading
from typing import Callable, Dict, Optional, List, Tuple, Any

CALL_DEPTH_ATTR_SUFFIX = '.depth'
CALL_COUNTER_ATTR_SUFFIX = '.count'
CALL_LIMIT_ATTR_SUFFIX = '.calllimit'


class _MethodCallTracker:
    """
    Tracks calls to methods within classes. The purpose of this code is to determine whether a given method is
    called first from the outside or whether it is a nested call inside a class or object.
    """
    _local_storage = threading.local()
    _instance = None

    @staticmethod
    def get_instance() -> _MethodCallTracker:
        return _MethodCallTracker._instance

    def __init__(self):
        if _MethodCallTracker._instance is not None:
            raise Exception('Internal error: cannot create another instance of this class')
        _MethodCallTracker._instance = self

    @staticmethod
    def init_stack(stack_name: str) -> List[Dict]:
        stack = getattr(_MethodCallTracker._local_storage, stack_name, None)
        if stack is None:
            stack = []
            _MethodCallTracker._local_storage.__setattr__(stack_name, stack)
        return stack

    @staticmethod
    def push_to_stack(stack_name: str, attributes: Dict):
        stack = _MethodCallTracker.init_stack(stack_name)
        stack.append(attributes)

    @staticmethod
    def pop_from_stack(stack_name: str) -> Optional[Dict]:
        stack: List[Dict] = _MethodCallTracker.init_stack(stack_name)
        if stack:
            return stack.pop()
        return None

    @staticmethod
    def get_class_storage_attr_names(obj: object, suffix: str) -> Tuple[str, str]:
        class_name = obj.__class__.__name__
        object_id = str(id(obj))

        attr_name_for_class = class_name + suffix
        attr_name_for_object = class_name + '.' + object_id + suffix
        return attr_name_for_class, attr_name_for_object

    @staticmethod
    def get_method_storage_attr_names(obj: object, method: Callable, suffix: str) -> Tuple[str, str, str, str]:
        class_name = obj.__class__.__name__
        object_id = str(id(obj))

        attr_name_for_class, attr_name_for_object = _MethodCallTracker.get_class_storage_attr_names(obj, suffix)
        attr_name_for_class_method = class_name + '.' + method.__name__ + suffix
        attr_name_for_object_method = class_name + '.' + object_id + '.' + method.__name__ + suffix
        return attr_name_for_class, attr_name_for_object, attr_name_for_class_method, attr_name_for_object_method

    @staticmethod
    def set_attr(attr_name: str, attr_value: Any):
        _MethodCallTracker._local_storage.__setattr__(attr_name, attr_value)

    @staticmethod
    def get_attr(attr_name: str, default_value: Any) -> Any:
        return getattr(_MethodCallTracker._local_storage, attr_name, default_value)

    @staticmethod
    def incr(attr_name):
        _MethodCallTracker.set_attr(attr_name, _MethodCallTracker.get_attr(attr_name, 0) + 1)

    @staticmethod
    def decr(attr_name):
        v = _MethodCallTracker.get_attr(attr_name, 0)
        if v > 0:
            _MethodCallTracker.set_attr(attr_name, v - 1)
        else:
            logging.warning('_MethodCallTracker: cannot decrease value of ' + attr_name + ' to negative')

    @staticmethod
    def method_call_started(obj: object, method: Callable):
        self = _MethodCallTracker

        # increase the call depth values
        attr_name_for_class, attr_name_for_object, attr_name_for_class_method, attr_name_for_object_method = \
            self.get_method_storage_attr_names(obj, method, CALL_DEPTH_ATTR_SUFFIX)

        self.incr(attr_name_for_class)
        self.incr(attr_name_for_object)
        self.incr(attr_name_for_class_method)
        self.incr(attr_name_for_object_method)

        # increase the call counter values
        attr_name_for_class, attr_name_for_object, attr_name_for_class_method, attr_name_for_object_method = \
            self.get_method_storage_attr_names(obj, method, CALL_COUNTER_ATTR_SUFFIX)

        self.incr(attr_name_for_class)
        self.incr(attr_name_for_object)
        self.incr(attr_name_for_class_method)
        self.incr(attr_name_for_object_method)

    @staticmethod
    def method_call_finished(obj: object, method: Callable):
        self = _MethodCallTracker

        # decrease only the method call depth values
        attr_name_for_class, attr_name_for_object, attr_name_for_class_method, attr_name_for_object_method = \
            self.get_method_storage_attr_names(obj, method, CALL_DEPTH_ATTR_SUFFIX)

        self.decr(attr_name_for_class)
        self.decr(attr_name_for_object)
        self.decr(attr_name_for_class_method)
        self.decr(attr_name_for_object_method)

    @staticmethod
    def get_call_depth_by_class(obj: object):
        attr_name_for_class, _ = _MethodCallTracker.get_class_storage_attr_names(obj, CALL_DEPTH_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_class, 0)

    @staticmethod
    def get_call_depth_by_object(obj: object):
        _, attr_name_for_object = _MethodCallTracker.get_class_storage_attr_names(obj, CALL_DEPTH_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_object, 0)

    @staticmethod
    def get_call_depth_by_class_method(obj: object, method: Callable):
        _, _, attr_name_for_class_method, _ = _MethodCallTracker.get_method_storage_attr_names(obj, method,
                                                                                               CALL_DEPTH_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_class_method, 0)

    @staticmethod
    def get_call_depth_by_object_method(obj: object, method: Callable):
        _, _, _, attr_name_for_object_method = _MethodCallTracker.get_method_storage_attr_names(obj, method,
                                                                                                CALL_DEPTH_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_object_method, 0)

    @staticmethod
    def get_call_count_by_class(obj: object):
        attr_name_for_class, _ = _MethodCallTracker.get_class_storage_attr_names(obj, CALL_COUNTER_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_class, 0)

    @staticmethod
    def get_call_count_by_object(obj: object):
        _, attr_name_for_object = _MethodCallTracker.get_class_storage_attr_names(obj, CALL_COUNTER_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_object, 0)

    @staticmethod
    def get_call_count_by_class_method(obj: object, method: Callable):
        _, _, attr_name_for_class_method, _ = _MethodCallTracker.get_method_storage_attr_names(obj, method,
                                                                                               CALL_COUNTER_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_class_method, 0)

    @staticmethod
    def get_call_count_by_object_method(obj: object, method: Callable):
        _, _, _, attr_name_for_object_method = _MethodCallTracker.get_method_storage_attr_names(obj, method,
                                                                                                CALL_COUNTER_ATTR_SUFFIX)
        return _MethodCallTracker.get_attr(attr_name_for_object_method, 0)

    @staticmethod
    def set_object_method_call_limit(obj: object, method: Callable, call_limit: int):
        self = _MethodCallTracker
        cur_call_count = self.get_call_count_by_object_method(obj, method)
        _, _, _, attr_name_for_object_method = self.get_method_storage_attr_names(obj, method, CALL_LIMIT_ATTR_SUFFIX)
        if call_limit is not None:
            val = cur_call_count + call_limit
        else:
            val = call_limit  # basically, it means disabling the call limit for the given method
        self.set_attr(attr_name_for_object_method, val)

    @staticmethod
    def get_object_method_call_limit(obj: object, method: Callable):
        self = _MethodCallTracker
        _, _, _, attr_name_for_object_method = self.get_method_storage_attr_names(obj, method, CALL_LIMIT_ATTR_SUFFIX)
        return self.get_attr(attr_name_for_object_method, None)

    def __call__(self, obj: object, method: Callable):
        # save obj and method values for the "__enter__" method
        # this should be called just before __enter__
        _MethodCallTracker._local_storage._obj = obj
        _MethodCallTracker._local_storage._method = method
        return self

    def __enter__(self):
        obj = _MethodCallTracker._local_storage._obj
        method = _MethodCallTracker._local_storage._method

        # use stack to pass the object and method values to the __exit__ method
        self.push_to_stack('OBJ_METHOD_STACK', {'obj': obj, 'method': method})
        self.method_call_started(obj, method)
        return self

    def __exit__(self, exc_type, exc_value, tb):
        v = self.pop_from_stack('OBJ_METHOD_STACK',)
        if not v:
            logging.error('No matching call to the __enter__ method.')
        else:
            self.method_call_finished(v['obj'], v['method'])
        if exc_type is not None or exc_value is not None:
            return False
        else:
            return True


MethodCallTracker = _MethodCallTracker()


def method_call_tracker(func):
    """Decorator function to track the execution of a given method and work in tandem with MethodCallLimit to
    implement method call limiting."""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        # if we reached limit set for 'func' calls, suppress call and return None
        call_limit = MethodCallTracker.get_object_method_call_limit(self, func)
        if call_limit is not None:
            cur_call_cont = MethodCallTracker.get_call_count_by_object_method(self, func)
            if cur_call_cont >= call_limit:
                return None

        with MethodCallTracker(self, func):
            ret = func(self, *args, **kwargs)
        return ret
    return wrapper


class MethodCallLimit:
    """
    The purpose of this class is to allow limiting the number of executions of a given method between
    __enter__ and __exit__ (using with clause). Methods being limited this way must use the 'method_call_tracker'
    decorator.
    Example:
        class Test:
            def some_function():
                with CallMethodIfNotCalledInside(self, self.controlled_method, 1):
                    self.method_name()  # will be executed
                    self.method_name()  # execution will be suppressed

            @method_call_tracker
            def controlled_method():
                pass
    """
    def __init__(self, obj: object, method: Callable, call_count_limit: int):
        self.object = obj
        self.method = method
        self.call_count_limit = call_count_limit
        self.old_call_limit = None

    def __enter__(self):
        self.old_call_limit = MethodCallTracker.get_object_method_call_limit(self.object, self.method)
        MethodCallTracker.set_object_method_call_limit(self.object, self.method, self.call_count_limit)
        return self

    def __exit__(self, exc_type, exc_value, exc_tb):
        # restore the old limit
        MethodCallTracker.set_object_method_call_limit(self.object, self.method, self.old_call_limit)
        if exc_type is not None or exc_value is not None:
            return False
        else:
            return True
