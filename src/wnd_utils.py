#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-03
import logging
import os
import threading
import traceback

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, QObject
from PyQt5.QtGui import QPalette, QPainter, QBrush, QColor, QPen, QIcon, QPixmap
from PyQt5.QtWidgets import QMessageBox, QWidget
import math
from thread_fun_dlg import ThreadFunDlg, WorkerThread
import app_cache as app_cache


class WndUtils():

    def __init__(self, app_path=''):
        self.app_path = app_path
        pass

    @staticmethod
    def displayMessage(type, message):
        msg = QMessageBox()
        msg.setIcon(type)
        msg.setText(message)
        return msg.exec_()

    @staticmethod
    def errorMsg(message):
        if threading.current_thread() != threading.main_thread():
            return WndUtils.callFunInTheMainThread(WndUtils.displayMessage, QMessageBox.Critical, message)
        else:
            return WndUtils.displayMessage(QMessageBox.Critical, message)

    @staticmethod
    def warnMsg(message):
        if threading.current_thread() != threading.main_thread():
            return WndUtils.callFunInTheMainThread(WndUtils.displayMessage, QMessageBox.Warning, message)
        else:
            return WndUtils.displayMessage(QMessageBox.Warning, message)

    @staticmethod
    def infoMsg(message):
        if threading.current_thread() != threading.main_thread():
            return WndUtils.callFunInTheMainThread(WndUtils.displayMessage, QMessageBox.Information, message)
        else:
            return WndUtils.displayMessage(QMessageBox.Information, message)

    @staticmethod
    def queryDlg(message, buttons=QMessageBox.Ok | QMessageBox.Cancel, default_button=QMessageBox.Ok,
            icon=QMessageBox.Information):

        def dlg(message, buttons, default_button, icon):
            msg = QMessageBox()
            msg.setIcon(icon)
            msg.setText(message)
            msg.setStandardButtons(buttons)
            msg.setDefaultButton(default_button)
            return msg.exec_()

        if threading.current_thread() != threading.main_thread():
            return WndUtils.callFunInTheMainThread(dlg, message, buttons, default_button, icon)
        else:
            return dlg(message, buttons, default_button, icon)

    def centerByWindow(self, parent):
        """
        Centers this window by window given by attribute 'center_by_window'
        :param center_by_window: Reference to (parent) window by wich this window will be centered.
        :return: None
        """
        self.move(parent.frameGeometry().topLeft() + parent.rect().center() - self.rect().center())

    @staticmethod
    def threadFunctionDialog(worker_fun, worker_fun_args, close_after_finish=True, buttons=None, title='',
                             text=None, center_by_window=None):
        """
        Executes worker_fun function inside a thread. Function provides a dialog for UI feedback (messages 
        and/or progressbar).
        :param worker_fun: user's method/function to be executed inside a thread 
        :param worker_fun_args:  argumets passed to worker_fun
        :param close_after_finish: True, if a dialog is to be closed after finishing worker_fun
        :param buttons: list of dialog button definitions; look at doc od whd_thread_fun.Ui_ThreadFunDialog class
        :return: value returned from worker_fun
        """
        ui = ThreadFunDlg(worker_fun, worker_fun_args, close_after_finish,
                          buttons=buttons, title=title, text=text, center_by_window=center_by_window)
        ui.exec_()
        ret = ui.getResult()
        ret_exception = ui.worker_exception
        del ui
        if ret_exception:
            # if there was an exception in the worker function, pass it to the caller
            raise ret_exception
        return ret

    @staticmethod
    def runInThread(worker_fun, worker_fun_args, on_thread_finish=None, on_thread_exception=None):
        """
        Run a function inside a thread.
        :param worker_fun: reference to function to be executed inside a thread
        :param worker_fun_args: arguments passed to a thread function
        :param on_thread_finish: function to be called after thread finishes its execution
        :return: reference to a thread object
        """
        thread = None

        def on_thread_finished_int(on_thread_finish_ext, nr):
            if thread.worker_exception:
                raise thread.worker_exception
            if on_thread_finish_ext:
                on_thread_finish_ext()

        if threading.current_thread() != threading.main_thread():
            # starting thread from another thread causes an issue of not passing arguments'
            # values to on_thread_finished_int function, so on_thread_finish is not called
            st = traceback.format_stack()
            logging.error('Running thread from inside another thread. Stack: \n' + ''.join(st))

        logging.debug('runInThread')
        thread = WorkerThread(worker_fun=worker_fun, worker_fun_args=worker_fun_args)
        thread.finished.connect(lambda: on_thread_finished_int(on_thread_finish, 22))
        thread.start()
        return thread

    @staticmethod
    def callFunInTheMainThread(fun_to_call, *args):
        return thread_wnd_utils.callFunInTheMainThread(fun_to_call, *args)

    def setIcon(self, widget, ico):
        if isinstance(ico, str):
            icon = QIcon()
            icon.addPixmap(QPixmap(os.path.join(self.app_path, "img/" + ico)))
        else:
            icon = self.style().standardIcon(ico)
        widget.setIcon(icon)

    def set_cache_value(self, name, value):
        app_cache.set_value(self.__class__.__name__ + '_' + name, value)

    def get_cache_value(self, name, default_value, type):
        return app_cache.get_value(self.__class__.__name__ + '_' + name, default_value, type)


class ThreadWndUtils(QObject):
    """
    Helps in calling functions interacting with GUI, executed from threads other than the main app's thread.
    """

    # signal for calling specified function in the main thread
    fun_call_signal = QtCore.pyqtSignal(object, object, object)

    def __init__(self):
        QObject.__init__(self)
        self.fun_call_signal.connect(self.funCallSignalled)
        self.mutex = QtCore.QMutex()
        self.fun_call_ret_value = None
        self.fun_call_exception = None

    def funCallSignalled(self, wait_condition, fun_to_call, args):
        """
        Function-event executed in the main thread as a result of emiting signal fun_call_signal from BG threads.
        :param wait_condition: QtCore.QWaitCondition - calling thread waits on this object until function  
        :param fun_to_call: ref to a function which is to be called
        :param args: args passed to the function fun_to_call
        :return: return value from fun_to_call
        """
        try:
            self.fun_call_ret_value = fun_to_call(*args)
        except Exception as e:
            print('ThreadWndUtils.funCallSignal error: %s' % str(e))
            self.fun_call_exception = e
        finally:
            wait_condition.wakeAll()

    def callFunInTheMainThread(self, fun_to_call, *args):
        """
        This method is called from BG threads. Its purpose is to run 'fun_to_call' from main thread (used for dialogs)
        and return values ruturned from it.
        :param fun_to_call: ref to a function which is to be called
        :param args: args passed to the function fun_to_call
        :return: return value from fun_to_call
        """
        exception_to_rethrow = None
        ret = None
        try:
            if threading.current_thread() != threading.main_thread():
                waitCondition = QtCore.QWaitCondition()
                self.mutex.lock()
                try:
                    self.fun_call_exception = None
                    self.fun_call_ret_value = None

                    # emit signal to call the function fun in the main thread
                    self.fun_call_signal.emit(waitCondition, fun_to_call, args)

                    # wait for the function to finish
                    waitCondition.wait(self.mutex)
                    ret = self.fun_call_ret_value
                finally:
                    self.mutex.unlock()
                if self.fun_call_exception:
                    # if there was an exception in the fun, pass it to the calling code
                    exception_to_rethrow = self.fun_call_exception
            else:
                return fun_to_call(*args)
        except Exception as e:
            print('ThreadWndUtils.callFunInTheMainThread error: %s' % str(e))
            raise

        if exception_to_rethrow:
            raise exception_to_rethrow
        return ret


thread_wnd_utils = ThreadWndUtils()


class WaitWidget(QWidget):
    def __init__(self, parent=None):

        QWidget.__init__(self, parent)
        palette = QPalette(self.palette())
        palette.setColor(palette.Background, Qt.transparent)
        self.setPalette(palette)
        self.timer_id = None

    def paintEvent(self, event):

        painter = QPainter()
        painter.begin(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(event.rect(), QBrush(QColor(255, 255, 255, 127)))
        painter.setPen(QPen(Qt.NoPen))

        for i in range(6):
            if self.counter % 6 == i:
                painter.setBrush(QBrush(QColor(0, 0, 0)))
            else:
                painter.setBrush(QBrush(QColor(200, 200, 200)))
            painter.drawEllipse(
                self.width() / 2 + 30 * math.cos(2 * math.pi * i / 6.0) - 10,
                self.height() / 2 + 30 * math.sin(2 * math.pi * i / 6.0) - 10,
                20, 20)

        painter.end()

    def showEvent(self, event):

        self.timer_id = self.startTimer(200)
        self.counter = 0

    def timerEvent(self, event):
        self.counter += 1
        self.update()

    def hideEvent(self, event):
        if self.timer_id:
            self.killTimer(self.timer_id)
            self.timer_id = None
