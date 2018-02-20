#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2017-04
from collections import Callable
from functools import partial

from PyQt5 import QtWidgets, QtCore
from PyQt5.QtCore import Qt, QEventLoop, QPoint, QSize
from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QDialog

from ui import ui_thread_fun_dlg


class ThreadFunDlg(QtWidgets.QDialog, ui_thread_fun_dlg.Ui_ThreadFunDlg):
    """
    Some of the DMT's features require quite a long time to complete. Performing this in a main thread
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
    res = ui.getResult()

    Example of a worker function:
        def long_running_function(ctrl, arg1):
            ctrl.dlg_config_fun(dlg_title="Long running task...", show_message=True, show_progress_bar=True)
            ctrl.display_msg_fun('test %d' % i)
            ctrl.set_progress_value_fun(50)
            time.sleep(10)
            if ctrl.finish:  # if using a loop you should periodically check if the user is willing to breake the task
                return
            return 'return value'
    """

    # signal for display message, args: message text:
    display_msg_signal = QtCore.pyqtSignal(str)

    # sets a dialog's progress bar's value
    set_progress_value_signal = QtCore.pyqtSignal(int)

    # signal to configure dialog, args: (bool) show message text (default True), (bool) show progress bar,
    # (int) window maximum width
    # (default false):
    dlg_config_signal = QtCore.pyqtSignal(object, object, object, object)

    def __init__(self, worker_fun, worker_args, close_after_finish=True, buttons=None, title='', text=None,
                 center_by_window=None):
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
                results in 'accept' or 'reject' event, depending on butotn's role. 
        :param title: title of the dialog
        :param text: initial text to display
        :param center_by_window: True, if this dialog is to be centered by window 'center_by_window'
        """
        QtWidgets.QDialog.__init__(self, parent=center_by_window)
        ui_thread_fun_dlg.Ui_ThreadFunDlg.__init__(self)
        self.worker_fun = worker_fun
        self.worker_args = worker_args
        self.close_after_finish = close_after_finish
        self.buttons = buttons
        self.setTextCalled = False
        self.title = title
        self.text = text
        self.max_width = None
        self.center_by_window = center_by_window
        self.setupUi()

    def setupUi(self):
        ui_thread_fun_dlg.Ui_ThreadFunDlg.setupUi(self, self)
        self.setWindowFlags(self.windowFlags() | Qt.CustomizeWindowHint)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowCloseButtonHint)
        self.setWindowTitle(self.title)
        self.display_msg_signal.connect(self.setText)
        self.dlg_config_signal.connect(self.onConfigureDialog)
        self.set_progress_value_signal.connect(self.setProgressValue)
        self.closeEvent = self.closeEvent
        self.btnBox.accepted.connect(self.accept)
        self.btnBox.rejected.connect(self.reject)
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
            self.work = WorkerDlgThread(self, self.worker_fun, self.worker_args,
                                        display_msg_signal=self.display_msg_signal,
                                        set_progress_value_signal=self.set_progress_value_signal,
                                        dlg_config_signal=self.dlg_config_signal)
            self.work.finished.connect(self.threadFinished)

        self.worker_result = None
        self.worker_exception = None
        if self.text:
            self.setText(self.text)
        if self.center_by_window:
            self.centerByWindow(self.center_by_window)
        if self.worker_fun:
            self.thread_runnung = True
            self.work.start()
        else:
            self.thread_runnung = False

    def getResult(self):
        return self.worker_result

    def setText(self, text):
        """
        Displays text on dialog.
        :param text: Text to be displayed.
        """
        if not self.setTextCalled:
            self.layout().setSizeConstraint(3)  # QLayout::SetFixedSize
            self.setTextCalled = True
        self.lblText.setText(text)

        # width = self.lblText.fontMetrics().boundingRect(text).width()
        # if self.max_width and width > self.max_width:
        #     width = self.max_width
        # self.lblText.setFixedWidth(width)

        QtWidgets.qApp.processEvents(QEventLoop.ExcludeUserInputEvents)
        self.centerByWindow(self.center_by_window)

    def setProgressValue(self, value):
        self.progressBar.setValue(value)

    def centerByWindow(self, center_by_window: QDialog):
        """
        Centers this window by window given by attribute 'center_by_window'
        :param center_by_window: Reference to (parent) window by wich this window will be centered.
        :return: None
        """
        if self.center_by_window:
            pg: QPoint = center_by_window.frameGeometry().topLeft()
            size_diff = center_by_window.rect().center() - self.rect().center()
            pg.setX( pg.x() + int((size_diff.x())))
            pg.setY( pg.y() + int((size_diff.y())))
            self.move(pg)

    def onConfigureDialog(self, show_message=None, show_progress_bar=None, dlg_title=None, max_width=None):
        """
        Configure visibility of this dialog's elements. This method can be called from inside a thread by calling
        signal dlg_config_signal passed inside control dicttionary.
        :param show_message: True if text area is to be shown
        :param show_progress_bar: True if progress bar is to be shown
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

    def setWorkerResults(self, result, exception):
        self.worker_result = result
        self.worker_exception = exception

    def threadFinished(self):
        self.thread_runnung = False
        del self.work
        if self.close_after_finish:
            self.accept()

    def waitForTerminate(self):
        if self.thread_runnung:
            self.work.stop()
            self.work.wait()

    def closeEvent(self, event):
        self.waitForTerminate()

    def accept(self):
        self.waitForTerminate()
        self.close()

    def reject(self):
        self.waitForTerminate()
        self.close()


class CtrlObject(object):
    def __init__(self):
        self.display_msg_fun: Callable[[str], None] = None
        self.set_progress_value_fun: Callable[[int], None] = None
        self.dlg_config_fun: Callable[[bool, bool, str, int],None] = None
        self.finish: bool = False


class WorkerDlgThread(QThread):
    """
    Class dedicated for running external method (worker_fun) in the background with a dialog (ThreadFunDlg) 
    on the foreground. Dialog's purpose is to display messages and/or progress bar according to the information
    sent by external thread function (worker_fun) by calling callback functions passed to it.
    """

    def __init__(self, dialog, worker_fun, worker_fun_args, display_msg_signal, set_progress_value_signal,
                 dlg_config_signal):
        """
        Constructor.
        :param worker_fun: external function which will be executed from inside a thread 
        :param worker_fun_args: dictionary passed to worker_fun as it's argument's
        :param display_msg_signal: signal from owner's dialog to display text
        :param set_progress_value_signal: signal from owner's dialog to set a progressbar's value
        :param dlg_config_signal: signal from owner's dialog to configure dialog
        """
        super(WorkerDlgThread, self).__init__()
        self.dialog = dialog
        self.worker_fun = worker_fun
        self.worker_fun_args = worker_fun_args
        self.display_msg_signal = display_msg_signal
        self.set_progress_value_signal = set_progress_value_signal
        self.dlg_config_signal = dlg_config_signal

        # prepare control object passed to a thread function
        self.ctrl_obj = CtrlObject()
        self.ctrl_obj.display_msg_fun = self.display_msg
        self.ctrl_obj.set_progress_value_fun = self.set_progress_value
        self.ctrl_obj.dlg_config_fun = self.dlg_config
        self.ctrl_obj.finish = False

    def display_msg(self, msg):
        """
        Called from a thread: displays a new message text.
        :param msg: text
        """
        self.display_msg_signal.emit(msg)

    def set_progress_value(self, value):
        """
        Called from a thread: sets progressbar's value
        :param value: new value
        """
        self.set_progress_value_signal.emit(value)

    def dlg_config(self, show_message=None, show_progress_bar=None, dlg_title=None, max_width=None):
        """
        Called from a thread function: configures dialog by sending a dediacted signal to a dialog class.
        :param show_message: True if dialog's text area is to be shown.
        :param show_progress_bar: True if dialog's progress bar is to be shown.
        :param dlg_title: New text to show on dialogs title bar.
        """
        self.dlg_config_signal.emit(show_message, show_progress_bar, dlg_title, max_width)

    def stop(self):
        """
        Sets information in control object that thread should finish its work as soon as possible.
        Finish attribute should be checked by a thread periodically.
        """
        self.ctrl_obj.finish = True

    def run(self):
        try:
            worker_result = self.worker_fun(self.ctrl_obj, *self.worker_fun_args)
            self.dialog.setWorkerResults(worker_result, None)
        except Exception as e:
            self.dialog.setWorkerResults(None, e)


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


