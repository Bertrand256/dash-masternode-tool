#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Author: Bertrand256
# Created on: 2018-09
import json
import re

from PyQt5 import QtWidgets
from PyQt5.QtCore import pyqtSlot, QEvent, Qt
from PyQt5.QtWidgets import QDialog, QDialogButtonBox
from bitcoinrpc.authproxy import EncodeDecimal

from ui import ui_cmd_console_dlg
from wnd_utils import WndUtils, get_widget_font_color_green
import logging
import app_cache
from app_defs import get_known_loggers, DEFAULT_LOG_FORMAT


class CmdConsoleDlg(QDialog, ui_cmd_console_dlg.Ui_CmdConsoleDlg):
    def __init__(self, main_dlg, app_config):
        QDialog.__init__(self, main_dlg)
        ui_cmd_console_dlg.Ui_CmdConsoleDlg.__init__(self)
        self.main_dlg = main_dlg
        self.app_config = app_config

        # user will be able to configure only those loggers, that exist in the known loggers list
        self.known_loggers = []
        for kl in sorted(get_known_loggers(), key = lambda x: (x.external, x.name)):
            self.known_loggers.append(kl.name)

        self.last_commands = []
        self.last_command_index = None
        self.saved_command_text = ''
        self.setupUi(self)

    def setupUi(self, dialog: QtWidgets.QDialog):
        ui_cmd_console_dlg.Ui_CmdConsoleDlg.setupUi(self, self)
        self.setWindowTitle("Command console")
        self.restore_cache_settings()
        btn = self.buttonBox.button(QDialogButtonBox.Close)
        btn.setAutoDefault(False)
        self.edtCommand.setFocus()
        self.edtCommand.installEventFilter(self)

    def closeEvent(self, event):
        self.save_cache_settings()

    def restore_cache_settings(self):
        app_cache.restore_window_size(self)

    def save_cache_settings(self):
        app_cache.save_window_size(self)

    def eventFilter(self, obj, event):
        if obj == self.edtCommand:
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Up:
                    self.prev_command()
                    return True
                elif event.key() == Qt.Key_Down:
                    self.next_command()
                    return True
            return False
        else:
            return super().eventFilter(obj, event)

    def prev_command(self):
        if self.last_commands:
            if self.last_command_index is None:
                self.last_command_index = len(self.last_commands) - 1
            if self.last_command_index > 0:
                if self.last_command_index >= len(self.last_commands):
                    self.saved_command_text = self.edtCommand.text()

                self.last_command_index -= 1
                self.edtCommand.setText(self.last_commands[self.last_command_index])

    def next_command(self):
        if self.last_commands:
            if self.last_command_index is None:
                self.last_command_index = len(self.last_commands) - 1
            if self.last_command_index < len(self.last_commands) - 1:
                self.last_command_index += 1
                self.edtCommand.setText(self.last_commands[self.last_command_index])
            elif self.last_command_index == len(self.last_commands) - 1:
                self.last_command_index += 1
                self.edtCommand.setText(self.saved_command_text)

    def on_edtCommand_returnPressed(self):
        self.process_command(self.edtCommand.text().strip())
        self.edtCommand.clear()

    def process_command(self, command: str):
        if not self.last_commands:
            newl = ''
        else:
            newl = '<br>'
        self.message(newl + '&gt; <b>' + command + '</b><br>', get_widget_font_color_green(self.edtCmdLog))
        ok = False

        match = re.search(r"\s*([A-Za-z0-9]+)\s*(.*)", command)
        if not match or len(match.groups()) < 2:
            self.error('Invalid command')
            return
        else:
            cmd = match.group(1)
            if cmd:
                cmd = cmd.lower()
            args = match.group(2).strip()

        if cmd == 'help':
            if not args:
                self.print_help()
                ok = True
            else:
                self.error('Invalid command arguments: ' + args)

        elif cmd == 'display':

            if re.match(r"^modules$", args, re.IGNORECASE):
                self.print_loggers()
                ok = True
            elif re.match(r"^logformat$", args, re.IGNORECASE):
                self.print_logformat()
                ok = True
            else:
                self.error('Invalid command arguments: ' + args)

        elif cmd == 'set':

            match = re.match(r"^loglevel\s+(.+)", args, re.IGNORECASE)
            if match:
                if len(match.groups()) == 1:
                    self.set_log_level(match.group(1))
                    ok = True
                else:
                    self.error('Invalid command arguments: ' + args)

            match = re.match(r"^logformat\s+(.+)", args, re.IGNORECASE)
            if match:
                if len(match.groups()) == 1:
                    self.set_log_format(match.group(1))
                    ok = True
                else:
                    self.error('Invalid command arguments: ' + args)

            if not ok:
                self.error('Invalid command arguments: ' + args)

        elif cmd == 'rpc':

            match = re.match(r"^(\w+)\s*(.*)", args, re.IGNORECASE)
            if match and len(match.groups()) >= 1:
                args = match.group(2) if len(match.groups()) > 1 else None
                if args:
                    args = args.strip().strip("'")
                    try:
                        a = json.loads(args)
                        ok = self.rpc_command(match.group(1), a)
                    except:
                        a = args.split()
                        for idx, el in enumerate(a):
                            if isinstance(el, str) and el.lower() in ('true', 'false'):
                                a[idx] = (el.lower() == 'true')
                        ok = self.rpc_command(match.group(1), *a)
                else:
                    ok = self.rpc_command(match.group(1))
            else:
                self.error('Missing the RPC command name')

        else:
            self.error('Invalid command: ' + cmd)

        if ok and (not self.last_commands or self.last_commands[-1] != command):
            self.last_commands.append(command)
            self.last_command_index = len(self.last_commands)

    def print_help(self):
        help = f"""Command list
        
        <b>set loglevel ["module-name":"log-level",...]</b>
          Sets up the log level for a specific module.
          Arguments:
            "module-name": "all" or a name of a module; to display list of all modules, enter `display modules` command
            "log-level": debug|info|warning|error|critical
          Example: set loglevel all:info,dmt.bip44_wallet:debug  
            
        <b>set logformat "format-string"</b>
          Sets the format of log messages.
          Arguments:
            "format-string": string with at least one of the following format elements:
              %(asctime)s      Human-readable time.
              %(msecs)d        Millisecond portion of the time when the LogRecord was created.
              %(pathname)s     Full pathname of the source file where the logging call was issued (if available).
              %(filename)s     Filename portion of pathname.
              %(funcName)s     Name of function containing the logging call.
              %(name)s         Name of the module (logger) used to log the call.
              %(levelname)s    Log level name.
              %(levelno)s      Numeric logging level for the message.
              %(lineno)d       Source line number where the logging call was issued (if available).
              %(message)s      The logged message.
              %(process)d      Process ID (if available).
              %(processName)s  Process name (if available).
              %(thread)d       Thread ID (if available).
              %(threadName)s   Thread name (if available).
          Default:
            {DEFAULT_LOG_FORMAT}
                
        <b>display logformat</b>
          Displays current log format.

        <b>display modules</b>
          Displays all logger modules. 

        <b>rpc command ["arg1",...]</b>
          Sends a RPC call to the RPC node you are connected to. 
        """
        lines = help.split('\n')
        if len(lines) > 1:
            l = lines[1]
            # count spaces at the beginning of the second line to calculate the indention
            ind = len(re.match(' *', l).group())

            for idx, l in enumerate(lines):
                if idx > 0:
                    remove_len = min(ind, len(re.match(' *', l).group()))
                    l = l[remove_len:]
                    lines[idx] = l
            for l in lines:
                self.edtCmdLog.append(l)

    def print_loggers(self):
        lines = []
        default_level = logging.getLevelName(logging.getLogger().level)
        for logger_name in self.known_loggers:
            log = logging.getLogger(logger_name)
            if log.level == 0:
                level_name = default_level
            else:
                level_name = logging.getLevelName(log.level)
            lines.append(f'  {logger_name}: {level_name}')
        self.edtCmdLog.append('\n'.join(lines))

    def print_logformat(self):
        if self.app_config.log_handler and self.app_config.log_handler.formatter:
            self.message(self.app_config.log_handler.formatter._fmt)
        else:
            self.error('Log handler or log formatter not set in the app_config module.')

    def message(self, msg, color=None, style=None):
        if color:
            s = 'style="color:'+color+'"'
        else:
            s = ''
        if style:
            s = 'style="' + style + '"'
        self.edtCmdLog.append(f'<span {s}>{msg}</span>')

    def error(self, msg):
        self.message(msg, 'red')

    def set_log_level(self, cfg: str):
        elems = cfg.split(',')
        if len(elems) > 0:
            for e in elems:
                elems1 = e.split(':')
                if len(elems1) == 2:
                    logger_name, level_name = elems1
                    level_name = level_name.upper().strip()
                    logger_name = logger_name.strip()
                    if level_name not in logging._levelToName.values():
                        self.error(f'Error: invalid log level name ({level_name}) for module {logger_name}')
                        continue
                    if logger_name.lower() == 'all':

                        for logger_name in logging.Logger.manager.loggerDict:
                            l = logging.Logger.manager.loggerDict[logger_name]
                            if isinstance(l, logging.Logger):
                                l.setLevel(level_name)

                        self.message(f'{level_name} level has been set for all modules')
                    else:
                        if logger_name in self.known_loggers:
                            logging.getLogger(logger_name).setLevel(level_name)
                            self.message(f'{level_name} level has been set for module {logger_name}')
                        else:
                            self.error(f'Error: module {logger_name} does not exist')

    def set_log_format(self, format_string: str):
        formatter = logging.Formatter(fmt=format_string, datefmt='%Y-%m-%d %H:%M:%S')
        l = logging.getLogger()
        for h in l.handlers:
            h.setFormatter(formatter)
        self.message('Log format set to: ' + format_string)

    def rpc_command(self, command: str, *args):
        if self.main_dlg.dashd_intf:
            ret = self.main_dlg.dashd_intf.rpc_call(False, True, command, *args)
            try:
                if isinstance(ret, str):
                    ret = json.loads(ret)
                ret = json.dumps(ret, default=EncodeDecimal, indent = 4, separators = (',', ': '))
            except Exception:
                pass
            self.message(ret, style="white-space: pre-wrap;")
            return True
        else:
            WndUtils.error_msg('Not connected to a Dash node')
            return False

    @pyqtSlot()
    def on_buttonBox_accepted(self):
        self.save_cache_settings()
        self.accept()
        # self.hide()
