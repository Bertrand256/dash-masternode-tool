import os
import sys
import subprocess
import shutil
import platform

def run_command(command, shell=False):
    print(f"Running command: {command}")
    result = subprocess.run(command, shell=shell, check=True)
    return result

def main():
    os_type = sys.platform
    arch = platform.machine().lower()
    
    # Map architectures
    if arch in ['x86_64', 'amd64']:
        target_arch = 'x64'
    elif arch in ['arm64', 'aarch64']:
        target_arch = 'arm64'
    else:
        target_arch = arch

    print(f"Detected OS: {os_type}, Arch: {arch} (Target: {target_arch})")

    dist_path = os.path.join('dist', os_type)
    work_path = os.path.join('build', os_type)

    # Base pyinstaller command
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "-y",
        f"--distpath={dist_path}",
        f"--workpath={work_path}",
        "dash_masternode_tool.spec"
    ]

    # Platform specific adjustments if needed
    # (The .spec file already handles most of it)
    
    # Install dependencies using uv
    # We skip this if running in a environment where dependencies are already managed (like uv run)
    # but for completeness and local usage:
    # run_command(["uv", "pip", "install", "-r", "requirements.txt"])
    
    # Run pyinstaller
    run_command(cmd)

    if os_type == 'linux':
        print("Building AppImage...")
        subprocess.run(["bash", "build/ubuntu/build-appimage.sh"], check=True)
    elif os_type == 'darwin':
        print("Building DMG...")
        subprocess.run(["bash", "build/darwin/build-dmg.sh", target_arch], check=True)

    print("Build completed successfully.")

if __name__ == "__main__":
    main()
