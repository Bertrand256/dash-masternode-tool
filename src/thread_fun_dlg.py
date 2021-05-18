#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04
from __future__ import annotations

import time
from typing import Optional, Callable, Any

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import QThread
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtWidgets import QDialog, QLabel, QLayout

from common import CancelException
from ui import ui_thread_fun_dlg


class ThreadFunDlg(QtWidgets.QDialog, ui_thread_fun_dlg.Ui_ThreadFunDlg):
    """
    Some of the DMT features require quite a long time to complete. Performing this in a main thread
    causes the app to behave as if it hung. In such situations it is better to display a dialog with
    some information about the progress of the task.
    This class is such a dialog window - it takes a reference to function/method performing a long-running task. 
    That function is executed inside a thread, controlled by a dialog and has the possibility of updating dialog's 
    text and/or progressbar through a special control object passed to it as an argument.
    
    Creating dialog for long running function:
    arg1 = 'test'
    ui = ThreadFunDlg(long_running_function, (arg1,), close_after_finish=True, 
        buttons=[{'caption': 'Break', 'role': QtWidgets.QDialogButtonBox.RejectRole}])
    ui.exec_()
    res = ui.get_result()

    Example of a worker function:
        def long_running_function(ctrl, arg1):
            ctrl.dlg_config(dlg_title="Long running task...", show_message=True, show_progress_bar=True)
            ctrl.display_msg('test %d' % i)
            ctrl.set_progress_value(50)
            time.sleep(10)
            if ctrl.finish:  # if using a loop you should periodically check if the user is willing to break the task
                return
            return 'return value'
    """

    # signal for display message, args: message text:
    display_msg_signal = QtCore.pyqtSignal(str)

    # sets a dialog's progress bar's value
    set_progress_value_signal = QtCore.pyqtSignal(int)

    show_window_signal = QtCore.pyqtSignal(bool)

    # signal to configure dialog, args: (bool) show message text (default True), (bool) show progress bar,
    # (int) window maximum width
    # (default false):
    dlg_config_signal = QtCore.pyqtSignal(object, object, object, object)

    def __init__(self, worker_fun, worker_args, close_after_finish=True, buttons=None, title='', text=None,
                 center_by_window=None,
                 force_close_dlg_callback: Optional[Callable[[], bool]] = None,
                 show_window_delay_ms: Optional[int] = 0):
        """
        Constructor.
        :param worker_fun: reference to an external method which is to be run in background
        :param worker_args: tuple with arguments passed to worker_fun
        :param close_after_finish: True, if dialog has to be closed after finishing worker_fun
        :param buttons: list of button definition to be created on the bottom of the dialog;
            Each of the elements can be:
              - a dict  {'std_btn': QtWidgets.QDialogButtonBox.StandardButton for example: QDialogButtonBox.Cancel,
                         'callback': callback_function (not mandatory)}
              - a dict {'caption': "Button caption", 
                        'role': QtWidgets.QDialogButtonBox.ButtonRole,
                         'callback': callback_function (not mandatory)}
            'callback': function executed on specific button click event; id not specified, click event 
                results in 'accept' or 'reject' event, depending on button's role.
        :param title: title of the dialog
        :param text: initial text to display
        :param center_by_window: True, if this dialog is to be centered by window 'center_by_window'
        :param force_close_dlg_callback: non mandatory callback function called when a user tries to close window
            while the associated thread hasn't finished yet; the callback function can for example ask the user if
            he/she really wants to break the underlying process (this means leaving the thread alone and closing the
            window) or apply a little more civilized approach like causing the termination of the underlying thread if
            possible; if the callback function returns True it means that there is consent to abandon thread and
            close the window
        :param show_window_delay_ms:
           -1: the window is initially hidden; can be shown only by emitting the 'show_window_signal' signal
           or explicitly calling the 'show' method
           >=0 the will be shown after the 'value' milliseconds after calling the 'wait_for_worker_completion'
           method
        """
        QtWidgets.QDialog.__init__(self, parent=center_by_window)
        ui_thread_fun_dlg.Ui_ThreadFunDlg.__init__(self)
        self.worker_fun = worker_fun
        self.worker_args = worker_args
        self.close_after_finish = close_after_finish
        self.force_close_dlg_callback = force_close_dlg_callback
        self.buttons = buttons
        self.set_text_called = False
        self.title = title
        self.text = text
        self.show_window_delay_ms = show_window_delay_ms
        self.max_width = None
        self.worker_thread: Optional[WorkerDlgThread] = None
        self.center_by_window = center_by_window
        self.worker_result: Any = None
        self.worker_exception: Optional[Exception] = None
        self.thread_running: bool = False
        self.setupUi(self)

    def setupUi(self, dialog: QtWidgets.QDialog):
        ui_thread_fun_dlg.Ui_ThreadFunDlg.setupUi(self, self)
        self.setWindowFlags(int(self.windowFlags()) | Qt.CustomizeWindowHint)
        self.setWindowTitle(self.title)
        self.display_msg_signal.connect(self.set_text)
        self.dlg_config_signal.connect(self.on_configure_dialog)
        self.show_window_signal.connect(self.on_show_window)
        self.set_progress_value_signal.connect(self.set_progress_value)
        self.progressBar.setVisible(False)
        self.btnBox.clear()
        self.btnBox.setCenterButtons(True)

        if self.buttons:
            for btn in self.buttons:
                assert isinstance(btn, dict)
                if btn.get('std_btn'):
                    b = self.btnBox.addButton(btn.get('std_btn'))
                elif btn.get('caption'):
                    if not btn.get('role'):
                        raise Exception("Button's role is mandatory")
                    b = self.btnBox.addButton(btn.get('caption'), btn.get('role'))
                else:
                    continue
                if btn.get('callback'):
                    b.clicked.connect(btn.get('callback'))
        if self.worker_fun:
            self.worker_thread = WorkerDlgThread(self, self.worker_fun, self.worker_args,
                                                 display_msg_signal=self.display_msg_signal,
                                                 set_progress_value_signal=self.set_progress_value_signal,
                                                 dlg_config_signal=self.dlg_config_signal,
                                                 show_dialog_signal=self.show_window_signal)
            self.worker_thread.finished.connect(self.thread_finished)

            # the user method controlled by the worker thread may need to access the widget
            # displaying a feedback for its non-standard purposes, so we expose it through
            # control object which is passed to that method
            self.worker_thread.ctrl_obj.set_msg_label(self.lblText)

        self.worker_result = None
        self.worker_exception = None
        if self.text:
            self.set_text(self.text)
        if self.center_by_window:
            self.center_by_widget(self.center_by_window)
        if self.worker_fun:
            self.thread_running = True
            self.worker_thread.start()
        else:
            self.thread_running = False

    def get_result(self):
        return self.worker_result

    def set_text(self, text):
        """
        Displays text on dialog.
        :param text: Text to be displayed.
        """
        if not self.set_text_called:
            self.layout().setSizeConstraint(QLayout.SetFixedSize)
            self.set_text_called = True
        self.lblText.setText(text)

        # width = self.lblText.fontMetrics().boundingRect(text).width()
        # if self.max_width and width > self.max_width:
        #     width = self.max_width
        # self.lblText.setFixedWidth(width)

        # QtWidgets.qApp.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.center_by_widget(self.center_by_window)

    def set_progress_value(self, value):
        self.progressBar.setValue(value)

    def on_show_window(self, show: bool):
        if show:
            self.show()
        else:
            self.hide()

    def center_by_widget(self, center_by_window: QDialog):
        """
        Centers this window by window given by attribute 'center_by_window'
        :param center_by_window: Reference to (parent) window by which this window will be centered.
        :return: None
        """
        if self.center_by_window:
            pg: QPoint = center_by_window.frameGeometry().topLeft()
            size_diff = center_by_window.rect().center() - self.rect().center()
            pg.setX(pg.x() + int((size_diff.x())))
            pg.setY(pg.y() + int((size_diff.y())))
            self.move(pg)

    def on_configure_dialog(self, show_message=None, show_progress_bar=None, dlg_title=None, max_width=None):
        """
        Configures visibility of this dialog elements. This method can be called from inside a thread by calling
        signal dlg_config_signal passed inside control dictionary.
        :param max_width: The maximum size of the dialog window in pixels.
        :param dlg_title: If passed, this string will become the window title.
        :param show_message: True if the text area is to be shown
        :param show_progress_bar: True if the progress bar is to be shown
        """
        if show_message:
            self.lblText.setVisible(show_message)
        if show_progress_bar:
            self.progressBar.setVisible(show_progress_bar)
        if dlg_title:
            self.setWindowTitle(dlg_title)
        if max_width is not None:
            self.max_width = max_width
            self.lblText.setWordWrap(True)
        else:
            self.lblText.setWordWrap(False)

    def set_worker_results(self, result, exception):
        self.worker_result = result
        self.worker_exception = exception

    def thread_finished(self):
        self.thread_running = False
        work = self.worker_thread
        self.worker_thread = None
        del work
        if self.close_after_finish:
            self.accept()

    def wait_for_terminate(self):
        if self.thread_running:
            self.worker_thread.stop()
            if self.force_close_dlg_callback is not None:
                try:
                    finish = self.force_close_dlg_callback()
                    if finish:
                        # user's decision to force close the window; probably something went wrong
                        # and some underlying process hung
                        self.thread_running = False
                        return
                except CancelException as e:
                    self.worker_exception = e
                    return
                except Exception as e:
                    self.worker_exception = e
                    return
            self.worker_thread.wait()

    def closeEvent(self, event):
        if self.thread_running:
            self.worker_thread.currentThreadId()
            self.wait_for_terminate()

    def accept(self):
        self.wait_for_terminate()
        self.close()

    def reject(self):
        self.wait_for_terminate()
        self.close()

    def wait_for_worker_completion(self):
        start_time = time.time()
        shown = False
        while self.thread_running:
            if not shown and 0 <= self.show_window_delay_ms <= (time.time() - start_time) * 1000:
                self.show()
                shown = True
            QtWidgets.qApp.processEvents()
            if self.worker_thread:
                self.worker_thread.wait(100)
            else:
                break


class CtrlObject(object):
    def __init__(self):
        self._display_msg_fun: Optional[Callable[[str], None]] = None
        self._set_progress_value_fun: Optional[Callable[[int], None]] = None
        self._dlg_config_fun: Optional[Callable[[bool, bool, str, int], None]] = None
        self._show_dialog_fun: Optional[Callable[[bool], None]] = None
        self.finish: bool = False
        self.__msg_label = None

        # below: reference to a Qt dialog if this object is used by ThreadFunDlg to allow an underlying function (run
        # as thread) to control some aspects of the dialog that is displayed during the thread's execution
        self.dialog: Optional[QDialog] = None

    def set_callback_functions(
            self,
            display_msg_fun: Optional[Callable[[str], None]] = None,
            set_progress_value_fun: Optional[Callable[[int], None]] = None,
            dlg_config_fun: Optional[Callable[[bool, bool, str, int], None]] = None,
            show_dialog_fun: Optional[Callable[[bool], None]] = None
    ):
        self._display_msg_fun = display_msg_fun
        self._set_progress_value_fun = set_progress_value_fun
        self._dlg_config_fun = dlg_config_fun
        self._show_dialog_fun = show_dialog_fun

    def get_msg_label_control(self) -> QLabel:
        return self.__msg_label

    def set_msg_label(self, label: QLabel):
        self.__msg_label = label

    def display_msg(self, msg: str):
        if self._display_msg_fun:
            self._display_msg_fun(msg)

    def set_progress_value(self, value: int):
        if self._set_progress_value_fun:
            self._set_progress_value_fun(value)

    def dlg_config(self, show_message: bool = False, show_progress_bar: bool = False, dlg_title: Optional[str] = None,
                   max_width: Optional[int] = None):
        if self._dlg_config_fun:
            self._dlg_config_fun(show_message, show_progress_bar, dlg_title, max_width)

    def show_dialog(self, show: bool):
        if self._show_dialog_fun:
            self._show_dialog_fun(show)


class WorkerDlgThread(QThread):
    """
    Class dedicated for running external method (worker_fun) in the background with a dialog (ThreadFunDlg) 
    on the foreground. Dialog's purpose is to display messages and/or progress bar according to the information
    sent by external thread function (worker_fun) by calling callback functions passed to it.
    """

    def __init__(self, dialog: QDialog, worker_fun, worker_fun_args, display_msg_signal, set_progress_value_signal,
                 dlg_config_signal, show_dialog_signal):
        """
        Constructor.
        :param worker_fun: external function which will be executed from inside a thread 
        :param worker_fun_args: dictionary passed to worker_fun as it's argument's
        :param display_msg_signal: signal from owner's dialog to display text
        :param set_progress_value_signal: signal from owner's dialog to set a progressbar value
        :param dlg_config_signal: signal from owner's dialog to configure dialog
        """
        super(WorkerDlgThread, self).__init__()
        self.dialog: QDialog = dialog
        self.worker_fun = worker_fun
        self.worker_fun_args = worker_fun_args
        self.display_msg_signal = display_msg_signal
        self.set_progress_value_signal = set_progress_value_signal
        self.show_dialog_signal = show_dialog_signal
        self.dlg_config_signal = dlg_config_signal

        # prepare control object passed to a thread function
        self.ctrl_obj = CtrlObject()
        self.ctrl_obj.dialog = self.dialog
        self.ctrl_obj.set_callback_functions(
            display_msg_fun=self.display_msg, set_progress_value_fun=self.set_progress_value,
            dlg_config_fun=self.dlg_config, show_dialog_fun=self.show_dialog)
        self.ctrl_obj.finish = False

    def display_msg(self, msg):
        """
        Called from a thread: displays a new message text.
        :param msg: text
        """
        self.display_msg_signal.emit(msg)

    def set_progress_value(self, value):
        """
        Called from a thread: sets the progressbar value
        :param value: new value
        """
        self.set_progress_value_signal.emit(value)

    def dlg_config(self, show_message: bool = False, show_progress_bar: bool = False, dlg_title: Optional[str] = None,
                   max_width: Optional[int] = None):
        """
        Called from a thread function: configures dialog by sending a dedicated signal to a dialog class.
        :param show_message: True if dialog's text area is to be shown.
        :param show_progress_bar: True if dialog's progress bar is to be shown.
        :param dlg_title: New text to show on dialogs title bar.
        :param max_width: If not None, it's used to set then maximum width of the dialog window in pixels.
        """
        self.dlg_config_signal.emit(show_message, show_progress_bar, dlg_title, max_width)

    def show_dialog(self, show: bool):
        self.show_dialog_signal.emit(show)

    def stop(self):
        """
        Sets information in control object that thread should finish its work as soon as possible.
        Finish attribute should be checked by a thread periodically.
        """
        self.ctrl_obj.finish = True

    def run(self):
        try:
            worker_result = self.worker_fun(self.ctrl_obj, *self.worker_fun_args)
            self.dialog.set_worker_results(worker_result, None)
        except Exception as e:
            self.dialog.set_worker_results(None, e)


class WorkerThread(QThread):
    """
    Helper class for running function inside a thread.
    """

    def __init__(self, parent, worker_fun, worker_fun_args):
        """
        """
        QThread.__init__(self, parent=parent)
        self.worker_fun = worker_fun
        self.worker_fun_args = worker_fun_args

        # prepare control object passed to external thread function
        self.ctrl_obj = CtrlObject()
        self.ctrl_obj.finish = False
        self.worker_result = None
        self.worker_exception = None

    def stop(self):
        """
        Sets information in control object that thread should finish its work as soon as possible.
        Finish attribute should be checked by a thread periodically.
        """
        self.ctrl_obj.finish = True

    def run(self):
        try:
            self.worker_result = self.worker_fun(self.ctrl_obj, *self.worker_fun_args)
        except Exception as e:
            self.worker_exception = e
