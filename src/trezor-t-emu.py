import os
import subprocess
import sys
import logging
import time
import threading
import PyQt5.QtWidgets as qwi


def execute_trezor_emu(emulator_base_dir: str, profile_dir: str):
    env = os.environ
    env['BROWSER'] = 'chromium'
    env['TREZOR_PROFILE'] = profile_dir
    start_sh = 'emu.sh'

    try:
        p = subprocess.Popen([os.path.join(emulator_base_dir, start_sh)], cwd=emulator_base_dir, env=env)
        p.wait()
        app.exit(0)
    except Exception as e:
        print(str(e))
        app.exit(1)


if __name__ == '__main__':
    app = qwi.QApplication(sys.argv)

    if getattr(sys, 'frozen', False):
        emulator_base_dir = sys._MEIPASS
        emulator_bin = os.path.join(emulator_base_dir, 'micropython')
        print('emulator_dir: ' + emulator_base_dir)
    else:
        app_dir = os.path.dirname(__file__)
        path, tail = os.path.split(app_dir)
        if tail == 'src':
            app_dir = path
        emulator_base_dir = os.path.join(app_dir, 'hardware-wallets', 'trezor-core-emu')
        emulator_bin = os.path.join(emulator_base_dir, sys.platform, 'micropython')

    profile_dir = os.path.join(os.path.expanduser('~'), '.dmt', 'trezor-core-emu')
    t = threading.Thread(target=execute_trezor_emu, args=(emulator_base_dir, profile_dir))
    t.start()

    sys.exit(app.exec_())
