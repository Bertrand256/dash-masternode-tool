# -*- mode: python -*-
import glob
import os
import sys

block_cipher = None

base_dir = os.path.dirname(os.path.realpath('__file__'))
data_files = []
binary_files = []
version_str = '?.?.?'


emu_binary = os.path.join(base_dir, 'hardware-wallets', 'trezor-core-emu', sys.platform, 'micropython')
emu_base_dir_from = os.path.join(base_dir, 'hardware-wallets', 'trezor-core-emu')


def add_data_file(file: str, dest_dir: str):
    data_files.append((file, dest_dir))
    print(f'Adding file {file} to dest dir {dest_dir}')

def add_binary_file(file: str, dest_dir: str):
    global bianry_files
    binary_files.append((file, dest_dir))
    print(f'Adding binary file {file} to dest dir {dest_dir}')


with open(os.path.join(emu_base_dir_from, 'version.txt')) as fptr:
    for line in fptr:
        parts = [elem.strip() for elem in line.split('=')]
        if len(parts) == 2 and parts[0].lower() == 'version_str':
            version_str = parts[1].strip("'")
            break


if os.path.exists(emu_base_dir_from):
    emu_dir_len_src = len(emu_base_dir_from)
    print('Trezor emulator dir exists: ' + emu_base_dir_from)

    for subdir, recursive in (('embed/**', True), ('src/**', True), ('**', False)):
        for fname in glob.iglob(os.path.join(emu_base_dir_from, subdir), recursive=recursive):
            if os.path.isfile(fname):
                if fname.startswith(base_dir):
                    dest_dir = fname[emu_dir_len_src:]
                    if dest_dir and dest_dir[0] == '/' or '\\':
                        dest_dir = dest_dir[1:]
                    dest_dir = os.path.dirname(dest_dir)
                    if not dest_dir:
                        dest_dir = '.'
                else:
                    dest_dir = '.'
                add_data_file(fname, dest_dir)

    add_binary_file(emu_binary, '.')
    if sys.platform == 'darwin':
        add_binary_file('/usr/lib/libSystem.B.dylib', '.')
        add_binary_file('/usr/local/opt/sdl2_image/lib/libSDL2_image-2.0.0.dylib', '.')
        add_binary_file('/usr/local/opt/sdl2/lib/libSDL2-2.0.0.dylib', '.')
        add_binary_file('/usr/local/lib/libwebp.7.dylib', '.')
        add_binary_file('/usr/local/lib/libusb-1.0.dylib', '.')
        add_binary_file('/usr/local/lib/libpng16.16.dylib', '.')
        add_binary_file('/usr/local/lib/libjpeg.9.dylib', '.')
        add_binary_file('/usr/local/lib/libtiff.5.dylib', '.')
        add_binary_file('/usr/local/lib/libpng16.16.dylib', '.')
        add_binary_file('/usr/local/lib/libpng16.16.dylib', '.')
    elif sys.platform == 'linux':
        add_binary_file('/usr/lib/x86_64-linux-gnu/libSDL2_image-2.0.so.0', '.')
        add_binary_file('/usr/lib/x86_64-linux-gnu/libSDL2-2.0.so.0', '.')
        add_binary_file('/usr/lib/x86_64-linux-gnu/libwebp.so.5', '.')
        add_binary_file('/usr/lib/x86_64-linux-gnu/libusb-1.0.so', '.')
        add_binary_file('/usr/lib/x86_64-linux-gnu/libsndio.so.6.1', '.')

else:
    print('Trezor emulator dir does not exist: ' + emu_base_dir_from)


a = Analysis(['src/trezor-t-emu.py'],
             pathex=[base_dir],
             binaries=binary_files,
             datas=data_files,
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)

pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='TrezorT-emulator',
          debug=False,
          strip=False,
          upx=False,
          console=False,
          icon=os.path.join('img',('hw-emulator.%s' % ('icns' if sys.platform=='darwin' else 'ico'))))

if sys.platform == 'darwin':
    app = BUNDLE(exe,
                 name='TrezorT-emulator.app',
                 icon='img/hw-emulator.icns',
                 bundle_identifier=None,
                 info_plist={
                    'NSHighResolutionCapable': 'True'
                 })

dist_path = os.path.join(base_dir, DISTPATH)
all_bin_dir = os.path.join(dist_path, '..', 'all')
if not os.path.exists(all_bin_dir):
    os.makedirs(all_bin_dir)

# zip archives
print(dist_path)
print(all_bin_dir)
os.chdir(dist_path)

if sys.platform == 'darwin':
    print('Compressing Mac executable')
    os.system('zip -r "%s" "%s"' % (os.path.join(all_bin_dir, 'TrezorT-emulator_' + version_str + '.mac.zip'),  'TrezorT-emulator.app'))
elif sys.platform == 'linux':
    print('Compressing Linux executable')
    os.system('tar -zcvf %s %s' % (os.path.join(all_bin_dir, 'TrezorT-emulator_' + version_str + '.linux.tar.gz'),  'TrezorT-emulator'))
