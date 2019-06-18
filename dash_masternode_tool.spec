# -*- mode: python -*-
import sys
import os.path
import platform

block_cipher = None

os_type = sys.platform
no_bits = platform.architecture()[0].replace('bit','')
version_str = ''
base_dir = os.path.dirname(os.path.realpath('__file__'))


# look for version string
with open(os.path.join(base_dir, 'version.txt')) as fptr:
    for line in fptr:
        parts = [elem.strip() for elem in line.split('=')]
        if len(parts) == 2 and parts[0].lower() == 'version_str':
            version_str = parts[1].strip("'")
            break

binary_files = []
data_files = [
 ('version.txt', '.')
]


def add_data_file(file: str, dest_dir: str):
    global data_files
    data_files.append((file, dest_dir))
    print(f'Adding data file {file} to dest dir {dest_dir}')


def add_binary_file(file: str, dest_dir: str):
    global bianry_files
    binary_files.append((file, dest_dir))
    print(f'Adding binary file {file} to dest dir {dest_dir}')


for f in os.listdir(os.path.join(base_dir, 'img')):
    f_full = os.path.join(base_dir, 'img', f)
    if os.path.isfile(f_full):
        add_data_file('img/' + f, '/img')


lib_path = next(p for p in sys.path if 'site-packages' in p)

add_data_file(os.path.join(lib_path, 'bitcoin/english.txt'), '/bitcoin')
add_data_file(os.path.join(lib_path, 'mnemonic/wordlist/english.txt'), '/mnemonic/wordlist')
add_data_file(os.path.join(lib_path, 'trezorlib/coins.json'), '/trezorlib')
add_data_file(os.path.join(lib_path, 'trezorlib/transport'), 'trezorlib/transport')

if os_type == 'darwin':
    add_binary_file('/usr/local/lib/libusb-1.0.dylib', '.')
elif os_type == 'win32':
    import ctypes.util
    l = ctypes.util.find_library('libusb-1.0.dll')
    if l:
        add_binary_file(l, '.')

a = Analysis(['src/dash_masternode_tool.py'],
             pathex=[base_dir],
             binaries=binary_files,
             datas=data_files,
             hiddenimports=['usb1'],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher)

pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)

exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='DashMasternodeTool',
          debug=False,
          strip=False,
          upx=False,
          console=False,
		  icon=os.path.join('img',('dmt.%s' % ('icns' if os_type=='darwin' else 'ico'))))

if os_type == 'darwin':
    app = BUNDLE(exe,
                 name='DashMasternodeTool.app',
                 icon='img/dmt.icns',
                 bundle_identifier=None,
                     info_plist={
                        'NSHighResolutionCapable': 'True'
                     }
                 )

dist_path = os.path.join(base_dir, DISTPATH)
all_bin_dir = os.path.join(dist_path, '..', 'all')
if not os.path.exists(all_bin_dir):
    os.makedirs(all_bin_dir)

# zip archives
print(dist_path)
print(all_bin_dir)
os.chdir(dist_path)

if os_type == 'win32':
    print('Compressing Windows executable')
    os.system('"7z.exe" a %s %s -mx0' % (os.path.join(all_bin_dir, 'DashMasternodeTool_' + version_str + '.win' + no_bits + '.zip'),  'DashMasternodeTool.exe'))
elif os_type == 'darwin':
    print('Compressing Mac executable')
    os.system('zip -r "%s" "%s"' % (os.path.join(all_bin_dir, 'DashMasternodeTool_' + version_str + '.mac.zip'),  'DashMasternodeTool.app'))
elif os_type == 'linux':
    print('Compressing Linux executable')
    os.system('tar -zcvf %s %s' % (os.path.join(all_bin_dir, 'DashMasternodeTool_' + version_str + '.linux.tar.gz'),  'DashMasternodeTool'))
